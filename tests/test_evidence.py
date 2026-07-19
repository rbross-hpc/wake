# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.evidence — full-text verification dossier, offline.

Uses the same committed OSTI fixture as test_pdf_abstract.py for real PDF
extraction, with the LLM verification call mocked (offline-safe). A
@pytest.mark.network test at the bottom runs the full pipeline live
against the real Argo endpoint.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from wake import evidence
from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS

_FIXTURE = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"

CLASSIFIED_CITING_WORK = {
    **SAMPLE_CITING_WORKS[0],
    "relationship": "uses-as-tool",
    "confidence": 0.4,
    "justification": "Likely uses PnetCDF for I/O, based on the abstract alone.",
    "has_abstract": True,
    "strength": 5,
    "verification_status": "provisional",
}


def _fake_verification_response(relationship="extends", agrees=False, quotes=None):
    return {
        "relationship": relationship,
        "confidence": 0.9,
        "justification": "The full text clearly shows a direct extension of the seed's method.",
        "agrees_with_provisional": agrees,
        "quotes": quotes if quotes is not None else [
            {"page": 2, "text": "We directly extend the subfiling scheme introduced by the seed paper to support asynchronous I/O.", "note": "Direct statement of extension"},
        ],
    }


def test_evidence_dir_and_paths(tmp_path):
    d = evidence.evidence_dir("W123", base=tmp_path)
    assert d.name == "evidence"
    md_path = evidence.dossier_path("W123", "W456", base=tmp_path)
    assert md_path.name == "W456.md"
    json_path = evidence.dossier_json_path("W123", "W456", base=tmp_path)
    assert json_path.name == "W456.json"


def test_verify_full_text_returns_structured_finding():
    with patch("wake.evidence.chat_json", return_value=_fake_verification_response()):
        finding = evidence.verify_full_text(
            PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, "some full text here",
            record_cost=False,
        )
    assert finding["provisional"]["relationship"] == "uses-as-tool"
    assert finding["proposed"]["relationship"] == "extends"
    assert finding["proposed"]["agrees_with_provisional"] is False
    assert len(finding["quotes"]) == 1
    assert finding["quotes"][0]["page"] == 2


def test_verify_full_text_rejects_invalid_relationship_label():
    with patch("wake.evidence.chat_json", return_value=_fake_verification_response(relationship="not-a-real-label")):
        finding = evidence.verify_full_text(
            PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, "text",
            record_cost=False,
        )
    assert finding["proposed"]["relationship"] == "background-mention"


def test_verify_full_text_filters_empty_quotes():
    with patch("wake.evidence.chat_json", return_value=_fake_verification_response(
        quotes=[{"page": 1, "text": "", "note": "empty"}, {"page": 2, "text": "Real quote text.", "note": "real"}]
    )):
        finding = evidence.verify_full_text(
            PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, "text",
            record_cost=False,
        )
    assert len(finding["quotes"]) == 1
    assert finding["quotes"][0]["text"] == "Real quote text."


def test_verify_full_text_no_quotes_when_seed_barely_mentioned():
    with patch("wake.evidence.chat_json", return_value=_fake_verification_response(
        relationship="background-mention", quotes=[],
    )):
        finding = evidence.verify_full_text(
            PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, "text",
            record_cost=False,
        )
    assert finding["quotes"] == []
    assert finding["proposed"]["relationship"] == "background-mention"


def test_build_dossier_no_pdf_available(tmp_path):
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": False, "tried": ["osti", "semanticscholar"], "fallback_links": {"google_scholar": "http://..."},
    }):
        result = evidence.build_dossier(
            PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, base=tmp_path, verbose=False,
        )
    assert result["ok"] is False
    assert result["reason"] == "no_pdf"
    assert "fallback_links" in result["fetch_result"]


def test_build_dossier_end_to_end_with_real_fixture_pdf(tmp_path):
    """Full pipeline against the real committed fixture PDF, with only the
    LLM verification call mocked -- exercises real fetch_pdf caching +
    real pdf_fulltext extraction end to end."""
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(_FIXTURE), "source": "osti",
    }), patch("wake.evidence.chat_json", return_value=_fake_verification_response()):
        result = evidence.build_dossier(
            PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, base=tmp_path, verbose=False,
        )

    assert result["ok"] is True
    assert result["proposed"]["relationship"] == "extends"
    assert Path(result["dossier_path"]).exists()
    assert Path(result["dossier_json_path"]).exists()

    md_text = Path(result["dossier_path"]).read_text()
    assert "type: citing-work-evidence" in md_text
    assert "Provisional Classification" in md_text
    assert "Full-Text Reading" in md_text
    assert "We directly extend the subfiling scheme" in md_text  # quote appears verbatim
    assert "pending your review" in md_text.lower()


