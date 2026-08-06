# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake narrative outline/section/stitch/refs-check/show.

Part of the cli/commands/ split (see PLAN.md "Phase 3 -- Structural
Hardening" / BACKLOG.md Theme L): cli/main.py used to hold every
command's parser-building and dispatch logic in one ~2,000-line file.
Each module here owns one command family's argparse subparser
construction (`_build_*_parser`) and handler (`run_*`) functions;
cli/main.py itself is reduced to constructing the top-level parser,
registering each family's parser, and dispatching to its `run_*`.
"""
from __future__ import annotations

import json
import sys

from ..emit import emit, emit_error
from ..main_helpers import _resolve_seed_to_work, _work_dir_base


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

    section_rerender_all = section_sub.add_parser(
        "rerender-all",
        help="Re-emit every section's .md from its .json sidecar -- a rendering-only "
             "pass (no change to any section's status or prose) that refreshes derived "
             "content like [ref:...] -> evidence-dossier links. Use after a wake "
             "upgrade changes section rendering, to backfill an existing wiki.",
    )
    section_rerender_all.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")

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
    from ...narrative import export_refs
    base = _work_dir_base(args)

    try:
        result = export_refs(work, base=base)
    except ValueError as exc:
        emit_error("narrative", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Refs exported: {d['refs_json_path']} ({d['reference_count']} reference(s))")
        print("  Run ref-checker yourself, e.g.:")
        print("    pipx install git+https://github.com/rbross-hpc/ref-checker.git  # once")
        print(f"    ref-checker check --refs-json {d['refs_json_path']} "
              f"--results-json {d['refs_json_path'].rsplit('.json', 1)[0]}.results.json")
        print("  Then: wake narrative refs-check summarize <seed> <results.json>")

    emit("narrative", result, as_json=args.json_out, human=human)


def run_narrative_refs_check_summarize(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...narrative import summarize_refs_check
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
    from ...narrative import narrative_md_path
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
    from ...narrative import create_outline
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
    from ...narrative import outline_md_path
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
    elif args.section_action == "rerender-all":
        run_narrative_section_rerender_all(args)


def run_narrative_section_create(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...narrative import create_section
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
    from ...narrative import confirm_section
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
    from ...narrative import section_md_path
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


def run_narrative_section_rerender_all(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...narrative import rerender_all_sections
    base = _work_dir_base(args)

    rerendered = rerender_all_sections(work["openalex_id"], work, base=base)
    emit(
        "narrative", {"ok": True, "rerendered": rerendered, "count": len(rerendered)},
        as_json=args.json_out,
        human=lambda d: print(f"Re-rendered {d['count']} section(s)."),
    )


def run_narrative_stitch(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...narrative import stitch
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
