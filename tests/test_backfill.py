# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.backfill — lazy abstract backfill, offline (mocked sources)."""
from __future__ import annotations

import pytest
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
