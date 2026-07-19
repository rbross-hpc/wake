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


@pytest.mark.network
def test_live_get_by_doi():
    from wake.sources.openalex import get_work_by_doi
    work = get_work_by_doi("10.1145/1048935.1050189")
    assert work is not None
    assert work["openalex_id"] == "W2156077349"
    assert work["year"] == 2003


@pytest.mark.network
def test_live_iter_citing_works():
    from wake.sources.openalex import iter_citing_works, count_citing_works
    count = count_citing_works("W2156077349")
    assert count >= 100

    first_five = list(work for i, work in enumerate(iter_citing_works("W2156077349")) if i < 5)
    assert len(first_five) == 5
    for w in first_five:
        assert w.get("openalex_id")
        assert w.get("title")
