# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.citing sort/sample primitives."""
from __future__ import annotations

import pytest
from wake.citing import sort_works, sample_works, filter_works
from .conftest import SAMPLE_CITING_WORKS


def test_sort_by_cited_by():
    sorted_works = sort_works(SAMPLE_CITING_WORKS, "cited-by")
    counts = [w["cited_by_count"] for w in sorted_works]
    assert counts == sorted(counts, reverse=True)


def test_sort_by_recent():
    sorted_works = sort_works(SAMPLE_CITING_WORKS, "recent")
    years = [w["year"] for w in sorted_works]
    assert years == sorted(years, reverse=True)


def test_sort_by_oldest():
    sorted_works = sort_works(SAMPLE_CITING_WORKS, "oldest")
    years = [w["year"] for w in sorted_works]
    assert years == sorted(years)


def test_sort_random_preserves_set():
    sorted_works = sort_works(SAMPLE_CITING_WORKS, "random")
    assert {w["openalex_id"] for w in sorted_works} == {w["openalex_id"] for w in SAMPLE_CITING_WORKS}


def test_sample_works_default_cited_by():
    sample = sample_works(SAMPLE_CITING_WORKS, n=2)
    assert len(sample) == 2
    assert sample[0]["cited_by_count"] >= sample[1]["cited_by_count"]


def test_sample_works_n_larger_than_pool():
    sample = sample_works(SAMPLE_CITING_WORKS, n=100)
    assert len(sample) == len(SAMPLE_CITING_WORKS)


def test_filter_works_with_sort():
    result = filter_works(SAMPLE_CITING_WORKS, sort="cited-by", limit=1)
    assert len(result) == 1
    assert result[0]["cited_by_count"] == max(w["cited_by_count"] for w in SAMPLE_CITING_WORKS)


def test_filter_works_min_year():
    result = filter_works(SAMPLE_CITING_WORKS, min_year=2009)
    assert all(w["year"] >= 2009 for w in result)
