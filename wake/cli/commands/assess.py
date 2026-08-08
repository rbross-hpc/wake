# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake assess.

Part of the cli/commands/ split (see PLAN.md "Phase 3 -- Structural
Hardening" / BACKLOG.md Theme L): cli/main.py used to hold every
command's parser-building and dispatch logic in one ~2,000-line file.
Each module here owns one command family's argparse subparser
construction (`_build_*_parser`) and handler (`run_*`) functions;
cli/main.py itself is reduced to constructing the top-level parser,
registering each family's parser, and dispatching to its `run_*`.

`wake assess` is a pure read-only report -- same trust model as `wake
gaps`/`wake missing-pdfs`/`wake theme queue`: it never mutates
classify/evidence/theme state, it only joins what's already on disk
(classified.json, overrides.jsonl, dossier existence, theme sidecars,
the PDF fetch log) into one triage-ready document. See
`report.build_assessment()` for the actual join logic.
"""
from __future__ import annotations

from ..emit import emit
from ..main_helpers import _resolve_seed_to_work, _work_dir_base

_STATE_LABEL = {
    "cached": "PDF cached",
    "never-attempted": "PDF: never tried",
    "exhausted": "PDF: tried, all failed",
    "fetched-but-gone": "PDF: was fetched, file missing",
}


def _build_assess_parser(sub) -> None:
    p = sub.add_parser(
        "assess",
        help="Evidence-gap triage report: overall + per-theme coverage, and a "
             "ranked worklist of provisional works most worth fetching a PDF / "
             "running `wake evidence` for next. Read-only, run between "
             "`wake classify` and `wake fetch-pdf`.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("--top", type=int, default=15, metavar="N",
                   help="Max number of triage worklist entries to print in "
                        "human output (default: 15). The full ranked list is "
                        "always present under --json.")


def run_assess(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...report import build_assessment
    base = _work_dir_base(args)

    data = build_assessment(work, base)
    by_id = {w["openalex_id"]: w for w in data["works"]}

    def human(d):
        t = d["totals"]
        print(f"Seed: {d['seed']['title']} ({d['seed']['openalex_id']})")
        print(f"  Classified: {t['classified']:,}  "
              f"verified: {t['verified']:,}  proposed: {t['proposed']:,}  "
              f"provisional: {t['provisional']:,}")
        if t["error"] or t["excluded"] or t["duplicate"]:
            print(f"  (error: {t['error']:,}, excluded: {t['excluded']:,}, "
                  f"duplicate: {t['duplicate']:,})")
        print()

        if d["themes"]:
            print("Theme coverage:")
            for th in d["themes"]:
                c = th["counts"]
                total_members = c["verified"] + c["proposed"] + c["provisional"] + c["unclassified"]
                thin = " [thin on verified evidence]" if total_members and c["verified"] == 0 else ""
                print(f"  {th['slug']} ({th['theme_status']}): "
                      f"{c['verified']} verified, {c['proposed']} proposed, "
                      f"{c['provisional']} provisional{thin}")
            print()

        if not d["triage"]:
            print("No provisional works awaiting a dossier -- nothing to triage.")
            return

        top = d["triage"][: args.top]
        print(f"Triage worklist (top {len(top)} of {len(d['triage'])} provisional, by score):")
        print()
        for rank, cid in enumerate(top, start=1):
            w = by_id[cid]
            state = _STATE_LABEL.get(w["pdf"]["fetch_state"], w["pdf"]["fetch_state"])
            theme_tag = f"  themes: {', '.join(w['themes'])}" if w["themes"] else ""
            print(f"  {rank}. {cid}  score={w['score']}  "
                  f"({w['cited_by_count']:,} cites, {w.get('year','?')})  [{state}]{theme_tag}")
            print(f"     {w['title']}")
            print(f"     relationship: {w['relationship']}")
        print()
        print("Next steps:")
        print(f"  wake fetch-pdf {args.seed} <openalex-id>")
        print(f"  wake evidence {args.seed} <openalex-id>")

    emit("assess", data, as_json=args.json_out, human=human)