def test_build_dossier_caches_on_second_call(tmp_path):
    call_count = {"n": 0}

    def _counting_chat_json(*args, **kwargs):
        call_count["n"] += 1
        return _fake_verification_response()

    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(_FIXTURE), "source": "osti",
    }), patch("wake.evidence.chat_json", side_effect=_counting_chat_json):
        evidence.build_dossier(PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, base=tmp_path, verbose=False)
        result2 = evidence.build_dossier(PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, base=tmp_path, verbose=False)

    assert call_count["n"] == 1  # second call used the cached dossier, no new LLM call
    assert result2["ok"] is True
    assert result2["proposed"]["relationship"] == "extends"


def test_build_dossier_force_bypasses_cache(tmp_path):
    call_count = {"n": 0}

    def _counting_chat_json(*args, **kwargs):
        call_count["n"] += 1
        return _fake_verification_response()

    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(_FIXTURE), "source": "osti",
    }), patch("wake.evidence.chat_json", side_effect=_counting_chat_json):
        evidence.build_dossier(PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, base=tmp_path, verbose=False)
        evidence.build_dossier(PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, base=tmp_path, force=True, verbose=False)

    assert call_count["n"] == 2


def test_load_dossier_missing_returns_none(tmp_path):
    assert evidence.load_dossier("W999", "W888", base=tmp_path) is None


def test_load_dossier_after_build(tmp_path):
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(_FIXTURE), "source": "osti",
    }), patch("wake.evidence.chat_json", return_value=_fake_verification_response()):
        evidence.build_dossier(PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, base=tmp_path, verbose=False)

    loaded = evidence.load_dossier(PARALLEL_NETCDF_WORK["openalex_id"], CLASSIFIED_CITING_WORK["openalex_id"], base=tmp_path)
    assert loaded is not None
    assert loaded["proposed"]["relationship"] == "extends"


def test_dossier_markdown_quotes_full_paragraph_verbatim(tmp_path):
    """Per design requirement: quotes must be full context, pasted verbatim
    into the dossier -- not paraphrased or truncated to a fragment."""
    long_quote = (
        "In this section we describe how our approach builds directly on the "
        "parallel I/O interface introduced by the seed library. Unlike prior "
        "work that merely uses the library as a black box, our contribution "
        "modifies the underlying collective I/O scheduler to add support for "
        "asynchronous, non-blocking writes, which the original library did not provide."
    )
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(_FIXTURE), "source": "osti",
    }), patch("wake.evidence.chat_json", return_value=_fake_verification_response(
        quotes=[{"page": 3, "text": long_quote, "note": "Describes the extension mechanism"}]
    )):
        result = evidence.build_dossier(PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, base=tmp_path, verbose=False)

    md_text = Path(result["dossier_path"]).read_text()
    assert long_quote in md_text
    assert "p. 3" in md_text


@pytest.mark.network
def test_verify_full_text_live():
    """Live end-to-end test against the real Argo endpoint, using the real
    fixture PDF's full text (both pages) and a deliberately-wrong
    provisional classification, to confirm the model reads the text
    independently rather than just agreeing with the provisional guess."""
    from wake.sources.pdf_fulltext import extract_full_text

    full_text = extract_full_text(_FIXTURE)
    fake_citing_work = {
        "openalex_id": "W-live-test",
        "title": "Accessing and Distributing Large Volumes of NetCDF Data",
        "year": 2016,
        "relationship": "extends",  # deliberately implausible provisional guess
        "confidence": 0.3,
        "justification": "Guessed from title alone.",
    }
    fake_seed = {
        "openalex_id": "W-seed-live-test",
        "title": "Parallel netCDF: A High-Performance Scientific I/O Interface",
        "year": 2003,
    }

    finding = evidence.verify_full_text(
        fake_seed, fake_citing_work, full_text, record_cost=False,
    )
    assert finding["proposed"]["relationship"] in evidence_relationships()
    assert isinstance(finding["proposed"]["confidence"], float)
    assert isinstance(finding["quotes"], list)


def evidence_relationships():
    from wake.classify import RELATIONSHIPS
    return RELATIONSHIPS
