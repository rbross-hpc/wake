# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.backfill — lazy abstract backfill, offline (mocked sources)."""
from __future__ import annotations

from unittest.mock import patch

from wake import backfill

WORK_NO_ABSTRACT = {
    "openalex_id": "W1",
    "title": "Some Citing Paper",
    "doi": "10.1234/fake",
    "abstract": None,
}

WORK_HAS_ABSTRACT = {
    "openalex_id": "W2",
    "title": "Another Paper",
    "doi": "10.1234/fake2",
    "abstract": "Already has one.",
}

WORK_NO_DOI = {
    "openalex_id": "W3",
    "title": "No DOI Paper",
    "doi": None,
    "abstract": None,
}


def test_backfill_one_skips_work_with_abstract():
    result = backfill.backfill_one(WORK_HAS_ABSTRACT)
    assert result == WORK_HAS_ABSTRACT


def test_backfill_one_skips_work_without_doi():
    result = backfill.backfill_one(WORK_NO_DOI)
    assert result == WORK_NO_DOI


def test_backfill_one_tries_osti_first():
    with patch("wake.backfill.osti.get_abstract_by_doi", return_value="OSTI abstract text.") as mock_osti, \
         patch("wake.backfill.semanticscholar.get_abstract_by_doi") as mock_ss:
        result = backfill.backfill_one(WORK_NO_ABSTRACT)
    mock_osti.assert_called_once_with("10.1234/fake")
    mock_ss.assert_not_called()
    assert result["abstract"] == "OSTI abstract text."
    assert result["abstract_source"] == "osti"


def test_backfill_one_falls_through_to_semanticscholar():
    with patch("wake.backfill.osti.get_abstract_by_doi", return_value=None), \
         patch("wake.backfill.semanticscholar.get_abstract_by_doi", return_value="S2 abstract text.") as mock_ss:
        result = backfill.backfill_one(WORK_NO_ABSTRACT)
    mock_ss.assert_called_once_with("10.1234/fake")
    assert result["abstract"] == "S2 abstract text."
    assert result["abstract_source"] == "semanticscholar"


def test_backfill_one_no_source_hits():
    with patch("wake.backfill.osti.get_abstract_by_doi", return_value=None), \
         patch("wake.backfill.semanticscholar.get_abstract_by_doi", return_value=None):
        result = backfill.backfill_one(WORK_NO_ABSTRACT)
    assert result == WORK_NO_ABSTRACT
    assert "abstract_source" not in result


def test_backfill_one_source_error_falls_through():
    with patch("wake.backfill.osti.get_abstract_by_doi", side_effect=RuntimeError("boom")), \
         patch("wake.backfill.semanticscholar.get_abstract_by_doi", return_value="Recovered anyway.") as mock_ss:
        result = backfill.backfill_one(WORK_NO_ABSTRACT, verbose=False)
    mock_ss.assert_called_once()
    assert result["abstract"] == "Recovered anyway."


def test_backfill_missing_only_touches_works_without_abstract():
    works = [WORK_HAS_ABSTRACT, WORK_NO_ABSTRACT, WORK_NO_DOI]
    with patch("wake.backfill.osti.get_abstract_by_doi", return_value="Backfilled."):
        result = backfill.backfill_missing(works, verbose=False)

    by_id = {w["openalex_id"]: w for w in result}
    assert by_id["W2"] == WORK_HAS_ABSTRACT
    assert by_id["W3"] == WORK_NO_DOI
    assert by_id["W1"]["abstract"] == "Backfilled."


def test_backfill_missing_disabled_via_config():
    works = [WORK_NO_ABSTRACT]
    with patch("wake.backfill.is_enabled", return_value=False), \
         patch("wake.backfill.osti.get_abstract_by_doi") as mock_osti:
        result = backfill.backfill_missing(works, verbose=False)
    mock_osti.assert_not_called()
    assert result == works


# --- Primo integration ---
#
# Primo is opt-in (wake.sources.primo.is_enabled() is False unless an
# endpoint is configured — see test_primo.py and conftest.py's autouse
# env-clearing fixture). These tests explicitly patch is_enabled() to
# simulate "Primo is configured" without needing a real endpoint, so
# they exercise the ordering/preference logic in isolation from Primo's
# own endpoint-resolution behavior.


def test_backfill_one_tries_primo_first_when_enabled():
    with patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch("wake.backfill.primo.get_abstract_by_doi", return_value="Primo abstract text.") as mock_primo, \
         patch("wake.backfill.osti.get_abstract_by_doi") as mock_osti, \
         patch("wake.backfill.semanticscholar.get_abstract_by_doi") as mock_ss:
        result = backfill.backfill_one(WORK_NO_ABSTRACT)
    mock_primo.assert_called_once_with("10.1234/fake")
    mock_osti.assert_not_called()
    mock_ss.assert_not_called()
    assert result["abstract"] == "Primo abstract text."
    assert result["abstract_source"] == "primo"


