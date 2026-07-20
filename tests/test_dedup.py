# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.dedup — duplicate citing-work detection and
human-confirmed merging (BACKLOG Theme J item 8), offline.

Fixture pair modeled directly on the two real preprint/published pairs
caught by hand this session (GMDD preprint W4229646607 vs. published
W2137705743, and W4251231835 vs. W2153325196) -- same shape: identical
or near-identical title, overlapping authors, one side with no venue
(preprint) and the other with a real journal venue.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wake import dedup
from wake.classify import save_classified
from wake.report import add_override
from .conftest import PARALLEL_NETCDF_WORK


_PREPRINT = {
    "openalex_id": "W_PREPRINT",
    "title": "An approach to enhance pnetCDF performance in environmental modeling applications",
    "authors": ["Alice Smith", "Bob Jones"],
    "author_ids": ["A1000000001", "A1000000002"],
    "year": 2014,
    "venue": None,
    "venue_type": None,
    "doi": "10.5194/fake-preprint-2014",
    "cited_by_count": 3,
    "type": "preprint",
    "abstract": "A preprint about pnetCDF performance.",
    "topics": ["High-performance computing"],
}

_PUBLISHED = {
    "openalex_id": "W_PUBLISHED",
    "title": "An approach to enhance pnetCDF performance in environmental modeling applications",
    "authors": ["Alice Smith", "Bob Jones"],
    "author_ids": ["A1000000001", "A1000000002"],
    "year": 2015,
    "venue": "Geoscientific Model Development",
    "venue_type": "journal",
    "doi": "10.5194/gmd-8-fake-2015",
    "cited_by_count": 20,
    "type": "article",
    "abstract": "The published version of the same work.",
    "topics": ["High-performance computing"],
}

_UNRELATED = {
    "openalex_id": "W_UNRELATED",
    "title": "A Totally Different Paper About Something Else Entirely",
    "authors": ["Carol Davis"],
    "author_ids": ["A1000000003"],
    "year": 2016,
    "venue": "Journal of Unrelated Things",
    "venue_type": "journal",
    "doi": "10.1000/unrelated",
    "cited_by_count": 5,
    "type": "article",
    "abstract": "Nothing to do with the other two.",
    "topics": ["Unrelated field"],
}

# Same title/venue shape as the preprint/published pair, but no shared
# author IDs -- title similarity alone must not be enough to flag a pair.
_SAME_TITLE_DIFFERENT_AUTHORS = {
    "openalex_id": "W_SAME_TITLE_OTHER_AUTHORS",
    "title": "An approach to enhance pnetCDF performance in environmental modeling applications",
    "authors": ["Zoe Nobody"],
    "author_ids": ["A1000000099"],
    "year": 2020,
    "venue": "Some Other Journal",
    "venue_type": "journal",
    "doi": "10.1000/coincidence",
    "cited_by_count": 1,
    "type": "article",
    "abstract": "A coincidentally similar title by unrelated authors.",
    "topics": ["High-performance computing"],
}


def _seed_classified(tmp_path, works):
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], works, base=tmp_path)


# --- dedup_candidates --------------------------------------------------

def test_dedup_candidates_finds_preprint_published_pair(tmp_path):
    _seed_classified(tmp_path, [_PREPRINT, _PUBLISHED])
    candidates = dedup.dedup_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert len(candidates) == 1
    c = candidates[0]
    assert {c["citing_id_a"], c["citing_id_b"]} == {"W_PREPRINT", "W_PUBLISHED"}
    assert c["likely_kind"] == "preprint-vs-published"
    assert c["title_similarity"] > 0.95
    assert "Alice Smith" in c["overlapping_authors"]


def test_dedup_candidates_requires_author_overlap_not_just_title(tmp_path):
    """Same title, no shared authors -- must not be flagged."""
    _seed_classified(tmp_path, [_PREPRINT, _SAME_TITLE_DIFFERENT_AUTHORS])
    candidates = dedup.dedup_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert candidates == []


def test_dedup_candidates_ignores_unrelated_works(tmp_path):
    _seed_classified(tmp_path, [_PREPRINT, _PUBLISHED, _UNRELATED])
    candidates = dedup.dedup_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert len(candidates) == 1  # only the preprint/published pair


