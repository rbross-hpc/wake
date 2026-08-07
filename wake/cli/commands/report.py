# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake bake / wake rebuild / wake override.

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


def _build_bake_parser(sub) -> None:
    p = sub.add_parser(
        "bake",
        help="Assemble impact.md + impact.json from whatever has been classified so far. "
             "Works on partial data (marks coverage) or a fully classified set.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")


def _build_rebuild_parser(sub) -> None:
    p = sub.add_parser(
        "rebuild",
        help="Render every derived Markdown/index file (dossiers, evidence/index.md, "
             "theme docs + their index, narrative outline/sections/stitched narrative.md, "
             "impact.md, README.md/AGENTS.md) from whatever JSON is currently on disk for "
             "this seed. This is the ONLY step that renders Markdown -- wake evidence/"
             "override/unverify/theme create/confirm/narrative outline/section create/"
             "confirm write JSON only and expect a `wake rebuild` afterward; run it after "
             "any such command, not just for recovery (e.g. after hand-editing a JSON "
             "sidecar). No LLM/network call. Skips any artifact type that has no JSON "
             "backing yet for this seed.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")


def _build_override_parser(sub) -> None:
    p = sub.add_parser(
        "override",
        help="Record a human-reviewed relationship override for one citing work. wake "
             "persists this judgment -- it never decides the relationship itself, the "
             "human already has. Wins over the LLM classification in the next bake. "
             "Always run by the agent on the human's behalf -- never ask the human to "
             "run this command themselves (see SKILL.md).",
    )
    from ...classify import RELATIONSHIPS
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to override.")
    p.add_argument("--relationship", required=True,
                   choices=RELATIONSHIPS,
                   help="The corrected relationship class.")
    p.add_argument("--justification", default="", help="One-line justification for the override.")
    p.add_argument("--verification-source", default="human-judgment",
                   choices=["human-judgment", "evidence-dossier"],
                   help="How the human arrived at this judgment (default: human-judgment). "
                        "Use 'evidence-dossier' when the human accepted a `wake evidence` "
                        "full-text finding.")


def run_bake(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...citing import load_citing
    from ...classify import load_classified
    from ...report import bake_and_save
    base = _work_dir_base(args)
    quiet = is_quiet(args)

    citing = load_citing(work["openalex_id"], base)
    if citing is None:
        emit_error("bake", RuntimeError(
            "No citing works cached. Run `wake citing` first."
        ), as_json=args.json_out)
        sys.exit(1)

    classified = load_classified(work["openalex_id"], base)
    works = classified if classified is not None else citing

    json_path, md_path = bake_and_save(work, works, base=base, verbose=not quiet)

    data = {"impact_json": str(json_path), "impact_md": str(md_path)}
    emit("bake", data, as_json=args.json_out,
         human=lambda d: print(f"Report written:\n  {d['impact_md']}\n  {d['impact_json']}"))


def run_rebuild(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...build import rebuild_seed
    base = _work_dir_base(args)
    quiet = is_quiet(args)

    result = rebuild_seed(work, base=base, verbose=not quiet)

    def _human(d):
        print("Rebuild complete:")
        for step in d["steps"]:
            name = step["step"]
            rebuilt = step["rebuilt"]
            if isinstance(rebuilt, list):
                label = f"{len(rebuilt)} rebuilt" if rebuilt else "skipped (nothing to rebuild)"
            else:
                label = "rebuilt" if rebuilt else "skipped (nothing to rebuild)"
            print(f"  {name}: {label}")

    emit("rebuild", result, as_json=args.json_out, human=_human)


def run_override(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...report import add_override
    base = _work_dir_base(args)
    entry = add_override(
        work["openalex_id"], args.citing_id,
        relationship=args.relationship,
        justification=args.justification,
        verification_source=args.verification_source,
        seed_title=work.get("title"),
        base=base,
    )
    def _human(d):
        print(f"Override recorded: {args.citing_id} -> {d['relationship']}")
        print(f"Run `wake rebuild {args.seed}` to render this in the wiki.")

    emit("override", entry, as_json=args.json_out, human=_human)
