# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake exclude/unexclude/unverify.

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


def _build_exclude_parser(sub) -> None:
    p = sub.add_parser(
        "exclude",
        help="Record an explicit, permanent exclusion for one citing work -- judged not "
             "actually about the seed. wake persists this decision -- it never decides "
             "that a work should be excluded. Excluded works are refused by wake theme "
             "create and wake narrative reference validation, dropped from wake bake's "
             "reach metrics, and no longer surfaced by wake gaps/wake theme queue. "
             "Always run by the agent on the human's behalf, one work at a time.",
    )
    from ... import exclude as exclude_mod
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to exclude.")
    p.add_argument("--reason", required=True, help="Justification for the exclusion (required).")
    p.add_argument("--category", default="other", choices=exclude_mod.EXCLUSION_REASONS,
                   help="At-a-glance category for the exclusion (default: other).")


def _build_unexclude_parser(sub) -> None:
    p = sub.add_parser(
        "unexclude",
        help="Reverse a prior exclusion -- a separate, explicit action with its own "
             "required justification, never an implicit side effect of another command.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to un-exclude.")
    p.add_argument("--reason", required=True, help="Justification for reversing the exclusion (required).")


def _build_unverify_parser(sub) -> None:
    p = sub.add_parser(
        "unverify",
        help="Reverse a mistaken verification -- a separate, explicit action with its "
             "own justification, never an implicit side effect of another command. "
             "Removes the citing work's overrides.jsonl entry entirely and, if an "
             "evidence dossier exists, patches it back to pending-human-review.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", nargs="?", default=None,
                   help="OpenAlex ID of the citing work to un-verify. Omit when using "
                        "--since/--last for batch recovery.")
    batch = p.add_mutually_exclusive_group()
    batch.add_argument(
        "--since", metavar="TIMESTAMP",
        help="Batch recovery: un-verify every override recorded at or after this "
             "ISO-8601 timestamp, instead of one citing_id.",
    )
    batch.add_argument(
        "--last", type=int, metavar="N",
        help="Batch recovery: un-verify the N most-recently-recorded overrides, "
             "instead of one citing_id.",
    )
    p.add_argument("--reason", default="", help="Justification for reversing the verification.")


def run_exclude(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...exclude import exclude_work
    base = _work_dir_base(args)

    try:
        result = exclude_work(
            work["openalex_id"], args.citing_id,
            reason=args.reason, category=args.category, base=base,
        )
    except ValueError as exc:
        emit_error("exclude", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Excluded: {d['citing_id']} ({d['category']}) — {d['reason']}")
        print("  Now refused by wake theme create and wake narrative reference validation, "
              "dropped from wake bake's reach metrics, and no longer surfaced by "
              "wake gaps/wake theme queue.")

    emit("exclude", result, as_json=args.json_out, human=human)


def run_unexclude(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...exclude import unexclude_work
    base = _work_dir_base(args)

    try:
        result = unexclude_work(work["openalex_id"], args.citing_id, reason=args.reason, base=base)
    except ValueError as exc:
        emit_error("unexclude", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Un-excluded: {d['citing_id']} — {d['reason']}")
        print("  Fully usable again in theme/narrative/bake.")

    emit("unexclude", result, as_json=args.json_out, human=human)


def run_unverify(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...unverify import unverify_batch, unverify_work
    base = _work_dir_base(args)

    if args.since is not None or args.last is not None:
        if args.citing_id is not None:
            emit_error(
                "unverify", ValueError("Cannot give both citing_id and --since/--last."),
                as_json=args.json_out,
            )
            sys.exit(1)
        try:
            result = unverify_batch(
                work, since=args.since, last=args.last, reason=args.reason, base=base,
            )
        except ValueError as exc:
            emit_error("unverify", exc, as_json=args.json_out)
            sys.exit(1)

        def human_batch(d):
            if d["count"] == 0:
                print("No overrides matched -- nothing to un-verify.")
                return
            print(f"Un-verified {d['count']} citing work(s):")
            for r in d["reverted"]:
                print(f"  {r['citing_id']}")
            print(f"Run `wake rebuild {args.seed}` to render this in the wiki.")

        emit("unverify", result, as_json=args.json_out, human=human_batch)
        return

    if args.citing_id is None:
        emit_error(
            "unverify", ValueError("Must give either citing_id or --since/--last."),
            as_json=args.json_out,
        )
        sys.exit(1)

    try:
        result = unverify_work(work, args.citing_id, reason=args.reason, base=base)
    except ValueError as exc:
        emit_error("unverify", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Un-verified: {d['citing_id']}" + (f" — {d['reason']}" if d["reason"] else ""))
        print("  No longer counted as verified in theme/narrative/bake.")
        print(f"  Run `wake rebuild {args.seed}` to render this in the wiki.")

    emit("unverify", result, as_json=args.json_out, human=human)