def test_dedup_candidates_labels_double_publication_without_preprint_signal(tmp_path):
    """Two full journal venues, same title/authors -- no preprint signal
    on either side, so likely_kind should be the double-publication
    label, not preprint-vs-published."""
    a = {**_PUBLISHED, "openalex_id": "W_JOURNAL_A"}
    b = {**_PUBLISHED, "openalex_id": "W_JOURNAL_B", "venue": "A Different Journal"}
    _seed_classified(tmp_path, [a, b])
    candidates = dedup.dedup_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert len(candidates) == 1
    assert candidates[0]["likely_kind"] == "possible-double-publication"


def test_dedup_candidates_respects_min_title_similarity(tmp_path):
    _seed_classified(tmp_path, [_PREPRINT, _PUBLISHED])
    candidates = dedup.dedup_candidates(
        PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path, min_title_similarity=0.999,
    )
    # Titles are identical here so this should still match; use a
    # deliberately unreachable threshold to confirm the parameter is honored.
    candidates_impossible = dedup.dedup_candidates(
        PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path, min_title_similarity=1.01,
    )
    assert candidates_impossible == []


def test_dedup_candidates_excludes_confirmed_pairs(tmp_path):
    _seed_classified(tmp_path, [_PREPRINT, _PUBLISHED])
    dedup.confirm_duplicate(
        PARALLEL_NETCDF_WORK["openalex_id"], "W_PREPRINT", "W_PUBLISHED", base=tmp_path,
    )
    candidates = dedup.dedup_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert candidates == []


def test_dedup_candidates_excludes_rejected_pairs(tmp_path):
    _seed_classified(tmp_path, [_PREPRINT, _PUBLISHED])
    dedup.reject_candidate(
        PARALLEL_NETCDF_WORK["openalex_id"], "W_PREPRINT", "W_PUBLISHED", base=tmp_path,
    )
    candidates = dedup.dedup_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert candidates == []


def test_dedup_candidates_sorted_highest_similarity_first(tmp_path):
    close_match = {**_SAME_TITLE_DIFFERENT_AUTHORS, "openalex_id": "W_CLOSE",
                    "author_ids": _PREPRINT["author_ids"], "authors": _PREPRINT["authors"],
                    "title": _PREPRINT["title"] + " (extended)"}
    _seed_classified(tmp_path, [_PREPRINT, _PUBLISHED, close_match])
    candidates = dedup.dedup_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    sims = [c["title_similarity"] for c in candidates]
    assert sims == sorted(sims, reverse=True)


# --- confirm_duplicate / reject_candidate -------------------------------

def test_confirm_duplicate_writes_entry(tmp_path):
    result = dedup.confirm_duplicate(
        PARALLEL_NETCDF_WORK["openalex_id"], "W_PREPRINT", "W_PUBLISHED",
        reason="Same paper, preprint vs. published.", base=tmp_path,
    )
    assert result["ok"] is True
    duplicates = dedup.load_duplicates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert duplicates["W_PREPRINT"]["canonical_id"] == "W_PUBLISHED"


def test_confirm_duplicate_rejects_self_duplicate(tmp_path):
    with pytest.raises(ValueError, match="must be different works"):
        dedup.confirm_duplicate(
            PARALLEL_NETCDF_WORK["openalex_id"], "W_SAME", "W_SAME", base=tmp_path,
        )


def test_confirm_duplicate_rejects_chaining(tmp_path):
    dedup.confirm_duplicate(
        PARALLEL_NETCDF_WORK["openalex_id"], "W_A", "W_B", base=tmp_path,
    )
    with pytest.raises(ValueError, match="already recorded as a duplicate"):
        dedup.confirm_duplicate(
            PARALLEL_NETCDF_WORK["openalex_id"], "W_C", "W_A", base=tmp_path,
        )


def test_canonical_id_for_resolves_duplicate(tmp_path):
    dedup.confirm_duplicate(
        PARALLEL_NETCDF_WORK["openalex_id"], "W_PREPRINT", "W_PUBLISHED", base=tmp_path,
    )
    duplicates = dedup.load_duplicates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert dedup.canonical_id_for("W_PREPRINT", duplicates) == "W_PUBLISHED"
    assert dedup.canonical_id_for("W_PUBLISHED", duplicates) == "W_PUBLISHED"
    assert dedup.canonical_id_for("W_OTHER", duplicates) == "W_OTHER"


