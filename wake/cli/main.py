# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake CLI — subcommand dispatcher.

Designed to be driven by an agent as much as by a human: every command
supports --json for machine-readable output, and the primitives are
intentionally thin (resolve / citing / sample / describe / classify /
bake / override / cost / status) so an agent can compose an
explore-first workflow instead of running one opaque pipeline command.
See wake/skills/impact-analysis/SKILL.md for the recommended workflow.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .emit import emit, emit_error, is_quiet, progress


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wake",
        description="Evidence-backed impact analysis for research papers.",
    )
    p.add_argument("--json", action="store_true", dest="json_out",
                   help="Emit a machine-readable JSON envelope on stdout instead of human text.")
    p.add_argument("--work-dir", default=None, metavar="DIR",
                   help="Root directory for wake-out/ cache (default: $WAKE_WORK_DIR or cwd).")
    p.add_argument("--verbose", action="store_true",
                   help="Keep progress banners on stderr even when --json is set.")

    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    _build_resolve_parser(sub)
    _build_status_parser(sub)
    _build_citing_parser(sub)
    _build_sample_parser(sub)
    _build_describe_parser(sub)
    _build_classify_parser(sub)
    _build_gaps_parser(sub)
    _build_dedup_parser(sub)
    _build_fill_abstract_parser(sub)
    _build_fetch_pdf_parser(sub)
    _build_evidence_parser(sub)
    _build_theme_parser(sub)
    _build_narrative_parser(sub)
    _build_bake_parser(sub)
    _build_override_parser(sub)
    _build_exclude_parser(sub)
    _build_unexclude_parser(sub)
    _build_cost_parser(sub)
    _build_show_parser(sub)
    _build_config_parser(sub)
    _build_skill_parser(sub)

    return p


def _build_resolve_parser(sub) -> None:
    p = sub.add_parser("resolve", help="Resolve a seed ID to a canonical OpenAlex work.")
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID (W...), or paper title.")
    p.add_argument("--force", action="store_true", help="Re-resolve even if cached.")


def _build_status_parser(sub) -> None:
    p = sub.add_parser(
        "status",
        help="Show cached-artifact counts and estimated remaining cost for a seed. "
             "The first stop for explore-first analysis.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")


def _build_citing_parser(sub) -> None:
    p = sub.add_parser("citing", help="Fetch and cache all citing works for a seed.")
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("--min-year", type=int, default=None, metavar="Y", help="Only fetch works from Y onwards.")
    p.add_argument("--limit", type=int, default=None, metavar="N", help="Truncate output to N works (does not limit fetch).")
    p.add_argument("--sort", choices=["cited-by", "recent", "oldest", "random"], default=None,
                   help="Sort output works (does not affect what's fetched/cached).")
    p.add_argument("--force", action="store_true", help="Re-fetch even if cached.")


