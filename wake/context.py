# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""WakeContext: an explicit, constructible bundle of the environment a
wake operation runs against (workspace root, resolved settings, and an
LLM client factory), as an alternative to resolving those things
implicitly from the process's current working directory and module-global
caches.

Fields:
  - `.workspace` / `.base`: the `Path | None` every domain function's
    `base=` parameter already accepts; `ctx.base` is a drop-in for any
    such call.
  - `.settings`: resolved config dict for this context; when None,
    `wake.config.load()` is used.
  - `.llm_client_factory`: zero-arg factory returning an LLM client;
    when None, the real OpenAI client is used.  Allows tests/embedders
    to substitute a fake client without monkeypatching module globals.

Threading `WakeContext` through all ~90 existing `base:`-taking domain
functions is real, valuable, deferred work -- see BACKLOG.md Theme L.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
