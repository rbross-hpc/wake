# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Shared helpers used across every wake/cli/commands/*.py module.

Split out of cli/main.py (see PLAN.md "Phase 3 -- Structural Hardening"
/ BACKLOG.md Theme L) so command modules don't need to import from
main.py itself (which would create a circular import, since main.py
imports every command module to register its parser/dispatch).
"""
from __future__ import annotations

import sys
from pathlib import Path

from .emit import emit_error


def _work_dir_base(args) -> Path | None:
    """The workspace root every command resolves wake-out/<seed>/
    against. Delegates to WakeContext.from_cli_args (see context.py) --
    this helper is kept as the CLI's actual call-site shim (every
    run_*() handler calls `_work_dir_base(args)`, not WakeContext
    directly) so the ~40 existing call sites don't all need touching in
    this pass; the context construction itself is centralized here."""
    from ..context import WakeContext
    return WakeContext.from_cli_args(args).base


def _resolve_seed_to_work(seed_str: str, args, force: bool = False) -> dict:
    from ..errors import SeedNotFound
    from ..seed import resolve_and_cache
    try:
        return resolve_and_cache(seed_str, base=_work_dir_base(args), force=force)
    except SeedNotFound as exc:
        emit_error("resolve", exc, as_json=args.json_out)
        sys.exit(1)


def _find_citing_work(seed_id: str, citing_id: str, base) -> dict | None:
    """Look up one citing work by ID from citing.json. Shared by
    commands/pdf.py (run_fetch_pdf) and commands/evidence.py
    (_find_classified_work's fallback when the work isn't classified
    yet)."""
    from ..citing import load_citing
    works = load_citing(seed_id, base) or []
    for w in works:
        if w.get("openalex_id") == citing_id:
            return w
    return None
