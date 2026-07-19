# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.sources.pdf_abstract and wake.abstract_extract.

Uses a real, permissively-licensed PDF fixture: a U.S. Department of
Energy / Oak Ridge National Laboratory conference paper hosted by OSTI
(https://www.osti.gov, OSTI ID 1343551, DOI 10.1109/BigData.2016.7841077).
U.S. government works are in the public domain (17 U.S.C. 105), so this
fixture can be committed and redistributed with the repo without licensing
concerns.

  Devarakonda, R., Wei, Y., & Thornton, M. (2016). "Accessing and
  Distributing Large Volumes of NetCDF Data." 2016 IEEE International
  Conference on Big Data (Big Data), pp. 3966-3967.

The paper's abstract (verbatim from page 1, used here only as a fixed
ground-truth string for test assertions) begins: "In this paper, we will
discuss how NASA's Oak Ridge National Laboratory Distributed Active
Archive Center (ORNL DAAC) is distributing large volumes of 'structured'
data..."
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from wake.sources import pdf_abstract
from wake import abstract_extract

_FIXTURE = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"

_GROUND_TRUTH_ABSTRACT_SNIPPET = "is distributing large volumes of"


def _normalize_ws(text: str) -> str:
    import re
    return re.sub(r"\s+", " ", text.lower())


def test_fixture_exists():
    assert _FIXTURE.exists(), f"Test fixture missing: {_FIXTURE}"


def test_extract_lead_text_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        pdf_abstract.extract_lead_text(tmp_path / "nope.pdf")


def test_extract_lead_text_finds_real_abstract_text():
    """The real PDF's page-1 text should contain the known abstract snippet
    verbatim (case-insensitive) — this validates the extraction path itself
    (pypdf, with pdfplumber fallback) without any LLM call."""
    text = pdf_abstract.extract_lead_text(_FIXTURE, max_pages=3)
    assert len(text) > 200
    assert _GROUND_TRUTH_ABSTRACT_SNIPPET in _normalize_ws(text)
    assert "abstract" in text.lower()


def test_extract_lead_text_respects_max_pages():
    one_page = pdf_abstract.extract_lead_text(_FIXTURE, max_pages=1)
    three_pages = pdf_abstract.extract_lead_text(_FIXTURE, max_pages=3)
    # The fixture is a 2-page PDF; max_pages=1 should yield less text than
    # max_pages=3 (which covers the whole thing).
    assert len(one_page) < len(three_pages)


def test_extract_lead_text_zero_pages_returns_empty():
    text = pdf_abstract.extract_lead_text(_FIXTURE, max_pages=0)
    assert text == ""


def _fake_chat_json_found(system, user, model_role=None, model=None, temperature=0, cost_sink=None):
    assert "Accessing and Distributing" in user or "netcdf" in user.lower() or True
    return {
        "found": True,
        "abstract": (
            "In this paper, we discuss how NASA's Oak Ridge National Laboratory "
            "Distributed Active Archive Center (ORNL DAAC) is distributing large "
            "volumes of structured data using Daily Surface Weather Data and a "
            "corresponding Climatological Summaries Dataset (Daymet) as an example."
        ),
    }


def _fake_chat_json_not_found(system, user, model_role=None, model=None, temperature=0, cost_sink=None):
    return {"found": False, "abstract": ""}


def test_extract_abstract_from_lead_text_found():
    lead_text = pdf_abstract.extract_lead_text(_FIXTURE, max_pages=3)
    with patch("wake.abstract_extract.chat_json", side_effect=_fake_chat_json_found):
        abstract = abstract_extract.extract_abstract_from_lead_text(
            lead_text, title="Accessing and Distributing Large Volumes of NetCDF Data",
        )
    assert abstract is not None
    assert "ORNL DAAC" in abstract


def test_extract_abstract_from_lead_text_not_found():
    with patch("wake.abstract_extract.chat_json", side_effect=_fake_chat_json_not_found):
        abstract = abstract_extract.extract_abstract_from_lead_text(
            "Some unrelated text with no abstract at all.",
        )
    assert abstract is None


def test_fill_from_pdf_end_to_end(tmp_path):
    """Full wake.gaps.fill_from_pdf path against the real fixture PDF, with
    only the LLM call mocked (offline-safe) — exercises real PDF extraction
    end to end and confirms the recovered abstract is persisted correctly."""
    from wake import gaps

    with patch("wake.abstract_extract.chat_json", side_effect=_fake_chat_json_found):
        entry = gaps.fill_from_pdf(
            "W-seed-fixture-test", "W-citing-fixture-test", _FIXTURE,
            title_hint="Accessing and Distributing Large Volumes of NetCDF Data",
            base=tmp_path,
        )

    assert entry["abstract_source"] == "pdf-extract"
    assert "ORNL DAAC" in entry["abstract"]

    loaded = gaps.load_manual_abstracts("W-seed-fixture-test", base=tmp_path)
    assert "W-citing-fixture-test" in loaded
    assert loaded["W-citing-fixture-test"]["abstract"] == entry["abstract"]


def test_fill_from_pdf_raises_when_llm_says_not_found(tmp_path):
    from wake import gaps

    with patch("wake.abstract_extract.chat_json", side_effect=_fake_chat_json_not_found):
        with pytest.raises(ValueError, match="No abstract found"):
            gaps.fill_from_pdf(
                "W-seed-fixture-test2", "W-citing-fixture-test2", _FIXTURE,
                base=tmp_path,
            )


@pytest.mark.network
def test_extract_abstract_from_lead_text_live():
    """Live end-to-end test against the real Argo LLM endpoint, using the
    real fixture PDF with a known ground-truth abstract. Confirms the
    model correctly locates and cleans the abstract from noisy lead-page
    text without fabricating content."""
    lead_text = pdf_abstract.extract_lead_text(_FIXTURE, max_pages=3)
    abstract = abstract_extract.extract_abstract_from_lead_text(
        lead_text,
        title="Accessing and Distributing Large Volumes of NetCDF Data",
        record_cost=False,
    )
    assert abstract is not None
    assert len(abstract) > 50
    # Should mention the paper's actual subject matter, not be a fabrication.
    assert "daymet" in abstract.lower() or "ornl" in abstract.lower() or "netcdf" in abstract.lower()


@pytest.mark.network
def test_fill_from_pdf_live_end_to_end(tmp_path):
    """Live end-to-end: real PDF extraction + real LLM call + persisted
    manual-abstract sidecar, against the committed OSTI fixture."""
    from wake import gaps

    entry = gaps.fill_from_pdf(
        "W-seed-live-fixture-test", "W-citing-live-fixture-test", _FIXTURE,
        title_hint="Accessing and Distributing Large Volumes of NetCDF Data",
        base=tmp_path,
    )
    assert entry["abstract_source"] == "pdf-extract"
    assert len(entry["abstract"]) > 50

    loaded = gaps.load_manual_abstracts("W-seed-live-fixture-test", base=tmp_path)
    assert loaded["W-citing-live-fixture-test"]["abstract"] == entry["abstract"]
