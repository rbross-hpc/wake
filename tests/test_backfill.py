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
#
# Note: backfill.py calls primo.get_metadata_by_doi/get_record_by_title
# (not the narrower get_abstract_by_doi/get_doi_by_title wrappers)
# specifically so an OA PDF URL can be captured in the same Primo call as
# the abstract/DOI — see _with_primo_pdf_url and the primo_pdf_url tests
# below.


def _primo_record(abstract=None, doi=None, oa_pdf_url=None):
    return {"title": "x", "abstract": abstract, "doi": doi, "oa_pdf_url": oa_pdf_url}


def test_backfill_one_tries_primo_first_when_enabled():
    with patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch("wake.backfill.primo.get_metadata_by_doi", return_value=_primo_record(abstract="Primo abstract text.")) as mock_primo, \
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
         patch("wake.backfill.primo.get_metadata_by_doi", return_value=None), \
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
         patch("wake.backfill.primo.get_metadata_by_doi") as mock_primo, \
         patch("wake.backfill.osti.get_abstract_by_doi", return_value="OSTI abstract text.") as mock_osti:
        result = backfill.backfill_one(WORK_NO_ABSTRACT)
    mock_primo.assert_not_called()
    mock_osti.assert_called_once_with("10.1234/fake")
    assert result["abstract_source"] == "osti"


def test_backfill_one_doi_backfill_via_primo():
    with patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch(
             "wake.backfill.primo.get_record_by_title",
             return_value=_primo_record(abstract="Abstract via recovered DOI.", doi="10.9999/recovered"),
         ) as mock_record:
        result = backfill.backfill_one(WORK_NO_DOI)
    mock_record.assert_called_once_with("No DOI Paper")
    assert result["doi"] == "10.9999/recovered"
    assert result["doi_source"] == "primo"
    assert result["abstract"] == "Abstract via recovered DOI."
    assert result["abstract_source"] == "primo"


def test_backfill_one_doi_backfill_reuses_record_no_second_primo_call():
    """The abstract-backfill cascade must reuse the Primo record already
    fetched during DOI backfill (same underlying DOI-less work) rather
    than calling Primo a second time for the same abstract."""
    with patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch(
             "wake.backfill.primo.get_record_by_title",
             return_value=_primo_record(abstract="One-call abstract.", doi="10.9999/recovered"),
         ) as mock_record, \
         patch("wake.backfill.primo.get_metadata_by_doi") as mock_metadata:
        result = backfill.backfill_one(WORK_NO_DOI)
    mock_record.assert_called_once()
    mock_metadata.assert_not_called()
    assert result["abstract"] == "One-call abstract."


def test_backfill_one_doi_backfill_noop_when_primo_disabled():
    with patch("wake.backfill.primo.is_enabled", return_value=False), \
         patch("wake.backfill.primo.get_record_by_title") as mock_record:
        result = backfill.backfill_one(WORK_NO_DOI)
    mock_record.assert_not_called()
    assert result == WORK_NO_DOI


def test_backfill_one_doi_backfill_miss_leaves_work_unchanged():
    with patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch("wake.backfill.primo.get_record_by_title", return_value=None):
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
         patch("wake.backfill.primo.get_metadata_by_doi", return_value=_primo_record(abstract="Better Primo abstract.")) as mock_primo, \
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
         patch("wake.backfill.primo.get_metadata_by_doi", return_value=None), \
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
         patch("wake.backfill.primo.get_metadata_by_doi") as mock_primo:
        result = backfill.backfill_one(WORK_HAS_ABSTRACT)
    mock_primo.assert_not_called()
    assert result == WORK_HAS_ABSTRACT


def test_default_sources_has_primo_first():
    assert backfill.DEFAULT_SOURCES[0] == "primo"


# --- primo_pdf_url capture ---
#
# Captured as a side effect of a Primo call already being made for the
# abstract/DOI (see module docstring) -- never an extra Primo request.


def test_backfill_one_captures_primo_pdf_url_during_abstract_backfill():
    with patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch(
             "wake.backfill.primo.get_metadata_by_doi",
             return_value=_primo_record(abstract="An abstract.", oa_pdf_url="https://example.com/paper.pdf"),
         ):
        result = backfill.backfill_one(WORK_NO_ABSTRACT)
    assert result["primo_pdf_url"] == "https://example.com/paper.pdf"


def test_backfill_one_no_primo_pdf_url_field_when_absent():
    with patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch(
             "wake.backfill.primo.get_metadata_by_doi",
             return_value=_primo_record(abstract="An abstract.", oa_pdf_url=None),
         ):
        result = backfill.backfill_one(WORK_NO_ABSTRACT)
    assert "primo_pdf_url" not in result


def test_backfill_one_captures_primo_pdf_url_during_doi_backfill():
    with patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch(
             "wake.backfill.primo.get_record_by_title",
             return_value=_primo_record(doi="10.9999/recovered", oa_pdf_url="https://example.com/found.pdf"),
         ):
        result = backfill.backfill_one(WORK_NO_DOI)
    assert result["primo_pdf_url"] == "https://example.com/found.pdf"


def test_backfill_one_captures_primo_pdf_url_in_prefer_mode_even_on_abstract_miss():
    """A Primo miss on the abstract in 'prefer' mode still keeps
    OpenAlex's abstract (see the miss-keeps-existing test above), but the
    PDF URL from that same lookup should still be captured -- it's an
    independent piece of data from the abstract preference decision."""
    cfg = {
        "sources": backfill.DEFAULT_SOURCES,
        "rate_limit_s": {},
        "primo": {"prefer_over_openalex": True},
    }
    with patch("wake.backfill._cfg", return_value=cfg), \
         patch("wake.backfill.primo.is_enabled", return_value=True), \
         patch(
             "wake.backfill.primo.get_metadata_by_doi",
             return_value=_primo_record(abstract=None, oa_pdf_url="https://example.com/still-found.pdf"),
         ):
        result = backfill.backfill_one(WORK_HAS_ABSTRACT)
    assert result["abstract"] == WORK_HAS_ABSTRACT["abstract"]  # unchanged (miss)
    assert result["primo_pdf_url"] == "https://example.com/still-found.pdf"
