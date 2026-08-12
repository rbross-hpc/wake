# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.classify — offline unit tests."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from wake.classify import (
    CANONICAL_RELATIONSHIPS,
    RELATIONSHIPS,
    _build_classify4_user_msg,
    _legacy_sidecar_dir,
    _legacy_sidecar_path,
    _load_sidecar,
    _sidecar_dir,
    _sidecar_path,
    _system_prompt,
    _title_only_shortcircuit_result,
    _validate_relationship_strength,
    _write_sidecar,
    classify_all,
    classify_one,
    relationship_strength,
    select_for_classification,
)
from wake.models import CLASSIFICATION_VERSION

from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS


def test_relationships_ordered():
    assert RELATIONSHIPS[0] == "extends"
    assert RELATIONSHIPS[-1] == "cites"


def test_relationship_strength_default():
    strength = relationship_strength()
    assert strength["applies-to-domain"] > strength["extends"]
    assert strength["uses-method-from"] > strength["cites"]
    assert strength["uses-data-from"] > strength["cites"]


def test_relationship_strength_reads_from_config(monkeypatch):
    """Reranking is a config-only operation: editing
    classify.relationship_strength changes the scores relationship_strength()
    returns with no re-classification."""
    custom = {
        "extends": 1, "uses-method-from": 2, "uses-data-from": 3, "benchmarks": 4,
        "applies-to-domain": 9, "related": 5, "cites": 1,
    }
    monkeypatch.setattr(
        "wake.classify.config.classify_cfg",
        lambda: {"relationship_strength": custom},
    )
    strength = relationship_strength()
    assert strength == custom
    assert strength["applies-to-domain"] > strength["extends"]


def test_relationship_strength_falls_back_to_default_when_config_omits_it(monkeypatch):
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-2"})
    strength = relationship_strength()
    assert strength["applies-to-domain"] == 7
    assert strength["cites"] == 1


def test_validate_relationship_strength_rejects_unknown_label():
    with pytest.raises(ValueError, match="unknown relationship label 'uses_method_from'"):
        _validate_relationship_strength({
            "extends": 5, "uses_method_from": 6, "uses-data-from": 6, "benchmarks": 3,
            "applies-to-domain": 7, "related": 2, "cites": 1,
        })


def test_validate_relationship_strength_unknown_label_suggests_closest_match():
    with pytest.raises(ValueError, match="did you mean 'uses-method-from'"):
        _validate_relationship_strength({
            "extends": 5, "uses_method_from": 6, "uses-data-from": 6, "benchmarks": 3,
            "applies-to-domain": 7, "related": 2, "cites": 1,
        })


def test_validate_relationship_strength_rejects_missing_label():
    incomplete = {k: v for k, v in zip(CANONICAL_RELATIONSHIPS, range(1, 8), strict=False) if k != "related"}
    with pytest.raises(ValueError, match="missing required label.*related"):
        _validate_relationship_strength(incomplete)


def test_validate_relationship_strength_rejects_zero():
    bad = {k: v for k, v in zip(CANONICAL_RELATIONSHIPS, range(1, 8), strict=False)}
    bad["extends"] = 0
    with pytest.raises(ValueError, match="must be a positive number"):
        _validate_relationship_strength(bad)


def test_validate_relationship_strength_rejects_negative():
    bad = {k: v for k, v in zip(CANONICAL_RELATIONSHIPS, range(1, 8), strict=False)}
    bad["extends"] = -3
    with pytest.raises(ValueError, match="must be a positive number"):
        _validate_relationship_strength(bad)


def test_validate_relationship_strength_rejects_non_numeric():
    bad = {k: v for k, v in zip(CANONICAL_RELATIONSHIPS, range(1, 8), strict=False)}
    bad["extends"] = "high"
    with pytest.raises(ValueError, match="must be a positive number"):
        _validate_relationship_strength(bad)


def test_validate_relationship_strength_rejects_bool():
    """bool is a subclass of int in Python -- must be explicitly excluded
    or `True`/`False` would silently pass as strength 1/0."""
    bad = {k: v for k, v in zip(CANONICAL_RELATIONSHIPS, range(1, 8), strict=False)}
    bad["extends"] = True
    with pytest.raises(ValueError, match="must be a positive number"):
        _validate_relationship_strength(bad)


def test_validate_relationship_strength_accepts_float():
    ok = {k: float(v) for k, v in zip(CANONICAL_RELATIONSHIPS, range(1, 8), strict=False)}
    result = _validate_relationship_strength(ok)
    assert result["extends"] == 1.0


def test_validate_relationship_strength_reports_every_error_at_once():
    bad = {
        "extends": 0, "uses_method_from": 6, "uses-data-from": 6, "benchmarks": 3,
        "applies-to-domain": 7,
    }
    with pytest.raises(ValueError) as exc_info:
        _validate_relationship_strength(bad)
    msg = str(exc_info.value)
    assert "unknown relationship label" in msg
    assert "missing required label" in msg
    assert "must be a positive number" in msg


