# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.__version__ -- derived from installed package metadata
(pyproject.toml's [project].version), not a hardcoded literal. See
wake/__init__.py's docstring and BACKLOG.md's "Open items carried
forward" for the staleness bug this replaces (__version__ stuck at
"0.1.0" despite ~24 documented v0.4.x releases)."""
from __future__ import annotations

import importlib
from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import wake


def test_version_matches_installed_package_metadata():
    """The live __version__ should equal importlib.metadata's own
    answer for the installed 'wake' distribution -- i.e. it's genuinely
    read from there, not a separate hardcoded string that happens to
    agree today."""
    from importlib.metadata import version as pkg_version

    assert wake.__version__ == pkg_version("wake")


def test_version_is_not_the_stale_literal():
    """Regression guard for the specific bug: __version__ must not be
    the old hardcoded "0.1.0" (unless that's genuinely also the
    installed package version, which is not the case post-fix)."""
    assert wake.__version__ != "0.1.0"


def test_version_falls_back_when_package_not_found():
    """If wake isn't installed as a package at all (e.g. a bare source
    checkout with no `pip install -e .`), __version__ falls back to an
    obviously-placeholder string rather than raising or fabricating a
    real-looking version number."""
    with patch("importlib.metadata.version", side_effect=PackageNotFoundError("wake")):
        reloaded = importlib.reload(wake)
        assert reloaded.__version__ == "0.0.0+unknown"
    # Restore the real module state for any tests that run after this one.
    importlib.reload(wake)
