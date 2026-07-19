# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.io."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wake.io import atomic_write_json, atomic_write_text, read_json, sha256_text, now_iso


def test_atomic_write_text(tmp_path):
    p = tmp_path / "test.txt"
    atomic_write_text(p, "hello world")
    assert p.read_text() == "hello world"


def test_atomic_write_json(tmp_path):
    p = tmp_path / "test.json"
    data = {"key": "value", "num": 42}
    atomic_write_json(p, data)
    assert json.loads(p.read_text()) == data


def test_read_json(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps({"x": 1}), encoding="utf-8")
    assert read_json(p) == {"x": 1}


def test_sha256_text():
    h = sha256_text("hello")
    assert len(h) == 64
    assert sha256_text("hello") == h
    assert sha256_text("world") != h


def test_now_iso():
    ts = now_iso()
    assert "T" in ts
    assert ts.endswith("+00:00")


def test_atomic_write_creates_parent(tmp_path):
    p = tmp_path / "subdir" / "nested" / "file.json"
    atomic_write_json(p, {"nested": True})
    assert p.exists()
    assert read_json(p) == {"nested": True}