def test_sidecar_write_and_load(tmp_path):
    seed_id = "W2156077349"
    citing_id = "W1000000001"
    payload = {
        "relationship": "uses-method-from",
        "confidence": 0.9,
        "justification": "Test justification.",
        "prompt_version": "classify-1",
        "model": "test-model",
    }
    _write_sidecar(seed_id, citing_id, payload, base=tmp_path)
    loaded = _load_sidecar(seed_id, citing_id, base=tmp_path)
    assert loaded is not None
    for key, value in payload.items():
        assert loaded[key] == value
    assert loaded["schema_version"] == CLASSIFICATION_VERSION


def test_sidecar_missing_returns_none(tmp_path):
    assert _load_sidecar("W999", "W888", base=tmp_path) is None


def test_sidecar_path_structure(tmp_path):
    p = _sidecar_path("W2156077349", "W1000000001", base=tmp_path)
    assert p.name == "W1000000001.json"
    assert p.parent.name == "classify"
    assert p.parent.parent.name == "W2156077349"


def test_load_sidecar_falls_back_to_legacy_dotfile_dir(tmp_path):
    """A packet built before the .classify/ -> classify/ rename should
    still be readable without any migration ceremony."""
    seed_id, citing_id = "W2156077349", "W1000000001"
    payload = {"relationship": "extends", "confidence": 0.9}
    legacy_path = _legacy_sidecar_path(seed_id, citing_id, base=tmp_path)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(json.dumps(payload), encoding="utf-8")

    assert not _sidecar_dir(seed_id, base=tmp_path).exists()
    loaded = _load_sidecar(seed_id, citing_id, base=tmp_path)
    assert loaded is not None
    for key, value in payload.items():
        assert loaded[key] == value
    assert loaded["schema_version"] == CLASSIFICATION_VERSION


def test_write_sidecar_migrates_legacy_dotfile_dir_in_place(tmp_path):
    """The first write after the rename should move the whole legacy
    .classify/ directory to classify/, not just add a new-named sibling
    alongside stale old-named files."""
    seed_id = "W2156077349"
    legacy_dir = _legacy_sidecar_dir(seed_id, base=tmp_path)
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "W_old.json").write_text(json.dumps({"relationship": "extends"}), encoding="utf-8")

    _write_sidecar(
        seed_id, "W_new",
        {
            "relationship": "uses-method-from", "confidence": 0.8, "justification": "x",
            "relationships": [{"label": "uses-method-from", "confidence": 0.8, "justification": "x"}],
        },
        base=tmp_path,
    )

    assert not legacy_dir.exists()
    new_dir = _sidecar_dir(seed_id, base=tmp_path)
    assert (new_dir / "W_old.json").exists()
    assert (new_dir / "W_new.json").exists()


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
    return {"relationship": "uses-method-from", "confidence": 0.8, "justification": "fake"}


def test_classify_one_always_marks_provisional(tmp_path, monkeypatch):
    """classify_one only ever sees title/abstract/venue -- it can never
    verify against the citing work's actual text, so every result it
    produces must be stamped 'provisional', with no way to opt out.
    Promotion to 'verified' only happens via wake evidence + wake override.

    Pinned to classify-2: this test is about classify_one's general
    provisional-tagging behavior, independent of which prompt version is
    active, and PARALLEL_NETCDF_WORK has no description (classify-4
    requires one -- see test_classify_4_* below for that behavior)."""
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-2"})
    with patch("wake.classify.chat_json", side_effect=_fake_chat_json):
        result = classify_one(PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS[0], record_cost=False)
    assert result["verification_status"] == "provisional"


def test_classify_one_tags_author_overlap_false_by_default(tmp_path, monkeypatch):
    """Fixture works have no author_ids -- must never be spuriously
    flagged as an overlap just because both sides lack the field."""
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-2"})
    with patch("wake.classify.chat_json", side_effect=_fake_chat_json):
        result = classify_one(PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS[0], record_cost=False)
    assert result["author_overlap"] is False


def test_classify_one_does_not_persist_a_strength_field(monkeypatch):
    """Strength is a derived ranking score, recomputed at bake time from
    the relationship label and the current config (see
    relationship_strength()/report.relationship_score()) -- classify_one's
    output must never carry a "strength" field, so a later config edit to
    classify.relationship_strength can rerank without stale, baked-in
    scores winning over the new config."""
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-2"})
    with patch("wake.classify.chat_json", side_effect=_fake_chat_json):
        result = classify_one(PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS[0], record_cost=False)
    assert "strength" not in result
    assert result["overlapping_authors"] == []


