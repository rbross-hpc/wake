# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake — evidence-backed impact analysis for research papers."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

# Single source of truth is pyproject.toml's [project].version -- see
# BACKLOG.md's "Open items carried forward" for the bug this replaces:
# __version__ used to be a hardcoded literal here that was never bumped
# past "0.1.0" despite ~24 documented v0.4.x releases in
# docs/build-log.md, so every packet's .state.json "tool_version" field
# (see state.py::mark_stage_complete) was a stale, misleading
# provenance/era signal. Reading it from installed package metadata
# instead means it can only ever drift if pyproject.toml itself isn't
# bumped -- a single point of truth instead of two files that can
# silently disagree.
#
# Falls back to "0.0.0+unknown" (never a fabricated real-looking version
# number) if wake isn't installed as a package at all -- e.g. running
# directly from a source checkout with wake/ on PYTHONPATH but no `pip
# install -e .` -- so the failure mode is an obviously-placeholder string
# rather than a silently wrong one.
try:
    __version__ = version("wake")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