def test_backfill_one_falls_through_primo_to_osti():
    with patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch("wake.backfill.primo.get_abstract_by_doi", return_value=None), \
         patch("wake.backfill.osti.get_abstract_by_doi", return_value="OSTI abstract text.") as mock_osti:
        result = backfill.backfill_one(WORK_NO_ABSTRACT)
    mock_osti.assert_called_once_with("10.1234/fake")
    assert result["abstract"] == "OSTI abstract text."
    assert result["abstract_source"] == "osti"


def test_backfill_one_primo_disabled_skips_straight_to_osti():
    """Default posture (no endpoint configured): primo.is_enabled() is
    False, so the cascade should never even call primo's abstract lookup —
    matches today's OSTI-first behavior exactly."""
    with patch("wake.backfill.primo.is_enabled", return_value=False), \
         patch("wake.backfill.primo.get_abstract_by_doi") as mock_primo, \
         patch("wake.backfill.osti.get_abstract_by_doi", return_value="OSTI abstract text.") as mock_osti:
        result = backfill.backfill_one(WORK_NO_ABSTRACT)
    mock_primo.assert_not_called()
    mock_osti.assert_called_once_with("10.1234/fake")
    assert result["abstract_source"] == "osti"


def test_backfill_one_doi_backfill_via_primo():
    with patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch("wake.backfill.primo.get_doi_by_title", return_value="10.9999/recovered") as mock_doi, \
         patch("wake.backfill.primo.get_abstract_by_doi", return_value="Abstract via recovered DOI.") as mock_abs:
        result = backfill.backfill_one(WORK_NO_DOI)
    mock_doi.assert_called_once_with("No DOI Paper")
    mock_abs.assert_called_once_with("10.9999/recovered")
    assert result["doi"] == "10.9999/recovered"
    assert result["doi_source"] == "primo"
    assert result["abstract"] == "Abstract via recovered DOI."


def test_backfill_one_doi_backfill_noop_when_primo_disabled():
    with patch("wake.backfill.primo.is_enabled", return_value=False), \
         patch("wake.backfill.primo.get_doi_by_title") as mock_doi:
        result = backfill.backfill_one(WORK_NO_DOI)
    mock_doi.assert_not_called()
    assert result == WORK_NO_DOI


def test_backfill_one_doi_backfill_miss_leaves_work_unchanged():
    with patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch("wake.backfill.primo.get_doi_by_title", return_value=None):
        result = backfill.backfill_one(WORK_NO_DOI)
    assert result == WORK_NO_DOI


def test_backfill_one_prefer_primo_over_openalex_hit():
    cfg = {
        "sources": backfill.DEFAULT_SOURCES,
        "rate_limit_s": {},
        "primo": {"prefer_over_openalex": True},
    }
    with patch("wake.backfill._cfg", return_value=cfg), \
         patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch("wake.backfill.primo.get_abstract_by_doi", return_value="Better Primo abstract.") as mock_primo, \
         patch("wake.backfill.osti.get_abstract_by_doi") as mock_osti:
        result = backfill.backfill_one(WORK_HAS_ABSTRACT)
    mock_primo.assert_called_once_with("10.1234/fake2")
    mock_osti.assert_not_called()
    assert result["abstract"] == "Better Primo abstract."
    assert result["abstract_source"] == "primo"


def test_backfill_one_prefer_primo_miss_keeps_openalex_abstract_no_fallthrough():
    cfg = {
        "sources": backfill.DEFAULT_SOURCES,
        "rate_limit_s": {},
        "primo": {"prefer_over_openalex": True},
    }
    with patch("wake.backfill._cfg", return_value=cfg), \
         patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch("wake.backfill.primo.get_abstract_by_doi", return_value=None), \
         patch("wake.backfill.osti.get_abstract_by_doi") as mock_osti, \
         patch("wake.backfill.semanticscholar.get_abstract_by_doi") as mock_ss:
        result = backfill.backfill_one(WORK_HAS_ABSTRACT)
    mock_osti.assert_not_called()
    mock_ss.assert_not_called()
    assert result == WORK_HAS_ABSTRACT


def test_backfill_one_prefer_primo_mode_but_primo_disabled_is_noop():
    cfg = {
        "sources": backfill.DEFAULT_SOURCES,
        "rate_limit_s": {},
        "primo": {"prefer_over_openalex": True},
    }
    with patch("wake.backfill._cfg", return_value=cfg), \
         patch("wake.backfill.primo.is_enabled", return_value=False), \
         patch("wake.backfill.primo.get_abstract_by_doi") as mock_primo:
        result = backfill.backfill_one(WORK_HAS_ABSTRACT)
    mock_primo.assert_not_called()
    assert result == WORK_HAS_ABSTRACT


def test_default_sources_has_primo_first():
    assert backfill.DEFAULT_SOURCES[0] == "primo"