def test_classify_one_tags_author_overlap_true_when_shared_author_id(tmp_path, monkeypatch):
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-2"})
    seed = {**PARALLEL_NETCDF_WORK, "author_ids": ["A1", "A2"]}
    citing = {**SAMPLE_CITING_WORKS[0], "authors": ["Alice Smith"], "author_ids": ["A1"]}
    with patch("wake.classify.chat_json", side_effect=_fake_chat_json):
        result = classify_one(seed, citing, record_cost=False)
    assert result["author_overlap"] is True
    assert result["overlapping_authors"] == ["Alice Smith"]


def test_classify_all_results_are_provisional(tmp_path, monkeypatch):
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-2"})
    with patch("wake.classify.chat_json", side_effect=_fake_chat_json):
        result = classify_all(
            PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS,
            base=tmp_path, inter_call_delay=0, verbose=False,
        )
    classified = [w for w in result if w.get("relationship")]
    assert len(classified) == len(SAMPLE_CITING_WORKS)
    assert all(w["verification_status"] == "provisional" for w in classified)


def test_classify_all_dry_run_makes_no_calls(tmp_path, monkeypatch):
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-2"})
    with patch("wake.classify.chat_json") as mock_chat:
        result = classify_all(
            PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS,
            base=tmp_path, dry_run=True, inter_call_delay=0, verbose=False,
        )
        mock_chat.assert_not_called()
    assert all(not w.get("relationship") for w in result)


def test_classify_all_scoped_run_preserves_prior_classifications(tmp_path, monkeypatch):
    """Regression test: a scoped classify_all (--limit/--ids) must not drop
    classifications made in a previous, differently-scoped run."""
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-2"})
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


def test_classify_all_backfills_missing_abstract_before_classifying(tmp_path, monkeypatch):
    """Works with no abstract should be backfilled (if a DOI is present)
    before being sent to the LLM, so classify_one sees the recovered text."""
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-2"})
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
        return {"relationship": "uses-method-from", "confidence": 0.7, "justification": "x"}

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


_SEED_WITH_DESCRIPTION = {
    **PARALLEL_NETCDF_WORK,
    "description": "This paper introduces a high-performance I/O library.",
}


def test_system_prompt_classify_4_differs_from_classify_2():
    assert _system_prompt("classify-4") != _system_prompt("classify-2")
    assert "description of the seed paper's contribution" in _system_prompt("classify-4")


def test_classify_4_user_msg_includes_seed_description_and_topics():
    citing = {**SAMPLE_CITING_WORKS[0], "topics": ["High-performance computing"]}
    msg = _build_classify4_user_msg(_SEED_WITH_DESCRIPTION, citing)
    assert _SEED_WITH_DESCRIPTION["description"] in msg
    assert "High-performance computing" in msg


def test_classify_4_user_msg_never_includes_seed_abstract():
    """classify-4 uses the seed description exclusively -- the seed's
    own abstract must never appear in the user message (see PLAN.md's
    'classify-4 description-only + required')."""
    msg = _build_classify4_user_msg(_SEED_WITH_DESCRIPTION, SAMPLE_CITING_WORKS[0])
    assert PARALLEL_NETCDF_WORK["abstract"] not in msg


def test_classify_4_user_msg_raises_when_seed_description_missing():
    """Description is required, not conditionally appended -- calling
    this with no description should never silently degrade. The real
    enforcement point is classify_all's fail-fast check (see below); this
    is a belt-and-suspenders backstop in the message-builder itself."""
    seed = {**PARALLEL_NETCDF_WORK}
    seed.pop("description", None)
    with pytest.raises(AssertionError):
        _build_classify4_user_msg(seed, SAMPLE_CITING_WORKS[0])


def test_classify_4_user_msg_never_includes_author_overlap():
    """Regression guard for the explicit exclusion (see PLAN.md):
    author_overlap must never leak into the classify prompt."""
    msg = _build_classify4_user_msg(_SEED_WITH_DESCRIPTION, SAMPLE_CITING_WORKS[0])
    assert "author_overlap" not in msg.lower().replace(" ", "_")
    assert "overlap" not in msg.lower()


def test_classify_one_uses_classify_4_template_when_configured(monkeypatch):
    monkeypatch.setattr(
        "wake.classify.config.classify_cfg",
        lambda: {"prompt_version": "classify-4"},
    )
    seen = {}

    def _capturing_chat_json(system, user, **kwargs):
        seen["system"] = system
        seen["user"] = user
        return {"relationship": "uses-method-from", "confidence": 0.8, "justification": "x"}

    with patch("wake.classify.chat_json", side_effect=_capturing_chat_json):
        classify_one(_SEED_WITH_DESCRIPTION, SAMPLE_CITING_WORKS[0], record_cost=False)

    assert seen["system"] == _system_prompt("classify-4")
    assert _SEED_WITH_DESCRIPTION["description"] in seen["user"]


