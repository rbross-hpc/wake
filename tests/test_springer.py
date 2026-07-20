# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.sources.springer — predictable Springer PDF URL
construction, offline (no network call, so no mocking needed)."""
from __future__ import annotations

from wake.sources import springer


def test_constructs_url_for_bare_springer_doi():
    url = springer.get_fulltext_pdf_url_by_doi("10.1007/978-3-540-92859-1_9")
    assert url == "https://link.springer.com/content/pdf/10.1007/978-3-540-92859-1_9.pdf"


def test_strips_doi_org_prefix():
    url = springer.get_fulltext_pdf_url_by_doi("https://doi.org/10.1007/978-3-540-92859-1_9")
    assert url == "https://link.springer.com/content/pdf/10.1007/978-3-540-92859-1_9.pdf"


def test_strips_doi_colon_prefix():
    url = springer.get_fulltext_pdf_url_by_doi("doi:10.1007/978-3-540-92859-1_9")
    assert url == "https://link.springer.com/content/pdf/10.1007/978-3-540-92859-1_9.pdf"


def test_non_springer_doi_returns_none():
    assert springer.get_fulltext_pdf_url_by_doi("10.1109/icpp.2009.68") is None
    assert springer.get_fulltext_pdf_url_by_doi("10.1145/1048935.1050189") is None
    assert springer.get_fulltext_pdf_url_by_doi("10.1016/j.envsoft.2011.08.007") is None


def test_none_doi_returns_none():
    assert springer.get_fulltext_pdf_url_by_doi(None) is None


def test_empty_doi_returns_none():
    assert springer.get_fulltext_pdf_url_by_doi("") is None
    assert springer.get_fulltext_pdf_url_by_doi("   ") is None
