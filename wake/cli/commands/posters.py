# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake posters candidates/keep.

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

from ..emit import emit, emit_error
from ..main_helpers import _resolve_seed_to_work, _work_dir_base


def _build_posters_parser(sub) -> None:
    p = sub.add_parser(
        "posters",
        help="Surface likely posters/conference-abstracts (type conference-abstract, or "
             "a 'Poster:'/'Abstract:' title prefix) for human sign-off. Never auto-"
             "excludes -- one candidate at a time, same as every other human-in-the-loop "
             "command in wake.",
    )
    ssub = p.add_subparsers(dest="posters_action", required=True, metavar="ACTION")

    candidates = ssub.add_parser(
        "candidates",
        help="Scan classified citing works for likely poster/conference-abstract stubs. "
             "Read-only, deterministic, no LLM call. Already-excluded and already-kept "
             "works are excluded from the results.",
    )
    candidates.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")

    keep = ssub.add_parser(
        "keep",
        help="Record a human decision that a flagged candidate should be kept as-is, "
             "not excluded -- so it isn't resurfaced by a later scan. Always run by the "
             "agent on the human's behalf.",
    )
    keep.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    keep.add_argument("citing_id", help="OpenAlex ID of the candidate to keep.")
    keep.add_argument("--reason", required=True, help="Justification for keeping this candidate (required).")


def run_posters(args) -> None:
    if args.posters_action == "candidates":
        run_posters_candidates(args)
    elif args.posters_action == "keep":
        run_posters_keep(args)


def run_posters_candidates(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...posters import poster_candidates
    base = _work_dir_base(args)

    candidates = poster_candidates(work["openalex_id"], base=base)

    def human(cands):
        if not cands:
            print("No likely poster/conference-abstract candidates found.")
            return
        print(f"{len(cands)} likely poster/conference-abstract candidate(s):")
        print()
        for c in cands:
            print(f"  {c['citing_id']}  ({c.get('year','?')}, {c.get('type','?')})  {c['title']}")
            print(f"    Matched: {c['matched_reason']}")
            print()
        print("Present each candidate to the human, then run on their behalf:")
        print(f"  wake exclude {args.seed} <citing-id> --reason \"...\" --category poster-or-abstract")
        print(f"  wake posters keep {args.seed} <citing-id> --reason \"...\"")

    emit("posters", {"count": len(candidates), "candidates": candidates}, as_json=args.json_out,
         human=lambda d: human(d["candidates"]))


def run_posters_keep(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...posters import keep_candidate
    base = _work_dir_base(args)

    try:
        result = keep_candidate(work["openalex_id"], args.citing_id, reason=args.reason, base=base)
    except ValueError as exc:
        emit_error("posters", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Recorded: {d['citing_id']} kept as-is -- not resurfaced by a later scan.")

    emit("posters", result, as_json=args.json_out, human=human)
