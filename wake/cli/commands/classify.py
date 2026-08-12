# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake classify.

Part of the cli/commands/ split (see PLAN.md "Phase 3 -- Structural
Hardening" / BACKLOG.md Theme L): cli/main.py used to hold every
command's parser-building and dispatch logic in one ~2,000-line file.
Each module here owns one command family's argparse subparser
construction (`_build_*_parser`) and handler (`run_*`) functions;
cli/main.py itself is reduced to constructing the top-level parser,
registering each family's parser, and dispatching to its `run_*`.
"""
from __future__ import annotations

import sys

from ..emit import emit, emit_error, is_quiet
from ..main_helpers import _resolve_seed_to_work, _work_dir_base


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


def run_classify(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...citing import fetch_and_cache
    from ...classify import classify_all
    base = _work_dir_base(args)
    quiet = is_quiet(args)

    citing = fetch_and_cache(work["openalex_id"], base=base, verbose=not quiet)
    ids = [s.strip() for s in args.ids.split(",")] if args.ids else None

    try:
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
    except ValueError as exc:
        # classify_all's fail-fast precondition check (e.g. classify-4
        # requires a seed description) -- one clean error, not a
        # traceback, matching every other command's error-handling
        # convention (see cli/commands/evidence.py).
        emit_error("classify", exc, as_json=args.json_out)
        sys.exit(1)

    if not args.dry_run:
        from ...classify import save_classified
        save_classified(work["openalex_id"], result, base=base)

    from collections import Counter
    classified_only = [w for w in result if w.get("relationship")]
    errored_only = [w for w in result if w.get("error") and not w.get("relationship")]
    # Counts each classified work under every facet it has (see
    # report.build_metrics' by_relationship, same convention) -- almost
    # always exactly one, occasionally two (see classify.py's MAX_FACETS).
    counts: Counter = Counter()
    for w in classified_only:
        facets = w.get("relationships") or [{"label": w.get("relationship", "?")}]
        for f in facets:
            counts[f.get("label", "?")] += 1

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
