# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.report — offline."""
from __future__ import annotations

import pytest
from wake.report import build_metrics, render_markdown, _score, _venue_type_or_fallback
from wake.classify import RELATIONSHIP_STRENGTH
from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS


def _make_classified(works, relationships):
    result = []
    for w, rel in zip(works, relationships):
        result.append({
            **w,
            "relationship": rel,
            "confidence": 0.9,
            "justification": "Test",
            "has_abstract": bool(w.get("abstract")),
            "strength": RELATIONSHIP_STRENGTH.get(rel, 1),
        })
    return result


def test_build_metrics_totals():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["builds-on", "uses-as-tool", "background-mention"],
    )
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    assert metrics["total_citing_works"] == 3
    assert metrics["by_relationship"]["builds-on"] == 1
    assert metrics["by_relationship"]["uses-as-tool"] == 1
    assert metrics["by_relationship"]["background-mention"] == 1


def test_build_metrics_highly_cited():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "applies-to-domain", "background-mention"],
    )
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    assert metrics["highly_cited_citing"] == 1


def test_build_metrics_no_abstract():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    assert metrics["no_abstract_count"] == 1


def test_build_metrics_by_year():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["builds-on", "uses-as-tool", "background-mention"],
    )
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    years = {e["year"] for e in metrics["by_year"]}
    assert 2005 in years
    assert 2008 in years
    assert 2010 in years


def test_top_evidence_sorted():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    top = metrics["top_evidence"]
    assert top[0]["relationship"] == "extends"
    scores = [e["score"] for e in top]
    assert scores == sorted(scores, reverse=True)


def test_render_markdown_contains_sections():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    seed = {**PARALLEL_NETCDF_WORK, "description": "This paper contributes PnetCDF."}
    metrics = build_metrics(seed, classified)
    md = render_markdown(seed, metrics)
    assert "# Impact Brief" in md
    assert "## The Contribution" in md
    assert "## Reach" in md
    assert "## Nature of Impact" in md
    assert "## Strongest Evidence" in md
    assert "PnetCDF" in md


def test_score_higher_for_stronger_relationship():
    w_extends = {"cited_by_count": 100, "strength": RELATIONSHIP_STRENGTH["extends"]}
    w_mention = {"cited_by_count": 100, "strength": RELATIONSHIP_STRENGTH["background-mention"]}
    assert _score(w_extends) > _score(w_mention)


def test_score_higher_for_more_cited():
    w_cited = {"cited_by_count": 1000, "strength": 4}
    w_few = {"cited_by_count": 1, "strength": 4}
    assert _score(w_cited) > _score(w_few)


def test_build_metrics_partial_coverage():
    """Reach metrics use the full citing set; relationship stats only the classified subset."""
    classified_first = {
        **SAMPLE_CITING_WORKS[0],
        "relationship": "extends",
        "confidence": 0.9,
        "justification": "Test",
        "has_abstract": True,
        "strength": RELATIONSHIP_STRENGTH["extends"],
    }
    mixed = [classified_first, SAMPLE_CITING_WORKS[1], SAMPLE_CITING_WORKS[2]]
    metrics = build_metrics(PARALLEL_NETCDF_WORK, mixed)

    assert metrics["total_citing_works"] == 3
    assert metrics["classified_count"] == 1
    assert metrics["coverage"] == pytest.approx(1 / 3, abs=1e-3)
    assert sum(metrics["by_relationship"].values()) == 1


def test_render_markdown_notes_partial_coverage():
    classified_first = {
        **SAMPLE_CITING_WORKS[0],
        "relationship": "extends",
        "confidence": 0.9,
        "justification": "Test",
        "has_abstract": True,
        "strength": RELATIONSHIP_STRENGTH["extends"],
    }
    mixed = [classified_first, SAMPLE_CITING_WORKS[1], SAMPLE_CITING_WORKS[2]]
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, mixed)
    md = render_markdown(seed, metrics)
    assert "Partial analysis" in md


def test_render_markdown_full_coverage_no_partial_note():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = render_markdown(seed, metrics)
    assert "Partial analysis" not in md


def test_venue_type_or_fallback_uses_venue_type_when_present():
    work = {"venue_type": "journal", "type": "conference-paper"}
    assert _venue_type_or_fallback(work) == "journal"


def test_venue_type_or_fallback_maps_conference_paper():
    work = {"venue_type": None, "type": "conference-paper"}
    assert _venue_type_or_fallback(work) == "conference"


def test_venue_type_or_fallback_maps_article_to_journal():
    work = {"venue_type": None, "type": "article"}
    assert _venue_type_or_fallback(work) == "journal"


def test_venue_type_or_fallback_maps_dissertation_to_thesis():
    work = {"venue_type": None, "type": "dissertation"}
    assert _venue_type_or_fallback(work) == "thesis"


def test_venue_type_or_fallback_unmapped_type_is_unknown():
    work = {"venue_type": None, "type": "some-new-openalex-type"}
    assert _venue_type_or_fallback(work) == "unknown"


def test_venue_type_or_fallback_no_type_at_all_is_unknown():
    assert _venue_type_or_fallback({}) == "unknown"


def test_build_metrics_venue_type_fallback_reduces_unknown_bucket():
    works = [
        {**SAMPLE_CITING_WORKS[0], "venue_type": None, "type": "conference-paper"},
        {**SAMPLE_CITING_WORKS[1], "venue_type": None, "type": "article"},
        {**SAMPLE_CITING_WORKS[2], "venue_type": None, "type": None},
    ]
    metrics = build_metrics(PARALLEL_NETCDF_WORK, works)
    by_vt = metrics["by_venue_type"]
    assert by_vt.get("conference") == 1
    assert by_vt.get("journal") == 1
    assert by_vt.get("unknown") == 1
