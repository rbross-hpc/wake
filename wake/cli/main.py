# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake CLI — subcommand dispatcher.

Designed to be driven by an agent as much as by a human: every command
supports --json for machine-readable output, and the primitives are
intentionally thin (resolve / citing / sample / describe / classify /
bake / override / cost / status) so an agent can compose an
explore-first workflow instead of running one opaque pipeline command.
See wake/skills/impact-analysis/SKILL.md for the recommended workflow.

This module used to hold every command's parser-building and dispatch
logic directly (~2,000 lines, ~90 functions — see PLAN.md "Phase 3 --
Structural Hardening" / BACKLOG.md Theme L for the assessment that
flagged it as a "god module"). It's now reduced to exactly three
things: constructing the top-level parser (delegating each command
family's subparser construction to wake/cli/commands/<family>.py),
dispatching a parsed command to that family's `run_*` handler, and
top-level KeyboardInterrupt handling. `_work_dir_base`/
`_resolve_seed_to_work` (used by every command module) live in
main_helpers.py to avoid a circular import (every commands/*.py module
imports from main_helpers, not from this module).

`_work_dir_base` is re-exported here for backward compatibility -- it
was a public-ish helper other modules/tests imported directly from
`wake.cli.main` before this split.
"""
from __future__ import annotations

import argparse
import sys

from . import main_helpers
from .commands import (
    citing,
    classify,
    dedup,
    evidence,
    exclude,
    gaps,
    misc,
    narrative,
    pdf,
    posters,
    report,
    resolve,
    theme,
)

_work_dir_base = main_helpers._work_dir_base


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wake",
        description="Evidence-backed impact analysis for research papers.",
    )
    p.add_argument("--json", action="store_true", dest="json_out",
                   help="Emit a machine-readable JSON envelope on stdout instead of human text.")
    p.add_argument("--work-dir", default=None, metavar="DIR",
                   help="Root directory for wake-out/ cache (default: $WAKE_WORK_DIR or cwd).")
    p.add_argument("--verbose", action="store_true",
                   help="Keep progress banners on stderr even when --json is set.")

    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    resolve._build_resolve_parser(sub)
    resolve._build_status_parser(sub)
    citing._build_citing_parser(sub)
    citing._build_sample_parser(sub)
    citing._build_describe_parser(sub)
    classify._build_classify_parser(sub)
    gaps._build_gaps_parser(sub)
    gaps._build_missing_pdfs_parser(sub)
    dedup._build_dedup_parser(sub)
    posters._build_posters_parser(sub)
    pdf._build_fill_abstract_parser(sub)
    pdf._build_fetch_pdf_parser(sub)
    evidence._build_evidence_parser(sub)
    theme._build_theme_parser(sub)
    narrative._build_narrative_parser(sub)
    report._build_bake_parser(sub)
    report._build_rebuild_parser(sub)
    report._build_override_parser(sub)
    exclude._build_exclude_parser(sub)
    exclude._build_unexclude_parser(sub)
    exclude._build_unverify_parser(sub)
    misc._build_cost_parser(sub)
    misc._build_show_parser(sub)
    misc._build_seed_parser(sub)
    misc._build_config_parser(sub)
    misc._build_skill_parser(sub)

    return p


# Command name -> handler, one entry per subparser registered above.
# A plain dict dispatch rather than an if/elif chain -- this is the
# entire dispatch surface now that each handler's own logic lives in
# its command module, not inline here.
_DISPATCH = {
    "resolve": resolve.run_resolve,
    "status": resolve.run_status,
    "citing": citing.run_citing,
    "sample": citing.run_sample,
    "describe": citing.run_describe,
    "classify": classify.run_classify,
    "gaps": gaps.run_gaps,
    "missing-pdfs": gaps.run_missing_pdfs,
    "dedup": dedup.run_dedup,
    "posters": posters.run_posters,
    "fill-abstract": pdf.run_fill_abstract,
    "fetch-pdf": pdf.run_fetch_pdf,
    "evidence": evidence.run_evidence,
    "theme": theme.run_theme,
    "narrative": narrative.run_narrative,
    "bake": report.run_bake,
    "rebuild": report.run_rebuild,
    "override": report.run_override,
    "exclude": exclude.run_exclude,
    "unexclude": exclude.run_unexclude,
    "unverify": exclude.run_unverify,
    "cost": misc.run_cost,
    "show": misc.run_show,
    "seed": misc.run_seed,
    "config": misc.run_config,
    "skill": misc.run_skill,
}


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        handler = _DISPATCH.get(args.command)
        if handler is not None:
            handler(args)
    except KeyboardInterrupt:
        print("\n[wake] Interrupted.", file=sys.stderr)
        sys.exit(130)
