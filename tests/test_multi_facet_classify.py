# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.classify's multi-facet relationship parsing (see
classify.py's module docstring for the design rationale: a citing paper's
relationship to the seed is sometimes genuinely more than one story --
e.g. both "uses-method-from" and "applies-to-domain" -- and forcing a single
label loses that signal).

Covers: classify-3 multi-facet response parsing, classify-2 legacy
single-label parsing (both must produce the same "relationships" +
legacy-scalar shape), the MAX_FACETS/MIN_FACET_CONFIDENCE backstops, the
"unknown label" drop behavior, and _normalize_relationships' read-compat
synthesis for pre-multi-facet sidecars.
"""
from __future__ import annotations

from unittest.mock import patch

from wake.classify import (
    MAX_FACETS,
    MIN_FACET_CONFIDENCE,
    _normalize_relationships,
    _parse_relationships_response,
    _system_prompt,
    classify_one,
)

from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS

# --- _system_prompt -----------------------------------------------------

def test_system_prompt_classify_2_is_single_label():
    prompt = _system_prompt("classify-2")
    assert "choose exactly one" in prompt.lower()
    assert '"relationship"' in prompt


def test_system_prompt_classify_3_is_multi_facet():
    prompt = _system_prompt("classify-3")
    assert '"relationships"' in prompt
    assert "confidence >= 0.5" in prompt or ">= 0.5" in prompt


def test_system_prompt_unknown_version_falls_back_to_classify_2():
    assert _system_prompt("classify-99") == _system_prompt("classify-2")


# --- _parse_relationships_response ---------------------------------------

def test_parse_multi_facet_response_two_facets():
    result = {
        "relationships": [
            {"label": "uses-method-from", "confidence": 0.95, "justification": "Uses PnetCDF as-is."},
            {"label": "applies-to-domain", "confidence": 0.8, "justification": "Applies it to flood modeling."},
        ]
    }
    facets = _parse_relationships_response(result)
    assert [f["label"] for f in facets] == ["uses-method-from", "applies-to-domain"]
    assert facets[0]["confidence"] == 0.95


def test_parse_legacy_single_label_response():
    """A classify-2-shaped response (no "relationships" key) still parses
    into a one-element facets list -- classify_one must work identically
    whether the configured prompt_version is classify-2 or classify-3."""
    result = {"relationship": "extends", "confidence": 0.9, "justification": "Direct extension."}
    facets = _parse_relationships_response(result)
    assert len(facets) == 1
    assert facets[0] == {"label": "extends", "confidence": 0.9, "justification": "Direct extension."}


def test_parse_response_sorts_by_confidence_descending():
    result = {
        "relationships": [
            {"label": "benchmarks", "confidence": 0.6, "justification": "x"},
            {"label": "extends", "confidence": 0.9, "justification": "y"},
        ]
    }
    facets = _parse_relationships_response(result)
    assert [f["label"] for f in facets] == ["extends", "benchmarks"]


def test_parse_response_drops_facets_below_min_confidence():
    result = {
        "relationships": [
            {"label": "extends", "confidence": 0.9, "justification": "x"},
            {"label": "uses-method-from", "confidence": MIN_FACET_CONFIDENCE - 0.01, "justification": "weak"},
        ]
    }
    facets = _parse_relationships_response(result)
    assert [f["label"] for f in facets] == ["extends"]


def test_parse_response_keeps_facet_at_exactly_min_confidence():
    result = {"relationships": [{"label": "extends", "confidence": MIN_FACET_CONFIDENCE, "justification": "x"}]}
    facets = _parse_relationships_response(result)
    assert len(facets) == 1


def test_parse_response_drops_unknown_labels():
    result = {
        "relationships": [
            {"label": "extends", "confidence": 0.9, "justification": "x"},
            {"label": "made-up-label", "confidence": 0.9, "justification": "y"},
        ]
    }
    facets = _parse_relationships_response(result)
    assert [f["label"] for f in facets] == ["extends"]


def test_parse_response_caps_at_max_facets():
    """Belt-and-suspenders backstop: even if the LLM ignores the prompt's
    'very rarely three' guidance and returns more, code truncates to the
    top MAX_FACETS by confidence."""
    result = {
        "relationships": [
            {"label": "extends", "confidence": 0.95, "justification": "a"},
            {"label": "uses-method-from", "confidence": 0.9, "justification": "b"},
            {"label": "uses-method-from", "confidence": 0.85, "justification": "c"},
            {"label": "benchmarks", "confidence": 0.8, "justification": "d"},
        ]
    }
    facets = _parse_relationships_response(result)
    assert len(facets) == MAX_FACETS
    assert [f["label"] for f in facets] == ["extends", "uses-method-from", "uses-method-from"]


def test_parse_response_falls_back_to_background_mention_when_nothing_usable():
    """Every facet failing validation (bad label, all below threshold, or
    a garbled/empty response) must never leave classify_one with zero
    facets -- cites is always the safety-net fallback."""
    result = {"relationships": [{"label": "not-a-real-label", "confidence": 0.9, "justification": "x"}]}
    facets = _parse_relationships_response(result)
    assert facets == [{"label": "cites", "confidence": 0.5, "justification": ""}]


def test_parse_response_empty_relationships_list_falls_back():
    result = {"relationships": []}
    facets = _parse_relationships_response(result)
    assert facets == [{"label": "cites", "confidence": 0.5, "justification": ""}]


def test_parse_response_non_dict_facets_are_skipped():
    result = {"relationships": ["not-a-dict", {"label": "extends", "confidence": 0.9, "justification": "x"}]}
    facets = _parse_relationships_response(result)
    assert [f["label"] for f in facets] == ["extends"]


def test_parse_response_bad_confidence_type_defaults_to_half():
    result = {"relationships": [{"label": "extends", "confidence": "high", "justification": "x"}]}
    facets = _parse_relationships_response(result)
    assert facets[0]["confidence"] == 0.5


# --- _normalize_relationships (read-compat) -------------------------------

def test_normalize_relationships_prefers_existing_list():
    payload = {
        "relationship": "extends",  # legacy scalar, should be ignored since list is present
        "relationships": [{"label": "uses-method-from", "confidence": 0.8, "justification": "x"}],
    }
    facets = _normalize_relationships(payload)
    assert facets == [{"label": "uses-method-from", "confidence": 0.8, "justification": "x"}]


def test_normalize_relationships_synthesizes_from_legacy_scalars():
    """A pre-multi-facet sidecar has no "relationships" key at all --
    _normalize_relationships must synthesize a one-element list so every
    facet-aware reader (report.py, evidence.py, evidence_wiki.py) can
    treat old and new sidecars identically."""
    payload = {"relationship": "extends", "confidence": 0.9, "justification": "Direct extension."}
    facets = _normalize_relationships(payload)
    assert facets == [{"label": "extends", "confidence": 0.9, "justification": "Direct extension."}]


def test_normalize_relationships_empty_list_falls_back_to_scalars():
    payload = {"relationship": "extends", "confidence": 0.9, "justification": "x", "relationships": []}
    facets = _normalize_relationships(payload)
    assert facets == [{"label": "extends", "confidence": 0.9, "justification": "x"}]


def test_normalize_relationships_defaults_to_background_mention():
    facets = _normalize_relationships({})
    assert facets[0]["label"] == "cites"


# --- classify_one end-to-end (multi-facet) --------------------------------

def _fake_multi_facet_response(*args, **kwargs):
    return {
        "relationships": [
            {"label": "uses-method-from", "confidence": 0.95, "justification": "Uses PnetCDF as-is for I/O."},
            {"label": "applies-to-domain", "confidence": 0.8, "justification": "Applies it to flood modeling."},
        ]
    }


def test_classify_one_with_classify_3_produces_multi_facet_sidecar():
    with patch("wake.classify.config.classify_cfg", return_value={"prompt_version": "classify-3"}), \
         patch("wake.classify.chat_json", side_effect=_fake_multi_facet_response):
        result = classify_one(PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS[0], record_cost=False)

    assert len(result["relationships"]) == 2
    assert result["relationships"][0]["label"] == "uses-method-from"
    # Legacy scalars are set from the top (most-confident) facet, so
    # every existing consumer (themes, narrative, report metrics) keeps
    # working unchanged.
    assert result["relationship"] == "uses-method-from"
    assert result["confidence"] == 0.95
    assert result["justification"] == "Uses PnetCDF as-is for I/O."


def test_classify_one_with_classify_2_produces_single_facet_sidecar():
    """Default behavior (packaged config.yaml's classify.prompt_version is
    classify-2, per the "opt-in, not a default" design) -- classify_one
    must still produce a valid single-element "relationships" list."""
    def _fake_single(*args, **kwargs):
        return {"relationship": "extends", "confidence": 0.9, "justification": "Direct extension."}

    with patch("wake.classify.config.classify_cfg", return_value={"prompt_version": "classify-2"}), \
         patch("wake.classify.chat_json", side_effect=_fake_single):
        result = classify_one(PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS[0], record_cost=False)

    assert result["relationships"] == [{"label": "extends", "confidence": 0.9, "justification": "Direct extension."}]
    assert result["relationship"] == "extends"


def test_classify_one_never_persists_strength_alongside_multi_facet():
    """Regression guard for the earlier config-driven-strength change:
    multi-facet output must not reintroduce a persisted "strength" field."""
    with patch("wake.classify.config.classify_cfg", return_value={"prompt_version": "classify-3"}), \
         patch("wake.classify.chat_json", side_effect=_fake_multi_facet_response):
        result = classify_one(PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS[0], record_cost=False)
    assert "strength" not in result
