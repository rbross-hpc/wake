# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.posters — surfacing likely posters/conference-abstract
stubs for human sign-off (BACKLOG Theme J item 9), offline.

Fixtures modeled directly on three real posters/abstracts caught by hand
this session (W2036045262 "Poster reception---...", W4256234323
"Abstract: Bringing Task and Data Parallelism...", W2130808347 "Poster:
Bringing Task and Data Parallelism...") -- same shape: OpenAlex `type:
conference-abstract` and/or a `Poster:`/`Abstract:` title prefix.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from wake import exclude, posters
from wake.classify import save_classified
from .conftest import PARALLEL_NETCDF_WORK


_POSTER_TYPE_AND_PREFIX = {
    "openalex_id": "W_POSTER_1",
    "title": "Poster: Bringing Task and Data Parallelism to Analysis of Climate Model Output",
    "authors": ["Alice Smith"],
    "author_ids": ["A1000000001"],
    "year": 2013,
    "venue": None,
    "venue_type": None,
    "doi": "10.1000/fake-poster-1",
    "cited_by_count": 1,
    "type": "conference-abstract",
    "abstract": "A poster.",
    "topics": ["High-performance computing"],
}

_ABSTRACT_PREFIX_ONLY = {
    "openalex_id": "W_ABSTRACT_1",
    "title": "Abstract: Bringing Task and Data Parallelism to Analysis of Climate Model Output",
    "authors": ["Bob Jones"],
    "author_ids": ["A1000000002"],
    "year": 2013,
    "venue": "Some Workshop",
    "venue_type": "conference",
    "doi": "10.1000/fake-abstract-1",
    "cited_by_count": 1,
    "type": "article",  # deliberately not conference-abstract -- title prefix alone must be enough
    "abstract": "An abstract.",
    "topics": ["High-performance computing"],
}

_CONFERENCE_ABSTRACT_TYPE_ONLY = {
    "openalex_id": "W_POSTER_2",
    "title": "Poster reception---Parallel I/O advancements in air quality modeling systems",
    "authors": ["Carol Davis"],
    "author_ids": ["A1000000003"],
    "year": 2006,
    "venue": None,
    "venue_type": None,
    "doi": "10.1000/fake-poster-2",
    "cited_by_count": 3,
    "type": "conference-abstract",
    "abstract": "A poster reception summary.",
    "topics": ["High-performance computing"],
}

_REAL_PAPER = {
    "openalex_id": "W_REAL_PAPER",
    "title": "A Full-Length Study of Parallel I/O Performance in Climate Models",
    "authors": ["Dave Evans"],
    "author_ids": ["A1000000004"],
    "year": 2018,
    "venue": "Journal of Scientific Computing",
    "venue_type": "journal",
    "doi": "10.1000/fake-real-paper",
    "cited_by_count": 40,
    "type": "article",
    "abstract": "A full-length paper, not a poster or abstract.",
    "topics": ["High-performance computing"],
}

# Title happens to start with "Abstract" as ordinary English, not a
# poster-style prefix marker -- must not false-positive.
_ABSTRACT_LOOKALIKE_TITLE = {
    "openalex_id": "W_ABSTRACT_LOOKALIKE",
    "title": "Abstraction Layers for Parallel I/O: A Survey",
    "authors": ["Eve Foster"],
    "author_ids": ["A1000000005"],
    "year": 2019,
    "venue": "ACM Computing Surveys",
    "venue_type": "journal",
    "doi": "10.1000/fake-abstraction-survey",
    "cited_by_count": 12,
    "type": "article",
    "abstract": "A survey paper, not a poster or abstract.",
    "topics": ["High-performance computing"],
}


def _seed_classified(tmp_path, works):
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], works, base=tmp_path)


# --- poster_candidates ---------------------------------------------------

def test_finds_type_and_title_prefix_match(tmp_path):
    _seed_classified(tmp_path, [_POSTER_TYPE_AND_PREFIX, _REAL_PAPER])
    candidates = posters.poster_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    ids = {c["citing_id"] for c in candidates}
    assert ids == {"W_POSTER_1"}
    assert "title starts with" in candidates[0]["matched_reason"]


def test_title_prefix_alone_is_sufficient(tmp_path):
    _seed_classified(tmp_path, [_ABSTRACT_PREFIX_ONLY])
    candidates = posters.poster_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    ids = {c["citing_id"] for c in candidates}
    assert ids == {"W_ABSTRACT_1"}


def test_conference_abstract_type_alone_is_sufficient(tmp_path):
    _seed_classified(tmp_path, [_CONFERENCE_ABSTRACT_TYPE_ONLY])
    candidates = posters.poster_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    ids = {c["citing_id"] for c in candidates}
    assert ids == {"W_POSTER_2"}


def test_does_not_flag_real_paper(tmp_path):
    _seed_classified(tmp_path, [_REAL_PAPER])
    candidates = posters.poster_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert candidates == []


def test_does_not_flag_abstract_lookalike_title(tmp_path):
    _seed_classified(tmp_path, [_ABSTRACT_LOOKALIKE_TITLE])
    candidates = posters.poster_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert candidates == []


def test_multiple_candidates_sorted_by_id(tmp_path):
    _seed_classified(tmp_path, [_POSTER_TYPE_AND_PREFIX, _CONFERENCE_ABSTRACT_TYPE_ONLY, _ABSTRACT_PREFIX_ONLY])
    candidates = posters.poster_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    ids = [c["citing_id"] for c in candidates]
    assert ids == sorted(ids)
    assert set(ids) == {"W_POSTER_1", "W_POSTER_2", "W_ABSTRACT_1"}


def test_already_excluded_work_not_surfaced(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    _seed_classified(tmp_path, [_POSTER_TYPE_AND_PREFIX])
    exclude.exclude_work(seed_id, _POSTER_TYPE_AND_PREFIX["openalex_id"], reason="Already excluded.", base=tmp_path)

    candidates = posters.poster_candidates(seed_id, base=tmp_path)
    assert candidates == []


def test_kept_candidate_not_resurfaced(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    _seed_classified(tmp_path, [_POSTER_TYPE_AND_PREFIX])
    posters.keep_candidate(seed_id, _POSTER_TYPE_AND_PREFIX["openalex_id"], reason="Actually a real paper.", base=tmp_path)

    candidates = posters.poster_candidates(seed_id, base=tmp_path)
    assert candidates == []


# --- keep_candidate --------------------------------------------------------

def test_keep_candidate_requires_reason(tmp_path):
    with pytest.raises(ValueError, match="reason must not be empty"):
        posters.keep_candidate(PARALLEL_NETCDF_WORK["openalex_id"], "W1", reason="", base=tmp_path)


def test_keep_candidate_writes_entry(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    result = posters.keep_candidate(seed_id, "W1", reason="Real paper, not a poster.", base=tmp_path)
    assert result["ok"] is True
    p = posters._reviewed_path(seed_id, base=tmp_path)
    assert p.exists()
    assert "W1" in posters._kept_ids(seed_id, base=tmp_path)
