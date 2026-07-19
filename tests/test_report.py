# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.report — offline."""
from __future__ import annotations

import pytest
from wake.report import build_metrics, render_markdown, _score, _venue_type_or_fallback
from wake.classify import RELATIONSHIP_STRENGTH
from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS


def _make_classified(works, relationships, verification_status="provisional"):
    result = []
    for w, rel in zip(works, relationships):
        result.append({
            **w,
            "relationship": rel,
            "confidence": 0.9,
            "justification": "Test",
            "has_abstract": bool(w.get("abstract")),
            "strength": RELATIONSHIP_STRENGTH.get(rel, 1),
            "verification_status": verification_status,
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
        "verification_status": "provisional",
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
        "verification_status": "provisional",
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


# ---- Verification lifecycle: provisional -> proposed -> verified ----

def test_build_metrics_all_provisional_by_default():
    """classify.py always stamps verification_status='provisional' -- this
    is the default state for every classification, not just ones that
    later go through wake evidence."""
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    assert metrics["verified_count"] == 0
    assert metrics["classified_count"] == 3


def test_build_metrics_counts_verified_works():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    # Promote one work to verified, as add_override() would.
    classified[0]["verification_status"] = "verified"
    classified[0]["verification_source"] = "evidence-dossier"

    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    assert metrics["verified_count"] == 1


def test_top_evidence_carries_verification_fields():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    classified[0]["verification_status"] = "verified"
    classified[0]["verification_source"] = "evidence-dossier"

    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    top = metrics["top_evidence"]
    verified_entries = [e for e in top if e["verification_status"] == "verified"]
    assert len(verified_entries) == 1
    assert verified_entries[0]["verification_source"] == "evidence-dossier"


def test_render_markdown_shows_provisional_tag_by_default():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = render_markdown(seed, metrics)
    assert "[PROVISIONAL" in md
    assert "provisional" in md.lower()


def test_render_markdown_shows_verified_via_evidence_dossier():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    classified[0]["verification_status"] = "verified"
    classified[0]["verification_source"] = "evidence-dossier"
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = render_markdown(seed, metrics)
    assert "[VERIFIED via full-text reading]" in md


def test_render_markdown_shows_verified_via_human_judgment():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    classified[0]["verification_status"] = "verified"
    classified[0]["verification_source"] = "human-judgment"
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = render_markdown(seed, metrics)
    assert "[VERIFIED via human judgment]" in md


def test_render_markdown_nature_of_impact_summary_counts():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    classified[0]["verification_status"] = "verified"
    classified[0]["verification_source"] = "evidence-dossier"
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = render_markdown(seed, metrics)
    assert "2 classification(s) are **provisional**" in md
    assert "1 have been **verified**" in md


def test_add_override_defaults_to_human_judgment_source():
    from wake.report import add_override
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        entry = add_override(
            "W123", "W456", relationship="extends", justification="test", base=Path(tmp),
        )
    assert entry["verification_status"] == "verified"
    assert entry["verification_source"] == "human-judgment"


def test_add_override_accepts_evidence_dossier_source():
    from wake.report import add_override
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        entry = add_override(
            "W123", "W456", relationship="extends", justification="quoted text",
            verification_source="evidence-dossier", base=Path(tmp),
        )
    assert entry["verification_status"] == "verified"
    assert entry["verification_source"] == "evidence-dossier"
