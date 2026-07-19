# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.sources.pdf_fulltext — full-document, page-tagged extraction.

Uses the same committed OSTI fixture as test_pdf_abstract.py (see that
file's docstring for provenance/licensing details).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from wake.sources import pdf_fulltext

_FIXTURE = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"


def test_extract_pages_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        pdf_fulltext.extract_pages(tmp_path / "nope.pdf")


def test_extract_pages_returns_one_entry_per_page():
    pages = pdf_fulltext.extract_pages(_FIXTURE)
    assert len(pages) == 2  # fixture is a 2-page PDF
    assert all(isinstance(p, str) for p in pages)
    assert all(len(p) > 100 for p in pages)  # both pages have real text


def test_extract_pages_content_matches_known_text():
    pages = pdf_fulltext.extract_pages(_FIXTURE)
    assert "netcdf" in pages[0].lower()
    assert "ornl" in pages[0].lower()


def test_extract_full_text_includes_page_markers():
    text = pdf_fulltext.extract_full_text(_FIXTURE)
    assert "[page 1]" in text
    assert "[page 2]" in text


def test_extract_full_text_page_markers_in_order():
    text = pdf_fulltext.extract_full_text(_FIXTURE)
    assert text.index("[page 1]") < text.index("[page 2]")


def test_extract_full_text_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        pdf_fulltext.extract_full_text(tmp_path / "nope.pdf")
