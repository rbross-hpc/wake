# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.classify — offline unit tests."""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from wake.classify import (
    RELATIONSHIPS,
    RELATIONSHIP_STRENGTH,
    _sidecar_path,
    _write_sidecar,
    _load_sidecar,
)
from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS


def test_relationships_ordered():
    assert RELATIONSHIPS[0] == "extends"
    assert RELATIONSHIPS[-1] == "background-mention"


def test_relationship_strength():
    assert RELATIONSHIP_STRENGTH["extends"] > RELATIONSHIP_STRENGTH["background-mention"]
    assert RELATIONSHIP_STRENGTH["builds-on"] > RELATIONSHIP_STRENGTH["uses-as-tool"]


def test_sidecar_write_and_load(tmp_path):
    seed_id = "W2156077349"
    citing_id = "W1000000001"
    payload = {
        "relationship": "builds-on",
        "confidence": 0.9,
        "justification": "Test justification.",
        "prompt_version": "classify-1",
        "model": "test-model",
    }
    _write_sidecar(seed_id, citing_id, payload, base=tmp_path)
    loaded = _load_sidecar(seed_id, citing_id, base=tmp_path)
    assert loaded == payload


def test_sidecar_missing_returns_none(tmp_path):
    assert _load_sidecar("W999", "W888", base=tmp_path) is None


def test_sidecar_path_structure(tmp_path):
    p = _sidecar_path("W2156077349", "W1000000001", base=tmp_path)
    assert p.name == "W1000000001.json"
    assert p.parent.name == ".classify"
    assert p.parent.parent.name == "W2156077349"
