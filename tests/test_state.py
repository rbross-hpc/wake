# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.state."""
from __future__ import annotations

import pytest
from wake.state import (
    load_state,
    save_state,
    is_stage_current,
    mark_stage_complete,
    state_path,
)


def test_load_state_missing(tmp_path):
    assert load_state(tmp_path) == {}


def test_save_and_load(tmp_path):
    save_state(tmp_path, {"foo": "bar"})
    assert load_state(tmp_path) == {"foo": "bar"}


def test_mark_and_check_current(tmp_path):
    mark_stage_complete(
        tmp_path, "citing",
        seed_id="W123",
        prompt_version="v1",
        model="model-x",
    )
    assert is_stage_current(
        tmp_path, "citing",
        seed_id="W123",
        prompt_version="v1",
        model="model-x",
    )


def test_stage_not_current_wrong_model(tmp_path):
    mark_stage_complete(tmp_path, "citing", seed_id="W123", model="model-x")
    assert not is_stage_current(tmp_path, "citing", seed_id="W123", model="model-y")


def test_stage_not_current_wrong_seed(tmp_path):
    mark_stage_complete(tmp_path, "citing", seed_id="W123")
    assert not is_stage_current(tmp_path, "citing", seed_id="W999")


def test_extra_key_matching(tmp_path):
    mark_stage_complete(tmp_path, "citing", seed_id="W123", extra={"count": 408})
    assert is_stage_current(tmp_path, "citing", seed_id="W123", extra_key={"count": 408})
    assert not is_stage_current(tmp_path, "citing", seed_id="W123", extra_key={"count": 999})


def test_state_path(tmp_path):
    p = state_path(tmp_path)
    assert p.name == ".state.json"
    assert p.parent == tmp_path
