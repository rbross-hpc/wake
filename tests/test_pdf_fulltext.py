# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.sources.pdf_fulltext — full-document, page-tagged extraction.

Uses the same committed OSTI fixture as test_pdf_abstract.py (see that
file's docstring for provenance/licensing details).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

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


def test_extract_full_text_from_pages_joins_with_markers():
    text = pdf_fulltext.extract_full_text_from_pages(["Page one text.", "Page two text."])
    assert text == "[page 1]\nPage one text.\n\n[page 2]\nPage two text."


def test_extract_full_text_from_pages_skips_blank_pages():
    text = pdf_fulltext.extract_full_text_from_pages(["Real text.", "", "  "])
    assert "[page 2]" not in text
    assert "[page 3]" not in text


# ---- Extraction caching (extract_pages_cached / extracted_text_path) ----

def test_extracted_text_path_is_sibling_json_file():
    p = pdf_fulltext.extracted_text_path("/some/dir/W123.pdf")
    assert p == Path("/some/dir/W123.json")


def test_extract_pages_cached_missing_pdf_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        pdf_fulltext.extract_pages_cached(tmp_path / "nope.pdf")


def test_extract_pages_cached_writes_cache_file(tmp_path):
    pdf_copy = tmp_path / "test.pdf"
    shutil.copy(_FIXTURE, pdf_copy)
    cache_path = pdf_fulltext.extracted_text_path(pdf_copy)

    assert not cache_path.exists()
    pages = pdf_fulltext.extract_pages_cached(pdf_copy)
    assert cache_path.exists()

    data = json.loads(cache_path.read_text())
    assert data["pages"] == pages
    assert data["extractor"] in ("pypdf", "pdfplumber")
    assert len(data["pdf_sha256"]) == 64  # sha256 hex digest length
    assert data["pdf_path"] == str(pdf_copy)
    assert "extracted_at" in data


def test_extract_pages_cached_second_call_skips_extraction(tmp_path):
    pdf_copy = tmp_path / "test.pdf"
    shutil.copy(_FIXTURE, pdf_copy)

    pdf_fulltext.extract_pages_cached(pdf_copy)  # populate cache

    with patch("wake.sources.pdf_fulltext._try_pypdf") as mock_pypdf, \
         patch("wake.sources.pdf_fulltext._try_pdfplumber") as mock_plumber:
        pages = pdf_fulltext.extract_pages_cached(pdf_copy)

    mock_pypdf.assert_not_called()
    mock_plumber.assert_not_called()
    assert len(pages) == 2


def test_extract_pages_cached_force_reextracts(tmp_path):
    pdf_copy = tmp_path / "test.pdf"
    shutil.copy(_FIXTURE, pdf_copy)

    pdf_fulltext.extract_pages_cached(pdf_copy)  # populate cache

    with patch(
        "wake.sources.pdf_fulltext._extract_pages_with_extractor_name",
        return_value=(["forced re-extraction"], "pypdf"),
    ) as mock_extract:
        pages = pdf_fulltext.extract_pages_cached(pdf_copy, force=True)

    mock_extract.assert_called_once()
    assert pages == ["forced re-extraction"]


def test_extract_pages_cached_detects_changed_pdf(tmp_path):
    """If the underlying PDF file changes (e.g. a fresh fetch-pdf --force
    swapped in a different file), the sha256 mismatch must be detected and
    extraction must re-run automatically -- no explicit invalidation call
    needed."""
    pdf_copy = tmp_path / "test.pdf"
    shutil.copy(_FIXTURE, pdf_copy)

    pdf_fulltext.extract_pages_cached(pdf_copy)
    cache_path = pdf_fulltext.extracted_text_path(pdf_copy)
    original_sha = json.loads(cache_path.read_text())["pdf_sha256"]

    with open(pdf_copy, "ab") as f:
        f.write(b"appended bytes to change the file's hash")

    pages = pdf_fulltext.extract_pages_cached(pdf_copy)
    new_sha = json.loads(cache_path.read_text())["pdf_sha256"]

    assert new_sha != original_sha
    assert len(pages) == 2  # re-extraction still succeeds on the same content


def test_extract_pages_cached_corrupt_cache_file_falls_back_to_extraction(tmp_path):
    pdf_copy = tmp_path / "test.pdf"
    shutil.copy(_FIXTURE, pdf_copy)
    cache_path = pdf_fulltext.extracted_text_path(pdf_copy)
    cache_path.write_text("not valid json{{{")

    pages = pdf_fulltext.extract_pages_cached(pdf_copy)
    assert len(pages) == 2
    # cache file should now be valid, overwritten by the fresh extraction
    data = json.loads(cache_path.read_text())
    assert data["pages"] == pages
