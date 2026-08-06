# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake citing / wake sample / wake describe.

Part of the cli/commands/ split (see PLAN.md "Phase 3 -- Structural
Hardening" / BACKLOG.md Theme L): cli/main.py used to hold every
command's parser-building and dispatch logic in one ~2,000-line file.
Each module here owns one command family's argparse subparser
construction (`_build_*_parser`) and handler (`run_*`) functions;
cli/main.py itself is reduced to constructing the top-level parser,
registering each family's parser, and dispatching to its `run_*`.
"""
from __future__ import annotations

from ..emit import emit, is_quiet
from ..main_helpers import _resolve_seed_to_work, _work_dir_base


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


def run_citing(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...citing import fetch_and_cache, filter_works
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
    from ...citing import fetch_and_cache, sample_works
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
    from ...describe import describe_and_cache
    quiet = is_quiet(args)
    description = describe_and_cache(work, base=_work_dir_base(args), force=args.force, verbose=not quiet)
    emit("describe", {"description": description}, as_json=args.json_out,
         human=lambda d: print(d["description"]))
