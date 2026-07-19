# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake CLI — subcommand dispatcher.

Designed to be driven by an agent as much as by a human: every command
supports --json for machine-readable output, and the primitives are
intentionally thin (resolve / citing / sample / describe / classify /
render / override / cost / status) so an agent can compose an
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
    _build_fill_abstract_parser(sub)
    _build_render_parser(sub)
    _build_override_parser(sub)
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


def _build_render_parser(sub) -> None:
    p = sub.add_parser(
        "render",
        help="Assemble impact.md + impact.json from whatever has been classified so far. "
             "Works on partial data (marks coverage) or a fully classified set.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")


def _build_override_parser(sub) -> None:
    p = sub.add_parser(
        "override",
        help="Record a human-reviewed relationship override for one citing work. "
             "Wins over the LLM classification in the next render.",
    )
    from ..classify import RELATIONSHIPS
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to override.")
    p.add_argument("--relationship", required=True,
                   choices=RELATIONSHIPS,
                   help="The corrected relationship class.")
    p.add_argument("--justification", default="", help="One-line justification for the override.")


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


def run_render(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..citing import load_citing
    from ..classify import load_classified
    from ..report import render_and_save
    base = _work_dir_base(args)
    quiet = is_quiet(args)

    citing = load_citing(work["openalex_id"], base)
    if citing is None:
        emit_error("render", RuntimeError(
            "No citing works cached. Run `wake citing` first."
        ), as_json=args.json_out)
        sys.exit(1)

    classified = load_classified(work["openalex_id"], base)
    works = classified if classified is not None else citing

    json_path, md_path = render_and_save(work, works, base=base, verbose=not quiet)

    data = {"impact_json": str(json_path), "impact_md": str(md_path)}
    emit("render", data, as_json=args.json_out,
         human=lambda d: print(f"Report written:\n  {d['impact_md']}\n  {d['impact_json']}"))


def run_override(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ..report import add_override
    base = _work_dir_base(args)
    entry = add_override(
        work["openalex_id"], args.citing_id,
        relationship=args.relationship,
        justification=args.justification,
        base=base,
    )
    emit("override", entry, as_json=args.json_out,
         human=lambda d: print(f"Override recorded: {args.citing_id} -> {d['relationship']}"))


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
                f"No impact.md found at {md_path}. Run: wake citing / classify / render {args.seed}"
            ), as_json=args.json_out)
            sys.exit(1)
        text = md_path.read_text(encoding="utf-8")
        emit("show", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))

    elif what == "metrics":
        json_path = wd / "impact.json"
        if not json_path.exists():
            emit_error("show", RuntimeError(
                f"No impact.json found. Run: wake citing / classify / render {args.seed}"
            ), as_json=args.json_out)
            sys.exit(1)
        from ..io import read_json
        metrics = read_json(json_path)
        emit("show", metrics, as_json=args.json_out, human=lambda d: print(json.dumps(d, indent=2)))

    elif what == "top":
        json_path = wd / "impact.json"
        if not json_path.exists():
            emit_error("show", RuntimeError(
                f"No impact.json found. Run: wake citing / classify / render {args.seed}"
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


def run_config(args) -> None:
    from .. import config
    if args.config_action == "show":
        print(config.show())
    elif args.config_action == "validate":
        errors = config.validate()
        if not errors:
            print("[wake] Configuration OK.")
        else:
            for e in errors:
                print(f"  ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.config_action == "init":
        from .. import config as cfg
        path, created = cfg.init_local()
        if created:
            print(f"[wake] Created {path}")
        else:
            print(f"[wake] Already exists: {path}")


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
        elif args.command == "fill-abstract":
            run_fill_abstract(args)
        elif args.command == "render":
            run_render(args)
        elif args.command == "override":
            run_override(args)
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
