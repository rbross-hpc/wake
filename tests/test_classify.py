# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.classify — offline unit tests."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from wake.classify import (
    RELATIONSHIPS,
    RELATIONSHIP_STRENGTH,
    _sidecar_path,
    _write_sidecar,
    _load_sidecar,
    classify_all,
    select_for_classification,
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


def test_select_for_classification_limit():
    selected = select_for_classification(SAMPLE_CITING_WORKS, limit=2, sort="cited-by")
    assert len(selected) == 2
    assert selected[0]["cited_by_count"] >= selected[1]["cited_by_count"]


def test_select_for_classification_ids():
    target_id = SAMPLE_CITING_WORKS[1]["openalex_id"]
    selected = select_for_classification(SAMPLE_CITING_WORKS, ids=[target_id])
    assert len(selected) == 1
    assert selected[0]["openalex_id"] == target_id


def _fake_chat_json(system, user, model_role="classify", model=None, temperature=0, cost_sink=None):
    return {"relationship": "uses-as-tool", "confidence": 0.8, "justification": "fake"}


def test_classify_all_dry_run_makes_no_calls(tmp_path):
    with patch("wake.classify.chat_json") as mock_chat:
        result = classify_all(
            PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS,
            base=tmp_path, dry_run=True, inter_call_delay=0, verbose=False,
        )
        mock_chat.assert_not_called()
    assert all(not w.get("relationship") for w in result)


def test_classify_all_scoped_run_preserves_prior_classifications(tmp_path):
    """Regression test: a scoped classify_all (--limit/--ids) must not drop
    classifications made in a previous, differently-scoped run."""
    with patch("wake.classify.chat_json", side_effect=_fake_chat_json):
        # First run: classify only the first work.
        first_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
        result1 = classify_all(
            PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS,
            base=tmp_path, ids=[first_id], inter_call_delay=0, verbose=False,
        )
        classified1 = [w for w in result1 if w.get("relationship")]
        assert len(classified1) == 1
        assert classified1[0]["openalex_id"] == first_id

        # Second run: classify a *different* work only.
        second_id = SAMPLE_CITING_WORKS[1]["openalex_id"]
        result2 = classify_all(
            PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS,
            base=tmp_path, ids=[second_id], inter_call_delay=0, verbose=False,
        )
        classified2 = [w for w in result2 if w.get("relationship")]
        # Both the first (from the earlier run) and second work must show as classified.
        classified_ids = {w["openalex_id"] for w in classified2}
        assert first_id in classified_ids, "prior classification must be preserved"
        assert second_id in classified_ids
        assert len(classified2) == 2


def test_classify_all_backfills_missing_abstract_before_classifying(tmp_path):
    """Works with no abstract should be backfilled (if a DOI is present)
    before being sent to the LLM, so classify_one sees the recovered text."""
    no_abstract_work = {
        **SAMPLE_CITING_WORKS[0],
        "openalex_id": "W1000000099",
        "abstract": None,
        "doi": "10.1234/no-abstract-fixture",
    }
    assert no_abstract_work["abstract"] is None
    assert no_abstract_work["doi"]

    seen_abstracts = []

    def _capturing_chat_json(system, user, **kwargs):
        seen_abstracts.append(user)
        return {"relationship": "uses-as-tool", "confidence": 0.7, "justification": "x"}

    with patch("wake.classify.chat_json", side_effect=_capturing_chat_json), \
         patch("wake.backfill.backfill_one", side_effect=lambda w, **kw: {**w, "abstract": "Recovered abstract text.", "abstract_source": "osti"}) as mock_backfill:
        result = classify_all(
            PARALLEL_NETCDF_WORK, [no_abstract_work],
            base=tmp_path, inter_call_delay=0, verbose=False,
        )

    mock_backfill.assert_called_once()
    assert any("Recovered abstract text." in u for u in seen_abstracts)
    classified = [w for w in result if w.get("relationship")]
    assert len(classified) == 1
    assert classified[0]["has_abstract"] is True
