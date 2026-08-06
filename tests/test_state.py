# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.state."""
from __future__ import annotations

from wake.state import (
    is_stage_current,
    load_state,
    mark_stage_complete,
    save_state,
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


def test_load_state_malformed_returns_empty_and_warns(tmp_path, capsys):
    """Malformed state must be handled distinctly from missing state
    (see load_state's docstring): both return {} to the caller (the
    fail-safe "re-run everything" behavior is correct either way), but
    malformed state must not fail silently -- it should warn and
    quarantine the bad file rather than mimicking a brand-new seed."""
    p = state_path(tmp_path)
    p.write_text("{not valid json", encoding="utf-8")

    result = load_state(tmp_path)

    assert result == {}
    captured = capsys.readouterr()
    assert "malformed" in captured.err
    assert str(p) in captured.err


def test_load_state_malformed_quarantines_the_bad_file(tmp_path):
    p = state_path(tmp_path)
    p.write_text("{not valid json", encoding="utf-8")

    load_state(tmp_path)

    assert not p.exists()
    quarantined = list(tmp_path.glob(".state.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not valid json"


def test_load_state_malformed_does_not_repeat_the_warning_on_next_call(tmp_path, capsys):
    """Once quarantined, a second load_state call sees a plain missing
    file (the corrupt one has been renamed aside) -- no repeated warning
    spam on every subsequent stage check in the same process."""
    p = state_path(tmp_path)
    p.write_text("{not valid json", encoding="utf-8")

    load_state(tmp_path)
    capsys.readouterr()  # discard the first warning
    result = load_state(tmp_path)

    assert result == {}
    captured = capsys.readouterr()
    assert captured.err == ""