def test_title_only_shortcircuit_result_is_low_signal_cites():
    result = _title_only_shortcircuit_result(PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS[0])
    assert result["relationship"] == "cites"
    assert result["low_signal"] is True
    assert result["has_abstract"] is False
    assert result["verification_status"] == "provisional"


def test_title_only_shortcircuit_respects_configured_label(monkeypatch):
    monkeypatch.setattr(
        "wake.classify.config.classify_cfg",
        lambda: {"title_only_relationship": "related"},
    )
    result = _title_only_shortcircuit_result(PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS[0])
    assert result["relationship"] == "related"


def test_classify_all_short_circuits_title_only_works_with_no_llm_call(tmp_path, monkeypatch):
    """A work with no abstract after backfill should be classified
    deterministically, with chat_json never called."""
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-2"})
    no_abstract_work = {
        **SAMPLE_CITING_WORKS[0],
        "openalex_id": "W_title_only",
        "abstract": None,
        "doi": None,
    }
    with patch("wake.classify.chat_json") as mock_chat, \
         patch("wake.backfill.backfill_one", side_effect=lambda w, **kw: w):
        result = classify_all(
            PARALLEL_NETCDF_WORK, [no_abstract_work],
            base=tmp_path, inter_call_delay=0, verbose=False,
        )
    mock_chat.assert_not_called()
    classified = [w for w in result if w.get("relationship")]
    assert len(classified) == 1
    assert classified[0]["relationship"] == "cites"
    assert classified[0]["low_signal"] is True

    # Cached/resumable exactly like an LLM-produced sidecar.
    cached = _load_sidecar(PARALLEL_NETCDF_WORK["openalex_id"], "W_title_only", base=tmp_path)
    assert cached is not None
    assert cached["low_signal"] is True


def test_classify_all_short_circuit_disabled_falls_back_to_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "wake.classify.config.classify_cfg",
        lambda: {"prompt_version": "classify-2", "title_only_shortcircuit": False},
    )
    no_abstract_work = {
        **SAMPLE_CITING_WORKS[0],
        "openalex_id": "W_title_only_2",
        "abstract": None,
        "doi": None,
    }
    with patch("wake.classify.chat_json", side_effect=_fake_chat_json) as mock_chat, \
         patch("wake.backfill.backfill_one", side_effect=lambda w, **kw: w):
        result = classify_all(
            PARALLEL_NETCDF_WORK, [no_abstract_work],
            base=tmp_path, inter_call_delay=0, verbose=False,
        )
    mock_chat.assert_called_once()
    classified = [w for w in result if w.get("relationship")]
    assert len(classified) == 1
    assert not classified[0].get("low_signal")


def test_classify_all_does_not_short_circuit_works_with_an_abstract(tmp_path, monkeypatch):
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-2"})
    works_with_abstracts = [w for w in SAMPLE_CITING_WORKS if w.get("abstract")]
    assert works_with_abstracts, "fixture must contain at least one work with an abstract"
    with patch("wake.classify.chat_json", side_effect=_fake_chat_json) as mock_chat:
        result = classify_all(
            PARALLEL_NETCDF_WORK, works_with_abstracts,
            base=tmp_path, inter_call_delay=0, verbose=False,
        )
    assert mock_chat.called
    classified = [w for w in result if w.get("relationship")]
    assert all(not w.get("low_signal") for w in classified)


def test_classify_all_fails_fast_when_classify_4_seed_has_no_description(tmp_path, monkeypatch):
    """classify-4 requires a seed description -- classify_all must raise
    immediately, before any LLM call and before touching the resume
    cache, rather than failing once per citing work."""
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-4"})
    seed = {**PARALLEL_NETCDF_WORK}
    seed.pop("description", None)
    with patch("wake.classify.chat_json") as mock_chat:
        with pytest.raises(ValueError, match="classify-4 requires a seed description"):
            classify_all(
                seed, SAMPLE_CITING_WORKS,
                base=tmp_path, inter_call_delay=0, verbose=False,
            )
    mock_chat.assert_not_called()


def test_classify_all_proceeds_when_classify_4_seed_has_description(tmp_path, monkeypatch):
    monkeypatch.setattr("wake.classify.config.classify_cfg", lambda: {"prompt_version": "classify-4"})
    with patch("wake.classify.chat_json", side_effect=_fake_chat_json) as mock_chat:
        result = classify_all(
            _SEED_WITH_DESCRIPTION, SAMPLE_CITING_WORKS,
            base=tmp_path, inter_call_delay=0, verbose=False,
        )
    assert mock_chat.called
    classified = [w for w in result if w.get("relationship")]
    assert len(classified) == len(SAMPLE_CITING_WORKS)
