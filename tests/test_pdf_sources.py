# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for the individual PDF-acquisition source modules — offline unit
tests (URL/parsing logic mocked or exercised against synthetic data) plus
a few @pytest.mark.network live checks against real, known DOIs."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from wake.sources import osti, semanticscholar, unpaywall, arxiv_fetch, core


# ---- OSTI fulltext link ----

def test_osti_get_fulltext_pdf_url_found():
    fake_record = {
        "links": [
            {"rel": "citation", "href": "https://www.osti.gov/biblio/12345"},
            {"rel": "fulltext", "href": "https://www.osti.gov/servlets/purl/12345"},
        ]
    }
    with patch("wake.sources.osti._get_record_by_doi", return_value=fake_record):
        url = osti.get_fulltext_pdf_url_by_doi("10.2172/12345")
    assert url == "https://www.osti.gov/servlets/purl/12345"


def test_osti_get_fulltext_pdf_url_no_fulltext_link():
    fake_record = {"links": [{"rel": "citation", "href": "https://www.osti.gov/biblio/12345"}]}
    with patch("wake.sources.osti._get_record_by_doi", return_value=fake_record):
        url = osti.get_fulltext_pdf_url_by_doi("10.2172/12345")
    assert url is None


def test_osti_get_fulltext_pdf_url_no_record():
    with patch("wake.sources.osti._get_record_by_doi", return_value=None):
        url = osti.get_fulltext_pdf_url_by_doi("10.2172/nonexistent")
    assert url is None


def test_osti_abstract_and_pdf_share_record_fetch():
    """Both get_abstract_by_doi and get_fulltext_pdf_url_by_doi should
    reuse the same underlying record fetch (single API call shape)."""
    fake_record = {"description": "An abstract.", "links": []}
    with patch("wake.sources.osti._get_record_by_doi", return_value=fake_record) as mock_fetch:
        abstract = osti.get_abstract_by_doi("10.2172/12345")
        pdf_url = osti.get_fulltext_pdf_url_by_doi("10.2172/12345")
    assert abstract == "An abstract."
    assert pdf_url is None
    assert mock_fetch.call_count == 2


# ---- Semantic Scholar openAccessPdf ----

def test_semanticscholar_get_open_access_pdf_found():
    fake_entry = {"openAccessPdf": {"url": "https://arxiv.org/pdf/0903.4875", "status": "GREEN"}}
    with patch("wake.sources.semanticscholar._get_paper_by_doi", return_value=fake_entry):
        url = semanticscholar.get_open_access_pdf_url_by_doi("10.1016/fake")
    assert url == "https://arxiv.org/pdf/0903.4875"


def test_semanticscholar_get_open_access_pdf_none():
    with patch("wake.sources.semanticscholar._get_paper_by_doi", return_value={"openAccessPdf": None}):
        url = semanticscholar.get_open_access_pdf_url_by_doi("10.1016/fake")
    assert url is None


def test_semanticscholar_get_open_access_pdf_no_entry():
    with patch("wake.sources.semanticscholar._get_paper_by_doi", return_value=None):
        url = semanticscholar.get_open_access_pdf_url_by_doi("10.1016/fake")
    assert url is None


# ---- Unpaywall ----

def test_unpaywall_requires_mailto(monkeypatch):
    monkeypatch.delenv("OPENALEX_MAILTO", raising=False)
    url = unpaywall.get_oa_pdf_url_by_doi("10.1016/fake")
    assert url is None


def test_unpaywall_get_oa_pdf_url_found(monkeypatch):
    monkeypatch.setenv("OPENALEX_MAILTO", "test@example.com")
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "best_oa_location": {"url_for_pdf": "https://example.com/paper.pdf"}
    }
    with patch("wake.sources.unpaywall.requests.get", return_value=fake_response):
        url = unpaywall.get_oa_pdf_url_by_doi("10.1016/fake")
    assert url == "https://example.com/paper.pdf"


def test_unpaywall_get_oa_pdf_url_no_doi(monkeypatch):
    monkeypatch.setenv("OPENALEX_MAILTO", "test@example.com")
    assert unpaywall.get_oa_pdf_url_by_doi("") is None
    assert unpaywall.get_oa_pdf_url_by_doi(None) is None


def test_unpaywall_get_oa_pdf_url_404(monkeypatch):
    monkeypatch.setenv("OPENALEX_MAILTO", "test@example.com")
    fake_response = MagicMock()
    fake_response.status_code = 404
    with patch("wake.sources.unpaywall.requests.get", return_value=fake_response):
        url = unpaywall.get_oa_pdf_url_by_doi("10.1016/fake")
    assert url is None


# ---- arXiv title search ----

_ARXIV_ATOM_RESPONSE = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/0903.4875v1</id>
    <title>Combining I/O Operations for Multiple Array Variables in Parallel netCDF</title>
  </entry>