def _build_sample_parser(sub) -> None:
    p = sub.add_parser(
        "sample",
        help="Pick a representative slice of citing works for human review "
             "before spending on classification.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("-n", type=int, default=10, help="Sample size (default: 10).")
    p.add_argument("--sort", choices=["cited-by", "recent", "oldest", "random"], default="cited-by",
                   help="Sampling order (default: cited-by — most influential first).")


def _build_describe_parser(sub) -> None:
    p = sub.add_parser("describe", help="LLM one-paragraph contribution description of the seed.")
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("--force", action="store_true", help="Re-generate even if cached.")


def _build_classify_parser(sub) -> None:
    p = sub.add_parser("classify", help="LLM-classify citing works' relationship to the seed.")
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("--ids", default=None, metavar="ID,ID,...",
                   help="Classify only these citing OpenAlex IDs (comma-separated).")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Classify only the top N works after sorting (default: all).")
    p.add_argument("--sort", choices=["cited-by", "recent", "oldest", "random"], default="cited-by",
                   help="Selection order when --limit is used (default: cited-by).")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would be classified and estimated cost; make no LLM calls.")
    p.add_argument("--force", action="store_true", help="Re-classify even if cached.")
    p.add_argument("--delay", type=float, default=0.5, metavar="S", help="Seconds between LLM calls (default: 0.5).")


def _build_gaps_parser(sub) -> None:
    p = sub.add_parser(
        "gaps",
        help="Surface high-value citing works with no recoverable abstract "
             "(automatic backfill exhausted) — candidates for wake fill-abstract.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("--min-cited-by", type=int, default=None, metavar="N",
                   help="Only surface gaps whose own cited_by_count is >= N "
                        "(default: from config, gaps.min_cited_by_count).")
    p.add_argument("-n", "--limit", type=int, default=None, metavar="N",
                   help="Max number of gaps to surface (default: from config, gaps.default_limit).")
    p.add_argument("--no-auto-backfill-check", action="store_true",
                   help="Skip the OSTI/Semantic Scholar re-check (faster, but may surface "
                        "works that auto-backfill would have resolved anyway).")


def _build_dedup_parser(sub) -> None:
    p = sub.add_parser(
        "dedup",
        help="Surface likely-duplicate citing works (preprint/published pairs, workshop/"
             "journal expansions, or double-publications) for human sign-off. Never "
             "auto-merges -- one candidate at a time, same as every other human-in-the-"
             "loop command in wake.",
    )
    ssub = p.add_subparsers(dest="dedup_action", required=True, metavar="ACTION")

    candidates = ssub.add_parser(
        "candidates",
        help="Scan classified citing works for likely-duplicate pairs (title similarity "
             "+ shared author IDs). Read-only, deterministic, no LLM call. Pairs already "
             "confirmed or rejected are excluded.",
    )
    candidates.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    candidates.add_argument(
        "--min-title-similarity", type=float, default=0.85, metavar="F",
        help="Minimum title similarity (0.0-1.0) to surface a pair (default: 0.85).",
    )

    confirm = ssub.add_parser(
        "confirm",
        help="Record a human-confirmed duplicate: DUPLICATE_ID is the same work as "
             "CANONICAL_ID. wake persists this decision -- it never decides which pair "
             "is a duplicate itself. Always run by the agent on the human's behalf, one "
             "pair at a time -- never ask the human to run this command themselves.",
    )
    confirm.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    confirm.add_argument("duplicate_id", help="OpenAlex ID to be treated as a duplicate.")
    confirm.add_argument("canonical_id", help="OpenAlex ID of the canonical (kept) work.")
    confirm.add_argument("--reason", default="", help="One-line justification for the human's decision.")

    reject = ssub.add_parser(
        "reject",
        help="Record that a human looked at a candidate pair and judged them genuinely "
             "distinct works, not a duplicate -- so it isn't resurfaced by a later scan.",
    )
    reject.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    reject.add_argument("id_a", help="OpenAlex ID of one work in the pair.")
    reject.add_argument("id_b", help="OpenAlex ID of the other work in the pair.")
    reject.add_argument("--reason", default="", help="One-line justification for the human's decision.")


def _build_fill_abstract_parser(sub) -> None:
    p = sub.add_parser(
        "fill-abstract",
        help="Manually resolve a missing abstract for one citing work, "
             "from a local PDF's lead pages or human-supplied text.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to fill in.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-pdf", metavar="PATH",
                      help="Path to a locally-downloaded PDF of the citing work. "
                           "Extracts the first few pages (config.pdf_extract.max_pages, "
                           "default 3) and asks an LLM to locate the abstract within them.")
    src.add_argument("--text", metavar="TEXT",
                      help="The abstract text itself, supplied directly (no LLM call).")


def _build_fetch_pdf_parser(sub) -> None:
    p = sub.add_parser(
        "fetch-pdf",
        help="Try to automatically acquire a PDF for one citing work "
             "(OSTI, Semantic Scholar, Unpaywall, arXiv, optional CORE). "
             "Falls back to human-actionable links (incl. Google Scholar) on failure.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to fetch a PDF for.")
    p.add_argument("--force", action="store_true", help="Re-fetch even if already cached.")


def _build_evidence_parser(sub) -> None:
    p = sub.add_parser(
        "evidence",
        help="Full-text verification of one citing work's provisional classification: "
             "fetches the PDF, reads the whole document, and proposes a relationship "
             "with quoted, page-cited supporting passages. Never auto-applied -- "
             "the agent presents the finding to the human and runs `wake override` "
             "on their behalf once accepted.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to investigate.")
    p.add_argument("--force", action="store_true",
                   help="Re-run verification even if a dossier already exists (re-fetches "
                        "the PDF only if not already cached; use `wake fetch-pdf --force` "
                        "separately to force a fresh PDF download).")


def _build_theme_parser(sub) -> None:
    p = sub.add_parser(
        "theme",
        help="Combined-evidence thematic documents synthesizing several citing works.",
    )
    ssub = p.add_subparsers(dest="theme_action", required=True, metavar="ACTION")

    create = ssub.add_parser(
        "create",
        help="Write (or overwrite) a theme document. wake validates and persists this "
             "judgment -- it never decides which works belong together or writes the "
             "summary itself. Always a draft -- no LLM call; the agent supplies the "
             "title/summary/citing-ids after reading the underlying dossiers/"
             "classifications itself.",
    )
    create.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    create.add_argument("slug", help="Theme identifier, e.g. 'earth-system-modeling' (lowercase, hyphenated).")
    create.add_argument("--title", required=True, help="Human-readable theme title.")
    create.add_argument("--summary", required=True, help="Synthesis paragraph, written by the agent.")
    create.add_argument("--citing-ids", required=True, metavar="ID,ID,...",
                         help="Comma-separated OpenAlex IDs of the citing works that support this theme.")

    confirm = ssub.add_parser(
        "confirm",
        help="Human-approved sign-off promoting a theme from 'draft' to 'confirmed'. "
             "wake only validates the sign-off (every cited work already human-verified) "
             "and records it -- the human's approval is the actual decision. Always run "
             "by the agent on the human's behalf, never by asking the human to run this "
             "command themselves (see SKILL.md). Refuses unless every cited work is "
             "already human-verified via `wake override`.",
    )
    confirm.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    confirm.add_argument("slug", help="Theme identifier to confirm.")

    queue = ssub.add_parser(
        "queue",
        help="List outstanding work across all themes for a seed: citing works with no "
             "evidence dossier yet, and dossiers that have appeared since a theme was "
             "last created/reviewed but haven't been re-confirmed.",
    )
    queue.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")

    show = ssub.add_parser("show", help="Print an already-written theme document.")
    show.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    show.add_argument("slug", help="Theme identifier to print.")


def _build_narrative_parser(sub) -> None:
    p = sub.add_parser(
        "narrative",
        help="Draft a narrative from confirmed themes, one section at a time, then stitch.",
    )
    ssub = p.add_subparsers(dest="narrative_action", required=True, metavar="ACTION")

    outline = ssub.add_parser("outline", help="Plan the narrative's structure before drafting any prose.")
    outline_sub = outline.add_subparsers(dest="outline_action", required=True, metavar="ACTION")

    outline_create = outline_sub.add_parser(
        "create",
        help="Write (or overwrite) the narrative outline: an ordered list of components. "
             "wake validates the structure and persists it -- it never decides the "
             "narrative's shape. No LLM call, no confirmation of its own -- it's a plan, "
             "not a claim.",
    )
    outline_create.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    outline_create.add_argument(
        "--components", required=True, metavar="JSON",
        help='JSON list of components, e.g. \'[{"slug":"intro","title":"Introduction","kind":"free"},'
             '{"slug":"earth-adoption","title":"Earth-System Adoption","kind":"theme",'
             '"theme_slugs":["earth-system-modeling"]}]\'. kind is "theme" (requires non-empty '
             'theme_slugs, each an already-existing theme) or "free" (framing prose, no theme_slugs).',
    )

    outline_show = outline_sub.add_parser("show", help="Print the current narrative outline.")
    outline_show.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")

    section = ssub.add_parser("section", help="Draft or confirm one narrative section's prose.")
    section_sub = section.add_subparsers(dest="section_action", required=True, metavar="ACTION")

    section_create = section_sub.add_parser(
        "create",
        help="Write (or overwrite) one section's prose. wake validates and persists this "
             "prose -- it never writes it or decides what it should say. Always a draft "
             "-- no LLM call; the agent writes the prose after reading the underlying "
             "theme(s)/dossiers itself.",
    )
    section_create.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    section_create.add_argument("slug", help="Section identifier, matching a component in the outline.")
    section_create.add_argument("--title", required=True, help="Human-readable section title.")
    section_create.add_argument(
        "--prose", required=True,
        help="Drafted prose, written by the agent. Each factual sentence should end with a "
             "[ref:ID,ID,...] marker naming its source(s) -- SEED for the seed paper, or a "
             "citing work's OpenAlex ID. Every marker is validated against the packet: each "
             "ID must be SEED or a currently human-verified citing work.",
    )
    section_create.add_argument(
        "--theme-slugs", default="", metavar="SLUG,SLUG,...",
        help="Comma-separated theme slugs this section is grounded in (omit for a free-form section).",
    )

    section_confirm = section_sub.add_parser(
        "confirm",
        help="Human-approved sign-off promoting a section from 'draft' to 'confirmed'. wake "
             "only validates the sign-off (every referenced theme currently confirmed) and "
             "records it -- the human's approval is the actual decision. Always run by the "
             "agent on the human's behalf (see SKILL.md). For a theme-backed section, "
             "refuses unless every referenced theme is currently confirmed.",
    )
    section_confirm.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    section_confirm.add_argument("slug", help="Section identifier to confirm.")

    section_show = section_sub.add_parser("show", help="Print one already-drafted section's prose.")
    section_show.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    section_show.add_argument("slug", help="Section identifier to print.")

    stitch = ssub.add_parser(
        "stitch",
        help="Assemble the outline order + every drafted section into the top-level narrative.md. "
             "Works on partial data -- missing/still-draft sections are clearly labeled, not hidden.",
    )
    stitch.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")

    show = ssub.add_parser("show", help="Print the assembled top-level narrative.md.")
    show.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")

    refs_check = ssub.add_parser(
        "refs-check",
        help="Verify the stitched narrative's References list against live scholarly "
             "databases using the external ref-checker tool. wake never runs ref-checker "
             "itself -- 'export' writes ref-checker's input file, 'summarize' reads its "
             "output. The agent runs `ref-checker check` itself as a subprocess in between.",
    )
    refs_check_sub = refs_check.add_subparsers(dest="refs_check_action", required=True, metavar="ACTION")

    refs_check_export = refs_check_sub.add_parser(
        "export",
        help="Write narrative/refs.json in the shape `ref-checker check --refs-json` "
             "expects, numbered identically to narrative.md's [R1]/[R2]/... so a flagged "
             "index always maps back to the same reference the human sees in the document.",
    )
    refs_check_export.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")

    refs_check_summarize = refs_check_sub.add_parser(
        "summarize",
        help="Parse a ref-checker results sidecar (from `ref-checker check --refs-json "
             "narrative/refs.json --results-json <path>`) into a human-facing report of "
             "which references are OK vs. flagged for review.",
    )
    refs_check_summarize.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    refs_check_summarize.add_argument(
        "results_path", metavar="RESULTS_JSON",
        help="Path to the ref-checker results sidecar to summarize.",
    )


def _build_bake_parser(sub) -> None:
    p = sub.add_parser(
        "bake",
        help="Assemble impact.md + impact.json from whatever has been classified so far. "
             "Works on partial data (marks coverage) or a fully classified set.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")


def _build_override_parser(sub) -> None:
    p = sub.add_parser(
        "override",
        help="Record a human-reviewed relationship override for one citing work. wake "
             "persists this judgment -- it never decides the relationship itself, the "
             "human already has. Wins over the LLM classification in the next bake. "
             "Always run by the agent on the human's behalf -- never ask the human to "
             "run this command themselves (see SKILL.md).",
    )
    from ..classify import RELATIONSHIPS
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to override.")
    p.add_argument("--relationship", required=True,
                   choices=RELATIONSHIPS,
                   help="The corrected relationship class.")
    p.add_argument("--justification", default="", help="One-line justification for the override.")
    p.add_argument("--verification-source", default="human-judgment",
                   choices=["human-judgment", "evidence-dossier"],
                   help="How the human arrived at this judgment (default: human-judgment). "
                        "Use 'evidence-dossier' when the human accepted a `wake evidence` "
                        "full-text finding.")


def _build_exclude_parser(sub) -> None:
    p = sub.add_parser(
        "exclude",
        help="Record an explicit, permanent exclusion for one citing work -- judged not "
             "actually about the seed. wake persists this decision -- it never decides "
             "that a work should be excluded. Excluded works are refused by wake theme "
             "create and wake narrative reference validation, dropped from wake bake's "
             "reach metrics, and no longer surfaced by wake gaps/wake theme queue. "
             "Always run by the agent on the human's behalf, one work at a time.",
    )
    from .. import exclude as exclude_mod
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to exclude.")
    p.add_argument("--reason", required=True, help="Justification for the exclusion (required).")
    p.add_argument("--category", default="other", choices=exclude_mod.EXCLUSION_REASONS,
                   help="At-a-glance category for the exclusion (default: other).")


def _build_unexclude_parser(sub) -> None:
    p = sub.add_parser(
        "unexclude",
        help="Reverse a prior exclusion -- a separate, explicit action with its own "
             "required justification, never an implicit side effect of another command.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to un-exclude.")
    p.add_argument("--reason", required=True, help="Justification for reversing the exclusion (required).")


def _build_cost_parser(sub) -> None:
    p = sub.add_parser("cost", help="Show estimated LLM token/cost usage for a seed.")
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")


def _build_show_parser(sub) -> None:
    p = sub.add_parser("show", help="Re-emit cached results.")
    ssub = p.add_subparsers(dest="show_what", required=True, metavar="WHAT")

    sp = ssub.add_parser("brief", help="Print impact.md for a seed.")
    sp.add_argument("seed", help="OpenAlex ID or seed string.")

    sm = ssub.add_parser("metrics", help="Print impact.json metrics for a seed.")
    sm.add_argument("seed", help="OpenAlex ID or seed string.")

    st = ssub.add_parser("top", help="Print top-evidence table for a seed.")
    st.add_argument("seed", help="OpenAlex ID or seed string.")
    st.add_argument("-n", type=int, default=10, help="Number of top works to show (default: 10).")

    sd = ssub.add_parser("dossier", help="Print an already-built evidence dossier for one citing work.")
    sd.add_argument("seed", help="OpenAlex ID or seed string.")
    sd.add_argument("citing_id", help="OpenAlex ID of the citing work whose dossier to print.")


def _build_config_parser(sub) -> None:
    p = sub.add_parser("config", help="Show, validate, or initialise wake configuration.")
    ssub = p.add_subparsers(dest="config_action", required=True, metavar="ACTION")
    ssub.add_parser("show", help="Print resolved configuration.")
    ssub.add_parser("validate", help="Validate configuration and environment.")
    ssub.add_parser("init", help="Write a starter wake.config.yaml in the current directory.")


def _build_skill_parser(sub) -> None:
    p = sub.add_parser("skill", help="Show or export the bundled Agent Skill.")
    ssub = p.add_subparsers(dest="skill_action", required=True, metavar="ACTION")
    ssub.add_parser("show", help="Print the bundled SKILL.md to stdout.")
    ep = ssub.add_parser("export", help="Copy the skill directory to PATH.")
    ep.add_argument("path", metavar="PATH", help="Destination directory.")
    ep.add_argument("--force", action="store_true", help="Overwrite if non-empty.")


def _work_dir_base(args) -> Path | None:
    wd = getattr(args, "work_dir", None)
    return Path(wd).resolve() if wd else None


def _resolve_seed_to_work(seed_str: str, args, force: bool = False) -> dict:
    from ..seed import resolve_and_cache
    from ..errors import SeedNotFound
    try:
        return resolve_and_cache(seed_str, base=_work_dir_base(args), force=force)
    except SeedNotFound as exc:
        emit_error("resolve", exc, as_json=args.json_out)
        sys.exit(1)


def run_resolve(args) -> None:
    work = _resolve_seed_to_work(args.seed, args, force=args.force)

    def human(w):
        from ..seed import print_seed_table
        print_seed_table(w)

    emit("resolve", work, as_json=args.json_out, human=human)


def run_status(args) -> None:
    from .. import config, cost as cost_mod
    from ..citing import load_citing
    from ..classify import _model as classify_model, load_classified
    from ..describe import _model as describe_model

    work = _resolve_seed_to_work(args.seed, args)
    oid = work["openalex_id"]
    base = _work_dir_base(args)

    citing = load_citing(oid, base) or []
    classified = load_classified(oid, base) or []
    classified_ids = {w.get("openalex_id") for w in classified if w.get("relationship")}
    pending = [w for w in citing if w.get("openalex_id") not in classified_ids]

    cost_summary = cost_mod.summarize(oid, base)
    remaining_est = cost_mod.estimate_remaining_classify_cost(
        oid, classify_model(), len(pending), base=base,
    )

    data = {
        "seed": {
            "openalex_id": oid,
            "title": work.get("title"),
            "cited_by_count": work.get("cited_by_count", 0),
        },
        "cached": {
            "citing_fetched": len(citing) if citing else 0,
            "citing_available": bool(citing),
            "described": bool(work.get("description")),
            "classified": len(classified_ids),
        },
        "pending_classify": len(pending),
        "cost_so_far": cost_summary,
        "estimated_remaining_classify_cost": remaining_est,
    }

    def human(d):
        c = d["cached"]
        print(f"Seed: {d['seed']['title']} ({d['seed']['openalex_id']})")
        print(f"  Total citations (OpenAlex): {d['seed']['cited_by_count']:,}")
        print(f"  Citing works fetched      : {c['citing_fetched']:,}" if c["citing_available"]
              else "  Citing works fetched      : (not fetched yet — run `wake citing`)")
        print(f"  Description generated     : {'yes' if c['described'] else 'no'}")
        print(f"  Classified                : {c['classified']:,}")
        print(f"  Pending classification    : {d['pending_classify']:,}")
        cs = d["cost_so_far"]
        print(f"  Cost so far (estimate)    : ${cs['total_cost_usd_est']:.4f}"
              + (" (unpriced model)" if cs["any_unpriced"] else ""))
        rem = d["estimated_remaining_classify_cost"]
        if rem["pending_count"]:
            print(f"  Est. cost to finish       : ${rem['total_cost_usd_est']:.4f}"
                  + (" (unpriced model)" if rem["unpriced"] else ""))

    emit("status", data, as_json=args.json_out, human=human)


def run_citing(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..citing import fetch_and_cache, filter_works
    quiet = is_quiet(args)
    works = fetch_and_cache(
        work["openalex_id"],
        base=_work_dir_base(args),
        force=args.force,
        min_year=args.min_year,
        verbose=not quiet,
    )
    works = filter_works(works, min_year=args.min_year, limit=args.limit, sort=args.sort)

    def human(ws):
        print(f"Citing works: {len(ws):,}")
        for w in ws[:20]:
            print(f"  [{w.get('year','?')}] {w.get('title','?')[:80]}  ({w.get('cited_by_count',0):,} cites)")
        if len(ws) > 20:
            print(f"  ... and {len(ws) - 20:,} more")

    emit("citing", {"count": len(works), "works": works}, as_json=args.json_out, human=lambda d: human(d["works"]))


def run_sample(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..citing import fetch_and_cache, sample_works
    quiet = is_quiet(args)
    citing = fetch_and_cache(work["openalex_id"], base=_work_dir_base(args), verbose=not quiet)
    sample = sample_works(citing, n=args.n, sort=args.sort)

    def human(ws):
        print(f"Sample of {len(ws)} citing works (sort={args.sort}):")
        for w in ws:
            abstract_flag = "" if w.get("abstract") else "  [no abstract]"
            print(f"  [{w.get('year','?')}] {w.get('title','?')[:70]}"
                  f"  ({w.get('cited_by_count',0):,} cites){abstract_flag}")

    emit("sample", {"count": len(sample), "works": sample}, as_json=args.json_out,
         human=lambda d: human(d["works"]))


def run_describe(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..describe import describe_and_cache
    quiet = is_quiet(args)
    description = describe_and_cache(work, base=_work_dir_base(args), force=args.force, verbose=not quiet)
    emit("describe", {"description": description}, as_json=args.json_out,
         human=lambda d: print(d["description"]))


def run_classify(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..citing import fetch_and_cache
    from ..classify import classify_all
    base = _work_dir_base(args)
    quiet = is_quiet(args)

    citing = fetch_and_cache(work["openalex_id"], base=base, verbose=not quiet)
    ids = [s.strip() for s in args.ids.split(",")] if args.ids else None

    result = classify_all(
        work,
        citing,
        base=base,
        force=args.force,
        verbose=not quiet,
        inter_call_delay=args.delay,
        ids=ids,
        limit=args.limit,
        sort=args.sort,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        from ..classify import save_classified
        save_classified(work["openalex_id"], result, base=base)

    from collections import Counter
    classified_only = [w for w in result if w.get("relationship")]
    errored_only = [w for w in result if w.get("error") and not w.get("relationship")]
    counts = Counter(w.get("relationship", "?") for w in classified_only)

    data = {
        "dry_run": args.dry_run,
        "total_citing": len(citing),
        "classified_count": len(classified_only),
        "error_count": len(errored_only),
        "by_relationship": dict(counts),
    }

    def human(d):
        label = "Would classify" if d["dry_run"] else "Classified"
        print(f"{label}: {d['classified_count']:,} of {d['total_citing']:,} citing works")
        if d["error_count"]:
            print(f"  ({d['error_count']:,} failed and will be retried on next run)")
        for rel, cnt in sorted(d["by_relationship"].items(), key=lambda x: x[1], reverse=True):
            print(f"  {rel:<25} {cnt:>5}")

    emit("classify", data, as_json=args.json_out, human=human)


def run_gaps(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..citing import fetch_and_cache
    from ..gaps import find_gaps
    base = _work_dir_base(args)
    quiet = is_quiet(args)

    citing = fetch_and_cache(work["openalex_id"], base=base, verbose=not quiet)
    gaps = find_gaps(
        citing,
        seed_id=work["openalex_id"],
        base=base,
        min_cited_by_count=args.min_cited_by,
        limit=args.limit,
        try_auto_backfill=not args.no_auto_backfill_check,
        verbose=not quiet,
    )

    data = {
        "count": len(gaps),
        "gaps": [
            {
                "openalex_id": g.get("openalex_id"),
                "title": g.get("title"),
                "year": g.get("year"),
                "venue": g.get("venue"),
                "doi": g.get("doi"),
                "url": g.get("url"),
                "cited_by_count": g.get("cited_by_count", 0),
            }
            for g in gaps
        ],
    }

    def human(d):
        if not d["gaps"]:
            print("No high-value abstract gaps found (all above threshold "
                  "have an abstract, or none meet the citation threshold).")
            return
        print(f"{d['count']} high-value citing work(s) with no recoverable abstract:")
        print()
        for g in d["gaps"]:
            print(f"  {g['openalex_id']}  ({g['cited_by_count']:,} cites, {g.get('year','?')})")
            print(f"    {g['title']}")
            if g.get("doi"):
                print(f"    DOI: {g['doi']}")
            if g.get("url"):
                print(f"    URL: {g['url']}")
            print()
        print("Resolve with:")
        print(f"  wake fill-abstract {args.seed} <openalex-id> --from-pdf <path/to.pdf>")
        print(f"  wake fill-abstract {args.seed} <openalex-id> --text \"...\"")

    emit("gaps", data, as_json=args.json_out, human=human)


def run_dedup(args) -> None:
    if args.dedup_action == "candidates":
        run_dedup_candidates(args)
    elif args.dedup_action == "confirm":
        run_dedup_confirm(args)
    elif args.dedup_action == "reject":
        run_dedup_reject(args)


def run_dedup_candidates(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..dedup import dedup_candidates
    base = _work_dir_base(args)

    candidates = dedup_candidates(
        work["openalex_id"], base=base, min_title_similarity=args.min_title_similarity,
    )

    def human(cands):
        if not cands:
            print("No likely-duplicate pairs found.")
            return
        print(f"{len(cands)} likely-duplicate pair(s), highest similarity first:")
        print()
        for c in cands:
            print(f"  [{c['likely_kind']}]  similarity {c['title_similarity']:.2f}")
            print(f"    A: {c['citing_id_a']}  ({c.get('year_a','?')}, {c.get('type_a','?')})  {c['title_a']}")
            print(f"    B: {c['citing_id_b']}  ({c.get('year_b','?')}, {c.get('type_b','?')})  {c['title_b']}")
            if c["overlapping_authors"]:
                print(f"    Shared author(s): {', '.join(c['overlapping_authors'])}")
            print()
        print("Present each pair to the human, then run on their behalf:")
        print(f"  wake dedup confirm {args.seed} <duplicate-id> <canonical-id> --reason \"...\"")
        print(f"  wake dedup reject {args.seed} <id-a> <id-b> --reason \"...\"")

    emit("dedup", {"count": len(candidates), "candidates": candidates}, as_json=args.json_out,
         human=lambda d: human(d["candidates"]))


def run_dedup_confirm(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..dedup import confirm_duplicate
    base = _work_dir_base(args)

    try:
        result = confirm_duplicate(
            work["openalex_id"], args.duplicate_id, args.canonical_id,
            reason=args.reason, base=base,
        )
    except ValueError as exc:
        emit_error("dedup", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Recorded: {d['duplicate_id']} is a duplicate of {d['canonical_id']}.")
        print(f"  {d['duplicate_id']} is now excluded from bake/theme/narrative -- "
              f"cite {d['canonical_id']} instead.")

    emit("dedup", result, as_json=args.json_out, human=human)


def run_dedup_reject(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..dedup import reject_candidate
    base = _work_dir_base(args)

    try:
        result = reject_candidate(work["openalex_id"], args.id_a, args.id_b, reason=args.reason, base=base)
    except ValueError as exc:
        emit_error("dedup", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Recorded: {d['id_a']} and {d['id_b']} are not duplicates -- both remain fully usable.")

    emit("dedup", result, as_json=args.json_out, human=human)


def run_fill_abstract(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..gaps import fill_from_pdf, fill_from_text
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]

    try:
        if args.from_pdf:
            entry = fill_from_pdf(seed_id, args.citing_id, args.from_pdf, base=base)
        else:
            entry = fill_from_text(seed_id, args.citing_id, args.text, base=base)
    except (FileNotFoundError, ValueError, ImportError) as exc:
        emit_error("fill-abstract", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Abstract recorded for {args.citing_id} (source: {d['abstract_source']}):")
        print(f"  {d['abstract'][:300]}{'...' if len(d['abstract']) > 300 else ''}")
        print()
        print("This will be picked up automatically the next time you run:")
        print(f"  wake classify {args.seed} --ids {args.citing_id} --force")

    emit("fill-abstract", entry, as_json=args.json_out, human=human)


def _find_citing_work(seed_id: str, citing_id: str, base) -> dict | None:
    from ..citing import load_citing
    works = load_citing(seed_id, base) or []
    for w in works:
        if w.get("openalex_id") == citing_id:
            return w
    return None


def run_fetch_pdf(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..pdf_fetch import fetch_pdf
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]
    quiet = is_quiet(args)

    citing_work = _find_citing_work(seed_id, args.citing_id, base)
    if citing_work is None:
        emit_error("fetch-pdf", RuntimeError(
            f"{args.citing_id} not found in cached citing works. "
            f"Run `wake citing {args.seed}` first."
        ), as_json=args.json_out)
        sys.exit(1)

    result = fetch_pdf(
        seed_id, args.citing_id,
        doi=citing_work.get("doi"),
        title=citing_work.get("title"),
        base=base,
        force=args.force,
        verbose=not quiet,
    )

    def human(d):
        if d["ok"]:
            print(f"PDF acquired via {d['source']}: {d['path']}")
        else:
            tried = ", ".join(d["tried"]) if d["tried"] else "(no applicable sources)"
            print(f"Could not automatically acquire a PDF (tried: {tried}).")
            print("Try one of these manually:")
            for label, url in d["fallback_links"].items():
                print(f"  {label}: {url}")

    emit("fetch-pdf", result, as_json=args.json_out, human=human)


def _find_classified_work(seed_id: str, citing_id: str, base) -> dict | None:
    """Find a citing work's *classified* record (with relationship/
    confidence/justification), falling back to the plain citing-works
    record if it hasn't been classified yet."""
    from ..classify import load_classified
    classified = load_classified(seed_id, base) or []
    for w in classified:
        if w.get("openalex_id") == citing_id:
            return w
    return _find_citing_work(seed_id, citing_id, base)


def run_evidence(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..evidence import build_dossier
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]
    quiet = is_quiet(args)

    citing_work = _find_classified_work(seed_id, args.citing_id, base)
    if citing_work is None:
        emit_error("evidence", RuntimeError(
            f"{args.citing_id} not found in cached citing works. "
            f"Run `wake citing {args.seed}` first."
        ), as_json=args.json_out)
        sys.exit(1)
    if not citing_work.get("relationship"):
        emit_error("evidence", RuntimeError(
            f"{args.citing_id} has not been classified yet. "
            f"Run `wake classify {args.seed} --ids {args.citing_id}` first "
            "so there's a provisional classification to verify against."
        ), as_json=args.json_out)
        sys.exit(1)

    result = build_dossier(work, citing_work, base=base, force=args.force, verbose=not quiet)

    def human(d):
        if not d["ok"]:
            if d["reason"] == "no_pdf":
                fr = d["fetch_result"]
                tried = ", ".join(fr.get("tried", [])) or "(no applicable sources)"
                print(f"Could not acquire a PDF to verify against (tried: {tried}).")
                print("Try one of these manually, then run:")
                print(f"  wake fetch-pdf {args.seed} {args.citing_id}  (after obtaining a PDF)")
                for label, url in fr.get("fallback_links", {}).items():
                    print(f"  {label}: {url}")
            else:
                print(f"Evidence verification failed: {d.get('message', d['reason'])}")
            return

        prov = d["provisional"]
        prop = d["proposed"]
        print(f"Provisional (abstract-only): {prov['relationship']} (confidence {prov['confidence']:.2f})")
        print(f"Proposed (full-text reading): {prop['relationship']} (confidence {prop['confidence']:.2f})")
        print(f"  {prop['justification']}")
        if not prop["agrees_with_provisional"]:
            print("  -> differs from the provisional guess")
        print()
        if d["quotes"]:
            print(f"{len(d['quotes'])} supporting passage(s) — see dossier for full context:")
            print(f"  {d['dossier_path']}")
        else:
            print("No supporting passages found in the full text.")
        print()
        print(
            "This is a proposed finding, not applied to the brief. Present the "
            "quoted passages to the human, then run `wake override` yourself "
            "once they accept or adjust it — never ask the human to run the "
            "override command."
        )

    emit("evidence", result, as_json=args.json_out, human=human)


def run_theme(args) -> None:
    if args.theme_action == "create":
        run_theme_create(args)
    elif args.theme_action == "confirm":
        run_theme_confirm(args)
    elif args.theme_action == "queue":
        run_theme_queue(args)
    elif args.theme_action == "show":
        run_theme_show(args)


def run_theme_create(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..themes import create_theme
    base = _work_dir_base(args)
    citing_ids = [c.strip() for c in args.citing_ids.split(",") if c.strip()]

    try:
        result = create_theme(
            work, args.slug,
            title=args.title, summary=args.summary, citing_ids=citing_ids,
            base=base,
        )
    except ValueError as exc:
        emit_error("theme", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Theme written (draft): {d['theme_path']}")
        if d["needs_evidence"]:
            print(f"  {len(d['needs_evidence'])} cited work(s) have no evidence dossier yet: "
                  f"{', '.join(d['needs_evidence'])}")
        print("  Present to the human; run `wake theme confirm` on their behalf once "
              "they approve (requires every cited work to be human-verified first).")

    emit("theme", result, as_json=args.json_out, human=human)


def run_theme_confirm(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..themes import confirm_theme
    base = _work_dir_base(args)

    try:
        result = confirm_theme(work, args.slug, base=base)
    except ValueError as exc:
        emit_error("theme", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        if not d["ok"]:
            print(d["message"])
            return
        print(f"Theme confirmed: {d['theme_path']}")

    emit("theme", result, as_json=args.json_out, human=human)
    if not result["ok"]:
        sys.exit(1)


def run_theme_queue(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..themes import list_theme_needs_evidence
    base = _work_dir_base(args)

    entries = list_theme_needs_evidence(work["openalex_id"], base)

    def human(d):
        if not d:
            print("No outstanding theme work.")
            return
        by_theme: dict[str, list[dict]] = {}
        for e in d:
            by_theme.setdefault(e["theme_slug"], []).append(e)
        for slug, items in by_theme.items():
            print(f'Theme "{slug}":')
            for item in items:
                if item["status"] == "dossier-available-unreviewed":
                    print(f"  {item['citing_id']} — dossier now available — re-review and "
                          "re-run `wake theme create` to confirm it still supports this theme")
                else:
                    print(f"  {item['citing_id']} — still needs a `wake evidence` dossier")

    emit("theme", {"queue": entries}, as_json=args.json_out, human=lambda d: human(d["queue"]))


def run_theme_show(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..themes import theme_path
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]

    p = theme_path(seed_id, args.slug, base)
    if not p.exists():
        emit_error("theme", RuntimeError(
            f"No theme {args.slug!r} found for {args.seed}. Run `wake theme create` first."
        ), as_json=args.json_out)
        sys.exit(1)

    text = p.read_text(encoding="utf-8")
    emit("theme", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))


def run_narrative(args) -> None:
    if args.narrative_action == "outline":
        run_narrative_outline(args)
    elif args.narrative_action == "section":
        run_narrative_section(args)
    elif args.narrative_action == "stitch":
        run_narrative_stitch(args)
    elif args.narrative_action == "show":
        run_narrative_show(args)
    elif args.narrative_action == "refs-check":
        run_narrative_refs_check(args)


def run_narrative_refs_check(args) -> None:
    if args.refs_check_action == "export":
        run_narrative_refs_check_export(args)
    elif args.refs_check_action == "summarize":
        run_narrative_refs_check_summarize(args)


def run_narrative_refs_check_export(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..narrative import export_refs
    base = _work_dir_base(args)

    try:
        result = export_refs(work, base=base)
    except ValueError as exc:
        emit_error("narrative", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Refs exported: {d['refs_json_path']} ({d['reference_count']} reference(s))")
        print("  Run ref-checker yourself, e.g.:")
        print(f"    pipx install git+https://github.com/rbross-hpc/ref-checker.git  # once")
        print(f"    ref-checker check --refs-json {d['refs_json_path']} "
              f"--results-json {d['refs_json_path'].rsplit('.json', 1)[0]}.results.json")
        print("  Then: wake narrative refs-check summarize <seed> <results.json>")

    emit("narrative", result, as_json=args.json_out, human=human)


def run_narrative_refs_check_summarize(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..narrative import summarize_refs_check
    base = _work_dir_base(args)

    try:
        result = summarize_refs_check(work["openalex_id"], args.results_path, base=base)
    except ValueError as exc:
        emit_error("narrative", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"ref-checker results: {d['ok_count']}/{d['total']} OK, {d['flagged_count']} flagged for review.")
        for entry in d["flagged"]:
            print(f"  [R{entry['index']}] {entry['status']}: {entry['title']}")
            if entry.get("year_mismatch_note"):
                print(f"      {entry['year_mismatch_note']}")
            for note in entry.get("id_notes", []):
                print(f"      {note}")
            for url in entry.get("dead_urls", []):
                print(f"      dead URL: {url}")
            for src in entry.get("exhausted_sources", []):
                print(f"      retries exhausted for {src} — results may be incomplete")
        if not d["flagged"]:
            print("  All references resolved cleanly.")

    emit("narrative", result, as_json=args.json_out, human=human)


def run_narrative_show(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..narrative import narrative_md_path
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]

    p = narrative_md_path(seed_id, base)
    if not p.exists():
        emit_error("narrative", RuntimeError(
            f"No assembled narrative found for {args.seed}. Run `wake narrative stitch` first."
        ), as_json=args.json_out)
        sys.exit(1)

    text = p.read_text(encoding="utf-8")
    emit("narrative", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))


def run_narrative_outline(args) -> None:
    if args.outline_action == "create":
        run_narrative_outline_create(args)
    elif args.outline_action == "show":
        run_narrative_outline_show(args)


def run_narrative_outline_create(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..narrative import create_outline
    base = _work_dir_base(args)

    try:
        components = json.loads(args.components)
    except json.JSONDecodeError as exc:
        emit_error("narrative", ValueError(f"--components must be valid JSON: {exc}"), as_json=args.json_out)
        sys.exit(1)

    try:
        result = create_outline(work, components=components, base=base)
    except ValueError as exc:
        emit_error("narrative", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Outline written: {d['outline_path']}")
        for c in d["components"]:
            print(f"  - {c['title']} ({c['slug']}, {c['kind']})")
        print("  Draft each section with `wake narrative section create`, then "
              "`wake narrative stitch` to assemble narrative.md.")

    emit("narrative", result, as_json=args.json_out, human=human)


def run_narrative_outline_show(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..narrative import outline_md_path
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]

    p = outline_md_path(seed_id, base)
    if not p.exists():
        emit_error("narrative", RuntimeError(
            f"No narrative outline found for {args.seed}. Run `wake narrative outline create` first."
        ), as_json=args.json_out)
        sys.exit(1)

    text = p.read_text(encoding="utf-8")
    emit("narrative", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))


def run_narrative_section(args) -> None:
    if args.section_action == "create":
        run_narrative_section_create(args)
    elif args.section_action == "confirm":
        run_narrative_section_confirm(args)
    elif args.section_action == "show":
        run_narrative_section_show(args)


def run_narrative_section_create(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..narrative import create_section
    base = _work_dir_base(args)
    theme_slugs = [t.strip() for t in args.theme_slugs.split(",") if t.strip()]

    try:
        result = create_section(
            work, args.slug,
            title=args.title, prose=args.prose, theme_slugs=theme_slugs,
            base=base,
        )
    except ValueError as exc:
        emit_error("narrative", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Section written (draft): {d['section_path']}")
        if d["theme_slugs"]:
            print(f"  Grounded in theme(s): {', '.join(d['theme_slugs'])}")
        print("  Present to the human; run `wake narrative section confirm` on their behalf "
              "once they approve" + (" (requires every referenced theme to be currently confirmed)."
              if d["theme_slugs"] else "."))

    emit("narrative", result, as_json=args.json_out, human=human)


def run_narrative_section_confirm(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..narrative import confirm_section
    base = _work_dir_base(args)

    try:
        result = confirm_section(work, args.slug, base=base)
    except ValueError as exc:
        emit_error("narrative", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        if not d["ok"]:
            print(d["message"])
            return
        print(f"Section confirmed: {d['section_path']}")

    emit("narrative", result, as_json=args.json_out, human=human)
    if not result["ok"]:
        sys.exit(1)


def run_narrative_section_show(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..narrative import section_md_path
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]

    p = section_md_path(seed_id, args.slug, base)
    if not p.exists():
        emit_error("narrative", RuntimeError(
            f"No section {args.slug!r} found for {args.seed}. Run `wake narrative section create` first."
        ), as_json=args.json_out)
        sys.exit(1)

    text = p.read_text(encoding="utf-8")
    emit("narrative", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))


def run_narrative_stitch(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..narrative import stitch
    base = _work_dir_base(args)

    try:
        result = stitch(work, base=base)
    except ValueError as exc:
        emit_error("narrative", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Narrative written: {d['narrative_path']}")
        print(f"  {d['confirmed_sections']} confirmed, {d['draft_sections']} draft, "
              f"{len(d['missing_sections'])} not yet written.")
        if d["missing_sections"]:
            print(f"  Missing: {', '.join(d['missing_sections'])}")

    emit("narrative", result, as_json=args.json_out, human=human)


def run_bake(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..citing import load_citing
    from ..classify import load_classified
    from ..report import bake_and_save
    base = _work_dir_base(args)
    quiet = is_quiet(args)

    citing = load_citing(work["openalex_id"], base)
    if citing is None:
        emit_error("bake", RuntimeError(
            "No citing works cached. Run `wake citing` first."
        ), as_json=args.json_out)
        sys.exit(1)

    classified = load_classified(work["openalex_id"], base)
    works = classified if classified is not None else citing

    json_path, md_path = bake_and_save(work, works, base=base, verbose=not quiet)

    data = {"impact_json": str(json_path), "impact_md": str(md_path)}
    emit("bake", data, as_json=args.json_out,
         human=lambda d: print(f"Report written:\n  {d['impact_md']}\n  {d['impact_json']}"))


def run_override(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..report import add_override
    base = _work_dir_base(args)
    entry = add_override(
        work["openalex_id"], args.citing_id,
        relationship=args.relationship,
        justification=args.justification,
        verification_source=args.verification_source,
        seed_title=work.get("title"),
        base=base,
    )
    emit("override", entry, as_json=args.json_out,
         human=lambda d: print(f"Override recorded: {args.citing_id} -> {d['relationship']}"))


def run_exclude(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..exclude import exclude_work
    base = _work_dir_base(args)

    try:
        result = exclude_work(
            work["openalex_id"], args.citing_id,
            reason=args.reason, category=args.category, base=base,
        )
    except ValueError as exc:
        emit_error("exclude", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Excluded: {d['citing_id']} ({d['category']}) — {d['reason']}")
        print("  Now refused by wake theme create and wake narrative reference validation, "
              "dropped from wake bake's reach metrics, and no longer surfaced by "
              "wake gaps/wake theme queue.")

    emit("exclude", result, as_json=args.json_out, human=human)


def run_unexclude(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..exclude import unexclude_work
    base = _work_dir_base(args)

    try:
        result = unexclude_work(work["openalex_id"], args.citing_id, reason=args.reason, base=base)
    except ValueError as exc:
        emit_error("unexclude", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Un-excluded: {d['citing_id']} — {d['reason']}")
        print("  Fully usable again in theme/narrative/bake.")

    emit("unexclude", result, as_json=args.json_out, human=human)


def run_cost(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from .. import cost as cost_mod
    base = _work_dir_base(args)
    summary = cost_mod.summarize(work["openalex_id"], base)

    def human(d):
        print(f"Total calls: {d['total_calls']:,}")
        print(f"Total estimated cost: ${d['total_cost_usd_est']:.4f}"
              + (" (some models unpriced)" if d["any_unpriced"] else ""))
        for stage, s in d["by_stage"].items():
            print(f"  {stage:<12} calls={s['calls']:>4}  "
                  f"in={s['in_tokens_est']:>7,}  out={s['out_tokens_est']:>6,}  "
                  f"cost_est=${s['cost_usd_est']:.4f}")

    emit("cost", summary, as_json=args.json_out, human=human)


def run_show(args) -> None:
    from ..seed import resolve_and_cache, work_dir
    from ..errors import SeedNotFound

    what = args.show_what
    base = _work_dir_base(args)
    try:
        work = resolve_and_cache(args.seed, base=base)
    except SeedNotFound as exc:
        emit_error("show", exc, as_json=args.json_out)
        sys.exit(1)

    oid = work["openalex_id"]
    wd = work_dir(oid, base)

    if what == "brief":
        md_path = wd / "impact.md"
        if not md_path.exists():
            emit_error("show", RuntimeError(
                f"No impact.md found at {md_path}. Run: wake citing / classify / bake {args.seed}"
            ), as_json=args.json_out)
            sys.exit(1)
        text = md_path.read_text(encoding="utf-8")
        emit("show", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))

    elif what == "metrics":
        json_path = wd / "impact.json"
        if not json_path.exists():
            emit_error("show", RuntimeError(
                f"No impact.json found. Run: wake citing / classify / bake {args.seed}"
            ), as_json=args.json_out)
            sys.exit(1)
        from ..io import read_json
        metrics = read_json(json_path)
        emit("show", metrics, as_json=args.json_out, human=lambda d: print(json.dumps(d, indent=2)))

    elif what == "top":
        json_path = wd / "impact.json"
        if not json_path.exists():
            emit_error("show", RuntimeError(
                f"No impact.json found. Run: wake citing / classify / bake {args.seed}"
            ), as_json=args.json_out)
            sys.exit(1)
        from ..io import read_json
        metrics = read_json(json_path)
        top = metrics.get("top_evidence", [])[:args.n]

        def human(t):
            for i, ev in enumerate(t, 1):
                print(
                    f"{i:>3}. [{ev.get('relationship','?'):<22}] "
                    f"{ev.get('title','?')[:60]}  "
                    f"({ev.get('cited_by_count',0):,} cites)"
                )

        emit("show", {"top_evidence": top}, as_json=args.json_out, human=lambda d: human(d["top_evidence"]))

    elif what == "dossier":
        from ..evidence import dossier_path
        p = dossier_path(oid, args.citing_id, base)
        if not p.exists():
            emit_error("show", RuntimeError(
                f"No dossier found for {args.citing_id}. Run `wake evidence {args.seed} {args.citing_id}` first."
            ), as_json=args.json_out)
            sys.exit(1)
        text = p.read_text(encoding="utf-8")
        emit("show", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))


def run_config(args) -> None:
    from .. import config

    if args.config_action == "show":
        text = config.show()
        emit("config", {"text": text, "env": config.env_status()},
             as_json=args.json_out, human=lambda d: print(d["text"]))

    elif args.config_action == "validate":
        report = config.validate_report()

        def human(d):
            if d["ok"]:
                print("[wake] Configuration OK.")
            else:
                for e in d["errors"]:
                    print(f"  ERROR: {e}", file=sys.stderr)

        emit("config", report, as_json=args.json_out, human=human)
        if not report["ok"]:
            sys.exit(1)

    elif args.config_action == "init":
        path, created = config.init_local()
        data = {"path": str(path), "created": created}

        def human(d):
            if d["created"]:
                print(f"[wake] Created {d['path']}")
            else:
                print(f"[wake] Already exists: {d['path']}")

        emit("config", data, as_json=args.json_out, human=human)


def run_skill(args) -> None:
    from ..cli.skill import run_skill as _run
    _run(args)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "resolve":
            run_resolve(args)
        elif args.command == "status":
            run_status(args)
        elif args.command == "citing":
            run_citing(args)
        elif args.command == "sample":
            run_sample(args)
        elif args.command == "describe":
            run_describe(args)
        elif args.command == "classify":
            run_classify(args)
        elif args.command == "gaps":
            run_gaps(args)
        elif args.command == "dedup":
            run_dedup(args)
        elif args.command == "fill-abstract":
            run_fill_abstract(args)
        elif args.command == "fetch-pdf":
            run_fetch_pdf(args)
        elif args.command == "evidence":
            run_evidence(args)
        elif args.command == "theme":
            run_theme(args)
        elif args.command == "narrative":
            run_narrative(args)
        elif args.command == "bake":
            run_bake(args)
        elif args.command == "override":
            run_override(args)
        elif args.command == "exclude":
            run_exclude(args)
        elif args.command == "unexclude":
            run_unexclude(args)
        elif args.command == "cost":
            run_cost(args)
        elif args.command == "show":
            run_show(args)
        elif args.command == "config":
            run_config(args)
        elif args.command == "skill":
            run_skill(args)
    except KeyboardInterrupt:
        print("\n[wake] Interrupted.", file=sys.stderr)
        sys.exit(130)