def test_reject_candidate_writes_entry_and_excludes_from_future_scans(tmp_path):
    _seed_classified(tmp_path, [_PREPRINT, _PUBLISHED])
    result = dedup.reject_candidate(
        PARALLEL_NETCDF_WORK["openalex_id"], "W_PREPRINT", "W_PUBLISHED",
        reason="Actually two distinct papers.", base=tmp_path,
    )
    assert result["ok"] is True
    candidates = dedup.dedup_candidates(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert candidates == []


def test_reject_candidate_rejects_self_pair(tmp_path):
    with pytest.raises(ValueError, match="must be different works"):
        dedup.reject_candidate(
            PARALLEL_NETCDF_WORK["openalex_id"], "W_SAME", "W_SAME", base=tmp_path,
        )


# --- downstream exclusion: bake / theme / narrative ---------------------

def test_bake_excludes_confirmed_duplicate_from_reach_metrics(tmp_path):
    from wake.report import bake_and_save

    works = [
        {**_PREPRINT, "relationship": "uses-as-tool", "confidence": 0.9,
         "justification": "j", "has_abstract": True, "strength": 5,
         "verification_status": "provisional"},
        {**_PUBLISHED, "relationship": "uses-as-tool", "confidence": 0.9,
         "justification": "j", "has_abstract": True, "strength": 5,
         "verification_status": "provisional"},
    ]
    dedup.confirm_duplicate(
        PARALLEL_NETCDF_WORK["openalex_id"], "W_PREPRINT", "W_PUBLISHED", base=tmp_path,
    )
    json_path, md_path = bake_and_save(PARALLEL_NETCDF_WORK, works, base=tmp_path, verbose=False)
    metrics = json.loads(json_path.read_text())
    assert metrics["total_citing_works"] == 1


def test_theme_create_refuses_confirmed_duplicate(tmp_path):
    from wake import themes

    _seed_classified(tmp_path, [_PREPRINT, _PUBLISHED])
    dedup.confirm_duplicate(
        PARALLEL_NETCDF_WORK["openalex_id"], "W_PREPRINT", "W_PUBLISHED", base=tmp_path,
    )
    with pytest.raises(ValueError, match="confirmed duplicate"):
        themes.create_theme(
            PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
            citing_ids=["W_PREPRINT"], base=tmp_path,
        )


def test_narrative_section_refuses_confirmed_duplicate_ref(tmp_path):
    """Realistic scenario: both the preprint and the published version
    were independently full-text-verified before a human noticed they
    were the same paper and confirmed the duplicate. A narrative section
    citing the (now-superseded) preprint ID should be refused and
    redirected to the canonical, even though the preprint ID is itself
    still human-verified."""
    from wake import evidence, narrative
    import shutil
    from unittest.mock import patch

    _seed_classified(tmp_path, [_PREPRINT, _PUBLISHED])
    fixture = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"
    fake_response = {
        "relationship": "extends", "confidence": 0.9, "justification": "j",
        "agrees_with_provisional": False,
        "quotes": [{"page": 2, "text": "We directly extend the seed's method here.", "note": "x"}],
    }
    for work in (_PREPRINT, _PUBLISHED):
        dest = tmp_path / "pdfs" / f"{work['openalex_id']}.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(fixture, dest)
        with patch("wake.evidence.fetch_pdf", return_value={"ok": True, "path": str(dest), "source": "osti"}), \
             patch("wake.evidence.chat_json", return_value=fake_response):
            evidence.build_dossier(PARALLEL_NETCDF_WORK, work, base=tmp_path, verbose=False)
        add_override(
            PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"],
            relationship="extends", justification="accepted", base=tmp_path,
            verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
        )

    dedup.confirm_duplicate(
        PARALLEL_NETCDF_WORK["openalex_id"], "W_PREPRINT", "W_PUBLISHED", base=tmp_path,
    )

    with pytest.raises(ValueError, match="confirmed duplicate"):
        narrative.create_section(
            PARALLEL_NETCDF_WORK, "s1", title="S",
            prose="Some claim. [ref:W_PREPRINT]", base=tmp_path,
        )
