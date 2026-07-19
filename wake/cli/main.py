# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake CLI — subcommand dispatcher."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wake",
        description="Evidence-backed impact analysis for research papers.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    _build_resolve_parser(sub)
    _build_citing_parser(sub)
    _build_describe_parser(sub)
    _build_classify_parser(sub)
    _build_brief_parser(sub)
    _build_show_parser(sub)
    _build_config_parser(sub)
    _build_skill_parser(sub)

    return p


def _build_resolve_parser(sub) -> None:
    p = sub.add_parser("resolve", help="Resolve a seed ID to a canonical OpenAlex work.")
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID (W...), or paper title.")
    p.add_argument("-j", "--json", action="store_true", dest="as_json", help="Output raw JSON.")
    p.add_argument("--force", action="store_true", help="Re-resolve even if cached.")


def _build_citing_parser(sub) -> None:
    p = sub.add_parser("citing", help="Fetch and cache all citing works for a seed.")
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("--min-year", type=int, default=None, metavar="Y", help="Only fetch works from Y onwards.")
    p.add_argument("--limit", type=int, default=None, metavar="N", help="Truncate output to N works (does not limit fetch).")
    p.add_argument("-j", "--json", action="store_true", dest="as_json", help="Output JSON.")
    p.add_argument("--force", action="store_true", help="Re-fetch even if cached.")


def _build_describe_parser(sub) -> None:
    p = sub.add_parser("describe", help="LLM one-paragraph contribution description of the seed.")
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("--force", action="store_true", help="Re-generate even if cached.")


def _build_classify_parser(sub) -> None:
    p = sub.add_parser("classify", help="LLM-classify each citing work's relationship to the seed.")
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("--force", action="store_true", help="Re-classify even if cached.")
    p.add_argument("--delay", type=float, default=0.5, metavar="S", help="Seconds between LLM calls (default: 0.5).")
    p.add_argument("-j", "--json", action="store_true", dest="as_json", help="Output JSON summary.")


def _build_brief_parser(sub) -> None:
    p = sub.add_parser("brief", help="Run the full pipeline and produce impact.md + impact.json.")
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("--force", action="store_true", help="Force re-run of all stages.")
    p.add_argument("--min-year", type=int, default=None, metavar="Y", help="Only consider citing works from Y onwards.")
    p.add_argument("--delay", type=float, default=0.5, metavar="S", help="Seconds between LLM classify calls (default: 0.5).")


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


def _resolve_seed_to_work(seed_str: str, force: bool = False) -> dict:
    from ..seed import resolve_and_cache
    from ..errors import SeedNotFound
    try:
        return resolve_and_cache(seed_str, force=force)
    except SeedNotFound as exc:
        print(f"[wake] Error: {exc}", file=sys.stderr)
        sys.exit(1)


def run_resolve(args) -> None:
    work = _resolve_seed_to_work(args.seed, force=args.force)
    if args.as_json:
        print(json.dumps(work, indent=2, default=str))
    else:
        from ..seed import print_seed_table
        print_seed_table(work)


def run_citing(args) -> None:
    work = _resolve_seed_to_work(args.seed)
    from ..citing import fetch_and_cache, filter_works
    works = fetch_and_cache(
        work["openalex_id"],
        force=args.force,
        min_year=args.min_year,
    )
    works = filter_works(works, min_year=args.min_year, limit=args.limit)
    if args.as_json:
        print(json.dumps(works, indent=2, default=str))
    else:
        print(f"Citing works: {len(works):,}")
        for w in works[:20]:
            print(f"  [{w.get('year','?')}] {w.get('title','?')[:80]}  ({w.get('cited_by_count',0):,} cites)")
        if len(works) > 20:
            print(f"  ... and {len(works) - 20:,} more")


def run_describe(args) -> None:
    work = _resolve_seed_to_work(args.seed)
    from ..describe import describe_and_cache
    description = describe_and_cache(work, force=args.force)
    print(description)


def run_classify(args) -> None:
    work = _resolve_seed_to_work(args.seed)
    from ..citing import fetch_and_cache
    from ..classify import classify_all, save_classified
    citing = fetch_and_cache(work["openalex_id"])
    classified = classify_all(
        work,
        citing,
        force=args.force,
        inter_call_delay=args.delay,
    )
    path = save_classified(work["openalex_id"], classified)
    if args.as_json:
        print(json.dumps(classified, indent=2, default=str))
    else:
        print(f"[wake] Classified {len(classified):,} citing works → {path}", file=sys.stderr)
        from collections import Counter
        counts = Counter(w.get("relationship", "?") for w in classified)
        for rel, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {rel:<25} {cnt:>5}")


def run_brief(args) -> None:
    work = _resolve_seed_to_work(args.seed, force=args.force)
    oid = work["openalex_id"]

    from ..citing import fetch_and_cache
    from ..describe import describe_and_cache
    from ..classify import classify_all, save_classified
    from ..report import build_and_save

    print(f"[wake] Seed: {work.get('title')} ({oid})", file=sys.stderr)

    citing = fetch_and_cache(oid, force=args.force, min_year=args.min_year)
    description = describe_and_cache(work, force=args.force)
    work["description"] = description

    classified = classify_all(
        work,
        citing,
        force=args.force,
        inter_call_delay=args.delay,
    )
    save_classified(oid, classified)

    json_path, md_path = build_and_save(work, classified)
    print(f"\n[wake] Done. Impact brief: {md_path}", file=sys.stderr)


def run_show(args) -> None:
    from ..seed import resolve_and_cache, work_dir
    from ..errors import SeedNotFound

    what = args.show_what
    try:
        work = resolve_and_cache(args.seed)
    except SeedNotFound as exc:
        print(f"[wake] Error: {exc}", file=sys.stderr)
        sys.exit(1)

    oid = work["openalex_id"]
    wd = work_dir(oid)

    if what == "brief":
        md_path = wd / "impact.md"
        if not md_path.exists():
            print(f"[wake] No impact.md found at {md_path}. Run: wake brief {args.seed}", file=sys.stderr)
            sys.exit(1)
        print(md_path.read_text(encoding="utf-8"))

    elif what == "metrics":
        json_path = wd / "impact.json"
        if not json_path.exists():
            print(f"[wake] No impact.json found. Run: wake brief {args.seed}", file=sys.stderr)
            sys.exit(1)
        from ..io import read_json
        print(json.dumps(read_json(json_path), indent=2))

    elif what == "top":
        json_path = wd / "impact.json"
        if not json_path.exists():
            print(f"[wake] No impact.json found. Run: wake brief {args.seed}", file=sys.stderr)
            sys.exit(1)
        from ..io import read_json
        metrics = read_json(json_path)
        top = metrics.get("top_evidence", [])[:args.n]
        for i, ev in enumerate(top, 1):
            print(
                f"{i:>3}. [{ev.get('relationship','?'):<22}] "
                f"{ev.get('title','?')[:60]}  "
                f"({ev.get('cited_by_count',0):,} cites)"
            )


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
        elif args.command == "citing":
            run_citing(args)
        elif args.command == "describe":
            run_describe(args)
        elif args.command == "classify":
            run_classify(args)
        elif args.command == "brief":
            run_brief(args)
        elif args.command == "show":
            run_show(args)
        elif args.command == "config":
            run_config(args)
        elif args.command == "skill":
            run_skill(args)
    except KeyboardInterrupt:
        print("\n[wake] Interrupted.", file=sys.stderr)
        sys.exit(130)
