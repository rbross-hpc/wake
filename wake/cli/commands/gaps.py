# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake gaps / wake missing-pdfs.

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


def _build_missing_pdfs_parser(sub) -> None:
    p = sub.add_parser(
        "missing-pdfs",
        help="Read-only report of classified citing works with no cached PDF. "
             "Shows fetch state (never-attempted, exhausted, fetched-but-gone) "
             "and which sources were tried, so you know where to focus manual "
             "PDF hunting. Complements wake gaps (which is about abstracts).",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("--min-cited-by", type=int, default=None, metavar="N",
                   help="Only surface works whose own cited_by_count is >= N.")
    p.add_argument("-n", "--limit", type=int, default=None, metavar="N",
                   help="Max number of works to show.")


def run_gaps(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...citing import fetch_and_cache
    from ...gaps import find_gaps
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


def run_missing_pdfs(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...missing_pdfs import list_missing_pdfs
    base = _work_dir_base(args)

    results = list_missing_pdfs(
        work["openalex_id"],
        base=base,
        min_cited_by_count=args.min_cited_by,
        limit=args.limit,
    )

    _STATE_LABEL = {
        "never-attempted": "never tried",
        "exhausted": "tried, all failed",
        "fetched-but-gone": "was fetched, file missing",
    }

    def human(d):
        items = d["missing"]
        if not items:
            print("No classified works are missing a PDF "
                  "(all have a cached PDF, dossier, or are excluded).")
            return
        print(f"{d['count']} classified work(s) with no cached PDF:")
        print()
        for r in items:
            state = _STATE_LABEL.get(r["fetch_state"], r["fetch_state"])
            tried = ", ".join(r["sources_tried"]) if r["sources_tried"] else ""
            print(f"  {r['citing_id']}  ({r.get('cited_by_count', 0):,} cites, {r.get('year','?')})  [{state}]")
            print(f"    {r['title']}")
            if tried:
                print(f"    Sources tried: {tried}")
            if r.get("doi"):
                print(f"    DOI: https://doi.org/{r['doi']}")
            if r.get("last_attempted"):
                print(f"    Last attempted: {r['last_attempted']}")
            print()
        print("Next steps:")
        print(f"  wake fetch-pdf {args.seed} <citing-id>          # try automatic acquisition again")
        print(f"  wake evidence {args.seed} <citing-id> --from-pdf <path>  # supply a PDF you found manually")

    emit("missing-pdfs", {"count": len(results), "missing": results},
         as_json=args.json_out, human=human)
