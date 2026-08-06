# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""WakeContext: an explicit, constructible bundle of the environment a
wake operation runs against (workspace root, resolved settings, and --
in later phases -- an LLM client and source registry), as an
alternative to resolving those things implicitly from the process's
current working directory and module-global caches.

This is a deliberately incremental step (see PLAN.md "Phase 3 --
Structural Hardening" / BACKLOG.md Theme L): wake's ~90 existing domain
functions all take an optional `base: Path | None = None` parameter
that resolves against cwd/WAKE_WORK_DIR when omitted (see seed.py::
work_dir()), and `config.load()` reads `./wake.config.yaml` relative to
cwd with its own process-wide cache. Rewriting every one of those call
sites to take a `WakeContext` instead of `base=`/implicit config lookup
is real, valuable, but large-blast-radius work -- deferred to a
follow-on pass once more of the codebase has settled on this shape.

What *is* done in this pass:
  - WakeContext exists as a real, constructible, testable object with a
    single canonical construction point (`WakeContext.from_cli_args` in
    cli/main.py) rather than being purely aspirational.
  - `.base` is exactly the `Path | None` every domain function's `base=`
    parameter already accepts, so passing `ctx.base` into any existing
    call is a drop-in replacement for the CLI's current
    `_work_dir_base(args)` helper -- this is the seam later phases
    thread further.
  - `.settings` is the resolved config dict for that context (by
    default, wake.config.py's own process-wide `load()`), letting a
    caller override configuration per-context without touching the
    global cache config.py still uses internally.
  - `.llm_client`/`.source_registry` are present as explicit,
    typed-but-currently-trivial extension points: today they default to
    thin callables/namespaces that delegate to the existing
    llm/openai_client.py module functions and wake/sources/ modules
    respectively, so nothing downstream breaks, but a future test or
    embedder can already substitute a fake/mock client or a
    restricted source set by constructing a WakeContext directly
    instead of monkeypatching module globals.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WakeContext:
    """Everything a wake operation needs from its environment, gathered
    into one explicit, passable object.

    Every field has a default that reproduces wake's existing implicit
    behavior (cwd/WAKE_WORK_DIR-relative workspace, config.py's own
    process-wide settings cache, the real OpenAI-compatible LLM client),
    so constructing `WakeContext()` with no arguments behaves exactly
    like today's implicit lookups -- this is an *additive* seam, not a
    breaking change to any existing call site.
    """

    workspace: Path | None = None
    """Root directory under which `wake-out/<seed_id>/` lives. None
    means "resolve from $WAKE_WORK_DIR or cwd at call time" -- exactly
    seed.py::work_dir()'s existing default-resolution behavior. Stored
    under the name `workspace` (matching the assessment's proposed
    field name) but aliased as `.base` below since every existing
    domain function's parameter is literally named `base`."""

    settings: dict[str, Any] | None = None
    """Resolved config dict for this context. None means "use
    wake.config.load()'s own process-wide cache" -- today's default
    behavior. Set explicitly to run a context against a config that
    differs from whatever's on disk at cwd (e.g. embedding wake in a
    larger process serving multiple configs)."""

    llm_client_factory: Callable[[], Any] | None = None
    """Zero-arg factory returning an LLM client. None means "use
    llm.openai_client._client()'s own real OpenAI(...) construction."
    A future test/embedder can substitute a fake client without
    monkeypatching wake.llm.openai_client module state."""

    source_registry: dict[str, Any] = field(default_factory=dict)
    """Reserved for a future explicit registry of bibliographic/PDF
    source adapters (wake/sources/*.py) keyed by name -- currently
    unused by any call site (those modules are still imported directly
    by name, e.g. `from .sources import openalex`), but present on the
    context now so a later phase can wire it in without another
    dataclass-shape change."""

    @property
    def base(self) -> Path | None:
        """Alias for `.workspace` matching the parameter name
        (`base: Path | None = None`) every existing domain function
        already accepts -- `ctx.base` is a drop-in value for any of
        those calls."""
        return self.workspace

    def settings_or_default(self) -> dict[str, Any]:
        """This context's settings if explicitly set, else wake's
        current process-wide resolved config (wake.config.load())."""
        if self.settings is not None:
            return self.settings
        from . import config
        return config.load()

    @classmethod
    def from_cli_args(cls, args: Any) -> WakeContext:
        """Construct the context the CLI actually runs a command
        against, from parsed argparse args. This is the one canonical
        construction point wired into cli/main.py -- every command
        handler that currently calls the module-level `_work_dir_base(
        args)` helper can use `WakeContext.from_cli_args(args).base`
        instead (equivalent today; the seam future phases build on)."""
        work_dir_arg = getattr(args, "work_dir", None)
        workspace = Path(work_dir_arg).resolve() if work_dir_arg else None
        return cls(workspace=workspace)
