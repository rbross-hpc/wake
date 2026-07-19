# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.report overrides (human-in-the-loop refinement)."""
from __future__ import annotations

import pytest
from wake.report import add_override, load_overrides, apply_overrides, overrides_path
from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS


def test_overrides_path(tmp_path):
    p = overrides_path("W2156077349", base=tmp_path)
    assert p.name == ".overrides.jsonl"


def test_load_overrides_missing_returns_empty(tmp_path):
    assert load_overrides("W999", base=tmp_path) == {}


def test_add_and_load_override(tmp_path):
    seed_id = "W2156077349"
    citing_id = "W1000000001"
    entry = add_override(
        seed_id, citing_id,
        relationship="extends",
        justification="Human review: this is foundational.",
        base=tmp_path,
    )
    assert entry["relationship"] == "extends"
    assert entry["human_reviewed"] is True

    overrides = load_overrides(seed_id, base=tmp_path)
    assert citing_id in overrides
    assert overrides[citing_id]["relationship"] == "extends"


def test_override_last_write_wins(tmp_path):
    seed_id = "W2156077349"
    citing_id = "W1000000001"
    add_override(seed_id, citing_id, relationship="benchmarks", base=tmp_path)
    add_override(seed_id, citing_id, relationship="extends", base=tmp_path)

    overrides = load_overrides(seed_id, base=tmp_path)
    assert overrides[citing_id]["relationship"] == "extends"


def test_apply_overrides_no_overrides():
    classified = [{**w, "relationship": "uses-as-tool"} for w in SAMPLE_CITING_WORKS]
    result = apply_overrides(classified, {})
    assert result == classified


def test_apply_overrides_replaces_relationship():
    classified = [{**w, "relationship": "background-mention"} for w in SAMPLE_CITING_WORKS]
    target_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    overrides = {target_id: {"relationship": "extends", "human_reviewed": True}}

    result = apply_overrides(classified, overrides)
    target = next(w for w in result if w["openalex_id"] == target_id)
    assert target["relationship"] == "extends"
    assert target["human_reviewed"] is True

    others = [w for w in result if w["openalex_id"] != target_id]
    assert all(w["relationship"] == "background-mention" for w in others)
