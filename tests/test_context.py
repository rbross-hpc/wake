# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.context.WakeContext -- see the module docstring for
why this is an additive, incrementally-adopted seam rather than a full
rewrite of every domain function's implicit base=/config lookup."""
from __future__ import annotations

import argparse

from wake.context import WakeContext


def test_default_context_has_no_explicit_workspace():
    ctx = WakeContext()
    assert ctx.workspace is None
    assert ctx.base is None


def test_base_is_an_alias_for_workspace(tmp_path):
    ctx = WakeContext(workspace=tmp_path)
    assert ctx.base == tmp_path
    assert ctx.base is ctx.workspace


def test_settings_or_default_uses_explicit_settings_when_given():
    ctx = WakeContext(settings={"models": {"classify": "fake-model"}})
    assert ctx.settings_or_default() == {"models": {"classify": "fake-model"}}


def test_settings_or_default_falls_back_to_process_wide_config():
    from wake import config
    ctx = WakeContext()
    assert ctx.settings_or_default() == config.load()


def test_from_cli_args_resolves_explicit_work_dir(tmp_path):
    args = argparse.Namespace(work_dir=str(tmp_path))
    ctx = WakeContext.from_cli_args(args)
    assert ctx.base == tmp_path.resolve()


def test_from_cli_args_none_when_work_dir_not_set():
    args = argparse.Namespace(work_dir=None)
    ctx = WakeContext.from_cli_args(args)
    assert ctx.base is None


def test_from_cli_args_none_when_work_dir_attr_missing():
    """Some commands' argparse namespaces may not define --work-dir at
    all (global flags are added to the top-level parser, but a
    defensive getattr matches the existing _work_dir_base behavior)."""
    args = argparse.Namespace()
    ctx = WakeContext.from_cli_args(args)
    assert ctx.base is None


def test_cli_work_dir_base_helper_delegates_to_context(tmp_path):
    from wake.cli.main import _work_dir_base
    args = argparse.Namespace(work_dir=str(tmp_path))
    assert _work_dir_base(args) == tmp_path.resolve()


def test_context_base_is_drop_in_for_existing_base_param(tmp_path):
    """ctx.base must be usable exactly where any existing domain
    function's base: Path | None = None parameter is used today."""
    from wake.seed import work_dir
    ctx = WakeContext(workspace=tmp_path)
    assert work_dir("W123", ctx.base) == tmp_path / "wake-out" / "W123"
