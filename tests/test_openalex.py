# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.sources.openalex."""
from __future__ import annotations

import pytest

from wake.sources.openalex import (
    _normalize_doi,
    _normalize_openalex_id,
    _reconstruct_abstract,
    _summarize_work,
)


def test_normalize_doi_strips_prefix():
    assert _normalize_doi("https://doi.org/10.1145/foo") == "10.1145/foo"
    assert _normalize_doi("doi:10.1145/foo") == "10.1145/foo"
    assert _normalize_doi("10.1145/foo") == "10.1145/foo"
    assert _normalize_doi(None) is None
    assert _normalize_doi("") is None


def test_normalize_doi_lowercases():
    assert _normalize_doi("10.1145/FOO") == "10.1145/foo"


def test_normalize_openalex_id():
    assert _normalize_openalex_id("W2156077349") == "W2156077349"
    assert _normalize_openalex_id("https://openalex.org/W2156077349") == "W2156077349"


def test_reconstruct_abstract_basic():
    inv = {"hello": [0], "world": [1]}
    assert _reconstruct_abstract(inv) == "hello world"


def test_reconstruct_abstract_ordered():
    inv = {"second": [1], "first": [0], "third": [2]}
    assert _reconstruct_abstract(inv) == "first second third"


def test_reconstruct_abstract_none():
    assert _reconstruct_abstract(None) is None
    assert _reconstruct_abstract({}) is None


def test_summarize_work_minimal():
    raw = {
        "id": "https://openalex.org/W123",
        "display_name": "Test Paper",
        "publication_year": 2023,
        "doi": "https://doi.org/10.1234/test",
        "cited_by_count": 5,
        "primary_location": {"source": {"display_name": "Test Journal", "type": "journal"}},
        "authorships": [{"author": {"display_name": "Alice Smith"}}],
        "type": "journal-article",
        "topics": [],
        "abstract_inverted_index": {"Test": [0], "abstract": [1]},
    }
    w = _summarize_work(raw)
    assert w["openalex_id"] == "W123"
    assert w["title"] == "Test Paper"
    assert w["year"] == 2023
    assert w["doi"] == "10.1234/test"
    assert w["authors"] == ["Alice Smith"]
    assert w["abstract"] == "Test abstract"


def test_summarize_work_preserves_author_ids():
    raw = {
        "id": "https://openalex.org/W123",
        "display_name": "Test Paper",
        "publication_year": 2023,
        "authorships": [
            {"author": {"display_name": "Alice Smith", "id": "https://openalex.org/A111"}},
            {"author": {"display_name": "Bob Jones", "id": "https://openalex.org/A222"}},
        ],
        "topics": [],
    }
    w = _summarize_work(raw)
    assert w["authors"] == ["Alice Smith", "Bob Jones"]
    assert w["author_ids"] == ["A111", "A222"]


def test_summarize_work_author_id_missing_uses_empty_string():
    raw = {
        "id": "https://openalex.org/W123",
        "display_name": "Test Paper",
        "publication_year": 2023,
        "authorships": [{"author": {"display_name": "Alice Smith"}}],
        "topics": [],
    }
    w = _summarize_work(raw)
    assert w["authors"] == ["Alice Smith"]
    assert w["author_ids"] == [""]


def test_summarize_work_authorship_with_no_name_is_skipped():
    raw = {
        "id": "https://openalex.org/W123",
        "display_name": "Test Paper",
        "publication_year": 2023,
        "authorships": [
            {"author": {"id": "https://openalex.org/A111"}},
            {"author": {"display_name": "Bob Jones", "id": "https://openalex.org/A222"}},
        ],
        "topics": [],
    }
    w = _summarize_work(raw)
    assert w["authors"] == ["Bob Jones"]
    assert w["author_ids"] == ["A222"]


# --- OA PDF URL / status capture (BACKLOG: "harvest OpenAlex OA PDF URL") ---


def test_summarize_work_captures_oa_pdf_url_and_status():
    raw = {
        "id": "https://openalex.org/W123",
        "display_name": "Open Access Paper",
        "publication_year": 2020,
        "authorships": [],
        "topics": [],
        "open_access": {"is_oa": True, "oa_status": "green"},
        "best_oa_location": {"pdf_url": "https://www.osti.gov/servlets/purl/1150929", "is_oa": True},
    }
    w = _summarize_work(raw)
    assert w["oa_pdf_url"] == "https://www.osti.gov/servlets/purl/1150929"
    assert w["oa_status"] == "green"


def test_summarize_work_closed_access_has_no_oa_pdf_url():
    raw = {
        "id": "https://openalex.org/W123",
        "display_name": "Closed Access Paper",
        "publication_year": 2020,
        "authorships": [],
        "topics": [],
        "open_access": {"is_oa": False, "oa_status": "closed"},
        "best_oa_location": None,
    }
    w = _summarize_work(raw)
    assert w["oa_pdf_url"] is None
    assert w["oa_status"] == "closed"


def test_summarize_work_missing_oa_fields_defaults_to_none():
    """A raw work with no open_access/best_oa_location keys at all (e.g.
    an older cached response, or a field the select= list didn't
    request) should degrade to None rather than KeyError."""
    raw = {
        "id": "https://openalex.org/W123",
        "display_name": "No OA Fields",
        "publication_year": 2020,
        "authorships": [],
        "topics": [],
    }
    w = _summarize_work(raw)
    assert w["oa_pdf_url"] is None
    assert w["oa_status"] is None


def test_iter_citing_works_select_includes_oa_fields():
    """Regression guard: the citing-works select= must request
    open_access/best_oa_location, or _summarize_work's oa_pdf_url/
    oa_status will silently always be None for the bulk citing path
    (single-work fetches via get_work_by_doi/get_work_by_openalex_id
    don't restrict fields at all, so they're unaffected)."""
    import inspect

    from wake.sources import openalex

    src = inspect.getsource(openalex.iter_citing_works)
    assert "open_access" in src
    assert "best_oa_location" in src


@pytest.mark.network
def test_live_get_by_doi():
    from wake.sources.openalex import get_work_by_doi
    work = get_work_by_doi("10.1145/1048935.1050189")
    assert work is not None
    assert work["openalex_id"] == "W2156077349"
    assert work["year"] == 2003


@pytest.mark.network
def test_live_iter_citing_works():
    from wake.sources.openalex import count_citing_works, iter_citing_works
    count = count_citing_works("W2156077349")
    assert count >= 100

    first_five = list(work for i, work in enumerate(iter_citing_works("W2156077349")) if i < 5)
    assert len(first_five) == 5
    for w in first_five:
        assert w.get("openalex_id")
        assert w.get("title")
