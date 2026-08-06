# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake dedup candidates/confirm/reject.

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


def run_dedup(args) -> None:
    if args.dedup_action == "candidates":
        run_dedup_candidates(args)
    elif args.dedup_action == "confirm":
        run_dedup_confirm(args)
    elif args.dedup_action == "reject":
        run_dedup_reject(args)


def run_dedup_candidates(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...dedup import dedup_candidates
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
    from ...dedup import confirm_duplicate
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
    from ...dedup import reject_candidate
    base = _work_dir_base(args)

    try:
        result = reject_candidate(work["openalex_id"], args.id_a, args.id_b, reason=args.reason, base=base)
    except ValueError as exc:
        emit_error("dedup", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Recorded: {d['id_a']} and {d['id_b']} are not duplicates -- both remain fully usable.")

    emit("dedup", result, as_json=args.json_out, human=human)