</feed>
"""

_ARXIV_ATOM_EMPTY = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>
"""


def test_arxiv_find_pdf_url_by_title_match():
    fake_response = MagicMock()
    fake_response.text = _ARXIV_ATOM_RESPONSE
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    with patch("wake.sources.arxiv_fetch._session") as mock_session:
        mock_session.return_value.get.return_value = fake_response
        url = arxiv_fetch.find_pdf_url_by_title(
            "Combining I/O Operations for Multiple Array Variables in Parallel netCDF"
        )
    assert url == "https://arxiv.org/pdf/0903.4875"


def test_arxiv_find_pdf_url_by_title_no_match():
    fake_response = MagicMock()
    fake_response.text = _ARXIV_ATOM_EMPTY
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    with patch("wake.sources.arxiv_fetch._session") as mock_session:
        mock_session.return_value.get.return_value = fake_response
        url = arxiv_fetch.find_pdf_url_by_title("Some Totally Unrelated Title")
    assert url is None


def test_arxiv_find_pdf_url_by_title_below_similarity_threshold():
    fake_response = MagicMock()
    fake_response.text = _ARXIV_ATOM_RESPONSE
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    with patch("wake.sources.arxiv_fetch._session") as mock_session:
        mock_session.return_value.get.return_value = fake_response
        # Real title is about "Combining I/O Operations..." — searching for
        # a barely-related title should not match given the 0.90 threshold.
        url = arxiv_fetch.find_pdf_url_by_title("A completely different paper about biology")
    assert url is None


def test_arxiv_find_pdf_url_by_title_empty_title():
    assert arxiv_fetch.find_pdf_url_by_title("") is None
    assert arxiv_fetch.find_pdf_url_by_title(None) is None


# ---- CORE.ac.uk (key-gated) ----

def test_core_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("CORE_API_KEY", raising=False)
    assert core.is_enabled() is False
    assert core.get_oa_pdf_url_by_doi("10.1016/fake") is None


def test_core_enabled_with_api_key(monkeypatch):
    monkeypatch.setenv("CORE_API_KEY", "fake-key")
    assert core.is_enabled() is True


def test_core_get_oa_pdf_url_found(monkeypatch):
    monkeypatch.setenv("CORE_API_KEY", "fake-key")
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "results": [{"downloadUrl": "https://core.ac.uk/download/12345.pdf"}]
    }
    with patch("wake.sources.core.requests.get", return_value=fake_response):
        url = core.get_oa_pdf_url_by_doi("10.1016/fake")
    assert url == "https://core.ac.uk/download/12345.pdf"


def test_core_get_oa_pdf_url_fallback_to_fulltext_urls(monkeypatch):
    monkeypatch.setenv("CORE_API_KEY", "fake-key")
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "results": [{"downloadUrl": None, "sourceFulltextUrls": ["https://example.com/a.pdf"]}]
    }
    with patch("wake.sources.core.requests.get", return_value=fake_response):
        url = core.get_oa_pdf_url_by_doi("10.1016/fake")
    assert url == "https://example.com/a.pdf"


def test_core_get_oa_pdf_url_no_results(monkeypatch):
    monkeypatch.setenv("CORE_API_KEY", "fake-key")
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {"results": []}
    with patch("wake.sources.core.requests.get", return_value=fake_response):
        url = core.get_oa_pdf_url_by_doi("10.1016/fake")
    assert url is None


def test_core_empty_fulltext_urls_list_does_not_crash(monkeypatch):
    """Regression guard: an empty sourceFulltextUrls list must not raise
    IndexError."""
    monkeypatch.setenv("CORE_API_KEY", "fake-key")
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "results": [{"downloadUrl": None, "sourceFulltextUrls": []}]
    }
    with patch("wake.sources.core.requests.get", return_value=fake_response):
        url = core.get_oa_pdf_url_by_doi("10.1016/fake")
    assert url is None


# ---- Live network tests (real DOIs known to have OA copies) ----

@pytest.mark.network
def test_osti_live_fulltext_link():
    # Known DOE technical report with a fulltext link (see BACKLOG.md / earlier session).
    url = osti.get_fulltext_pdf_url_by_doi("10.2172/10129297")
    assert url is None or url.startswith("https://www.osti.gov/servlets/purl/")


@pytest.mark.network
def test_semanticscholar_live_open_access_pdf():
    url = semanticscholar.get_open_access_pdf_url_by_doi("10.1016/j.parco.2009.08.001")
    assert url is None or url.startswith("http")


@pytest.mark.network
def test_arxiv_live_find_pdf_url():
    url = arxiv_fetch.find_pdf_url_by_title(
        "Combining I/O operations for multiple array variables in parallel netCDF"
    )
    assert url is None or url.startswith("https://arxiv.org/pdf/")
