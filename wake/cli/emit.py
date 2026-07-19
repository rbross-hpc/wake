# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Machine-first output helpers: JSON envelopes on stdout, progress on stderr.

Agents drive wake through --json output. Humans (via an agent) get formatted
text. Both share the same underlying data; this module is the seam between
them.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Callable

from .. import __version__


def emit(
    command: str,
    data: Any,
    *,
    as_json: bool = False,
    human: Callable[[Any], None] | None = None,
) -> None:
    """Emit a result either as a JSON envelope (stdout) or via *human*.

    When as_json is True, *human* is ignored — the envelope is the only
    output. When False, *human* is called with *data* to print
    human-readable output (or nothing happens if human is None).
    """
    if as_json:
        envelope = {
            "wake_version": __version__,
            "command": command,
            "ok": True,
            "data": data,
        }
        print(json.dumps(envelope, indent=2, default=str))
    elif human is not None:
        human(data)


def emit_error(command: str, exc: Exception, *, as_json: bool = False) -> None:
    """Emit an error either as a JSON envelope (stdout) or plain text (stderr)."""
    if as_json:
        envelope = {
            "wake_version": __version__,
            "command": command,
            "ok": False,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }
        print(json.dumps(envelope, indent=2))
    else:
        print(f"[wake] Error: {exc}", file=sys.stderr)


def is_quiet(args: Any) -> bool:
    """True if progress banners should be suppressed.

    Suppressed by default under --json unless --verbose is also given.
    """
    json_out = getattr(args, "json_out", False)
    verbose = getattr(args, "verbose", False)
    return bool(json_out) and not verbose


def progress(msg: str, *, quiet: bool = False) -> None:
    if not quiet:
        print(msg, file=sys.stderr)
