# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.author_overlap (BACKLOG Theme E)."""
from __future__ import annotations

from wake.author_overlap import compute_overlap


def test_no_overlap_when_no_shared_author_ids():
    seed = {"author_ids": ["A1", "A2"]}
    citing = {"authors": ["Carol Davis"], "author_ids": ["A3"]}
    result = compute_overlap(seed, citing)
    assert result == {"author_overlap": False, "overlapping_authors": []}


def test_overlap_detected_by_id_not_name():
    seed = {"author_ids": ["A1", "A2"]}
    citing = {"authors": ["Alice Smith", "Carol Davis"], "author_ids": ["A1", "A3"]}
    result = compute_overlap(seed, citing)
    assert result["author_overlap"] is True
    assert result["overlapping_authors"] == ["Alice Smith"]


def test_overlap_lists_multiple_overlapping_authors_in_order():
    seed = {"author_ids": ["A1", "A2", "A9"]}
    citing = {"authors": ["Bob Jones", "Alice Smith"], "author_ids": ["A2", "A1"]}
    result = compute_overlap(seed, citing)
    assert result["author_overlap"] is True
    assert result["overlapping_authors"] == ["Bob Jones", "Alice Smith"]


def test_no_overlap_when_seed_has_no_author_ids():
    # Two works both lacking author IDs must never be treated as "the
    # same team" just because both sides are empty.
    seed = {"author_ids": []}
    citing = {"authors": ["Someone"], "author_ids": []}
    result = compute_overlap(seed, citing)
    assert result == {"author_overlap": False, "overlapping_authors": []}


def test_no_overlap_when_citing_has_no_author_ids():
    seed = {"author_ids": ["A1"]}
    citing = {"authors": ["Someone"], "author_ids": []}
    result = compute_overlap(seed, citing)
    assert result == {"author_overlap": False, "overlapping_authors": []}


def test_missing_author_ids_key_entirely_is_safe():
    seed = {}
    citing = {"authors": ["Someone"]}
    result = compute_overlap(seed, citing)
    assert result == {"author_overlap": False, "overlapping_authors": []}


def test_empty_string_author_id_never_counts_as_overlap():
    # Both sides can have a "" placeholder for an authorship entry with no
    # OpenAlex author id -- these must never spuriously match each other.
    seed = {"author_ids": ["", "A1"]}
    citing = {"authors": ["Someone"], "author_ids": [""]}
    result = compute_overlap(seed, citing)
    assert result == {"author_overlap": False, "overlapping_authors": []}


def test_duplicate_author_name_only_listed_once():
    seed = {"author_ids": ["A1"]}
    citing = {"authors": ["Alice Smith", "Alice Smith"], "author_ids": ["A1", "A1"]}
    result = compute_overlap(seed, citing)
    assert result["overlapping_authors"] == ["Alice Smith"]
