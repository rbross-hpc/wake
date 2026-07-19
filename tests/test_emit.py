# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.cli.emit — JSON envelope + progress routing."""
from __future__ import annotations

import json
import pytest
from wake.cli.emit import emit, emit_error, is_quiet, progress


def test_emit_json_envelope(capsys):
    emit("resolve", {"title": "Test Paper"}, as_json=True)
    out = capsys.readouterr().out
    envelope = json.loads(out)
    assert envelope["command"] == "resolve"
    assert envelope["ok"] is True
    assert envelope["data"] == {"title": "Test Paper"}
    assert "wake_version" in envelope


def test_emit_human_path(capsys):
    called = []
    emit("resolve", {"title": "Test Paper"}, as_json=False, human=lambda d: called.append(d))
    assert called == [{"title": "Test Paper"}]
    out = capsys.readouterr().out
    assert out == ""  # human callback controls its own output; nothing auto-printed


def test_emit_json_ignores_human_callback(capsys):
    called = []
    emit("resolve", {"x": 1}, as_json=True, human=lambda d: called.append(d))
    assert called == []  # human callback must not run under --json


def test_emit_error_json(capsys):
    emit_error("resolve", ValueError("not found"), as_json=True)
    out = capsys.readouterr().out
    envelope = json.loads(out)
    assert envelope["ok"] is False
    assert envelope["error"]["type"] == "ValueError"
    assert envelope["error"]["message"] == "not found"


def test_emit_error_text(capsys):
    emit_error("resolve", ValueError("not found"), as_json=False)
    err = capsys.readouterr().err
    assert "not found" in err


class _Args:
    def __init__(self, json_out=False, verbose=False):
        self.json_out = json_out
        self.verbose = verbose


def test_is_quiet_default():
    assert is_quiet(_Args(json_out=False)) is False


def test_is_quiet_under_json():
    assert is_quiet(_Args(json_out=True)) is True


def test_is_quiet_json_with_verbose():
    assert is_quiet(_Args(json_out=True, verbose=True)) is False


def test_progress_respects_quiet(capsys):
    progress("hello", quiet=True)
    assert capsys.readouterr().err == ""
    progress("hello", quiet=False)
    assert "hello" in capsys.readouterr().err
