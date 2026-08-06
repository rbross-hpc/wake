# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake resolve / wake status.

Part of the cli/commands/ split (see PLAN.md "Phase 3 -- Structural
Hardening" / BACKLOG.md Theme L): cli/main.py used to hold every
command's parser-building and dispatch logic in one ~2,000-line file.
Each module here owns one command family's argparse subparser
construction (`_build_*_parser`) and handler (`run_*`) functions;
cli/main.py itself is reduced to constructing the top-level parser,
registering each family's parser, and dispatching to its `run_*`.
"""
from __future__ import annotations

from ..emit import emit
from ..main_helpers import _resolve_seed_to_work, _work_dir_base


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


def run_resolve(args) -> None:
    work = _resolve_seed_to_work(args.seed, args, force=args.force)

    def human(w):
        from ...seed import print_seed_table
        print_seed_table(w)

    emit("resolve", work, as_json=args.json_out, human=human)


def run_status(args) -> None:
    from ... import cost as cost_mod
    from ...citing import load_citing
    from ...classify import _model as classify_model
    from ...classify import load_classified
    from ...pdf_fetch import seed_pdf_path

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

    seed_pdf_info = work.get("seed_pdf") or {}
    seed_pdf_cached = seed_pdf_path(oid, base).exists()

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
            "seed_pdf": seed_pdf_cached,
            "seed_pdf_path": seed_pdf_info.get("path") if seed_pdf_cached else None,
        },
        "pending_classify": len(pending),
        "cost_so_far": cost_summary,
        "estimated_remaining_classify_cost": remaining_est,
    }

    def human(d):
        c = d["cached"]
        print(f"Seed: {d['seed']['title']} ({d['seed']['openalex_id']})")
        print(f"  Total citations (OpenAlex): {d['seed']['cited_by_count']:,}")
        if c["seed_pdf"]:
            print(f"  Seed PDF                  : {c['seed_pdf_path']}")
        else:
            print("  Seed PDF                  : (not available — run 'wake seed fetch-pdf --from-pdf PATH')")
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
