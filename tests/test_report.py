# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.report — offline."""
from __future__ import annotations

import pytest
from wake.report import build_metrics, bake_markdown, relationship_score, _score, _venue_type_or_fallback
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
            # Deliberately no "strength" field -- see
            # test_score_ignores_legacy_strength_field below: _score()
            # must always recompute from the relationship label, never
            # from a stored value, so this fixture matches what
            # classify_one() actually produces now.
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


def test_bake_markdown_contains_sections():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    seed = {**PARALLEL_NETCDF_WORK, "description": "This paper contributes PnetCDF."}
    metrics = build_metrics(seed, classified)
    md = bake_markdown(seed, metrics)
    assert "# Impact Brief" in md
    assert "## The Contribution" in md
    assert "## Reach" in md
    assert "## Nature of Impact" in md
    assert "## Strongest Evidence" in md
    assert "PnetCDF" in md


def test_bake_markdown_has_okf_frontmatter():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    md = bake_markdown(PARALLEL_NETCDF_WORK, metrics)
    assert md.startswith("---\n")
    assert "type: impact-brief" in md
    assert f'seed_openalex_id: {PARALLEL_NETCDF_WORK["openalex_id"]}' in md
    assert f"seed_doi: {PARALLEL_NETCDF_WORK['doi']}" in md
    assert f"seed_year: {PARALLEL_NETCDF_WORK['year']}" in md
    assert "citing_count: 3" in md
    assert "themes_confirmed: 0" in md
    assert "themes_draft: 0" in md
    assert "narrative_status: none" in md
    assert "seed_pdf_status: not-attempted" in md
    # frontmatter closes before the H1
    frontmatter, _, rest = md.partition("---\n")[2].partition("\n---\n")
    assert rest.lstrip().startswith("# Impact Brief")


def test_bake_markdown_seed_pdf_status_reflects_seed_json(tmp_path):
    from wake.io import atomic_write_json
    from wake.seed import work_dir

    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    wd = work_dir(seed_id, base=tmp_path)
    wd.mkdir(parents=True)
    atomic_write_json(wd / "seed.json", {
        "openalex_id": seed_id, "title": "x",
        "seed_pdf": {"path": None, "tried": ["osti"], "fallback_links": {}},
    })

    classified = _make_classified(SAMPLE_CITING_WORKS, ["extends", "uses-as-tool", "background-mention"])
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    md = bake_markdown(PARALLEL_NETCDF_WORK, metrics, base=tmp_path)
    assert "seed_pdf_status: attempted-failed" in md

    (wd / "seed.pdf").write_bytes(b"%PDF-1.4 fake")
    md = bake_markdown(PARALLEL_NETCDF_WORK, metrics, base=tmp_path)
    assert "seed_pdf_status: cached" in md


def test_bake_markdown_no_nav_line_without_base():
    classified = _make_classified(SAMPLE_CITING_WORKS, ["extends", "uses-as-tool", "background-mention"])
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    md = bake_markdown(PARALLEL_NETCDF_WORK, metrics)
    assert "See also:" not in md


def test_bake_markdown_nav_line_reflects_existing_wiki_artifacts(tmp_path):
    import shutil
    from pathlib import Path as _Path
    from unittest.mock import patch
    from wake import evidence, narrative, themes
    from wake.classify import save_classified
    from wake.report import add_override

    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = SAMPLE_CITING_WORKS[0]
    save_classified(seed_id, [{**work, "relationship": "extends", "confidence": 0.9, "justification": "x"}], base=tmp_path)

    fixture = _Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"
    dest = tmp_path / "pdfs" / "citing.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(fixture, dest)
    fake_response = {
        "relationship": "extends", "confidence": 0.9, "justification": "j",
        "agrees_with_provisional": False,
        "quotes": [{"page": 1, "text": "Directly extends the seed.", "note": ""}],
    }
    with patch("wake.evidence.fetch_pdf", return_value={"ok": True, "path": str(dest), "source": "osti"}), \
         patch("wake.evidence.chat_json", return_value=fake_response):
        evidence.build_dossier(PARALLEL_NETCDF_WORK, work, base=tmp_path, verbose=False)

    add_override(
        seed_id, work["openalex_id"], relationship="extends", justification="ok",
        verification_source="evidence-dossier", base=tmp_path,
    )
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[work["openalex_id"]], base=tmp_path,
    )
    narrative.create_outline(
        PARALLEL_NETCDF_WORK, components=[{"slug": "intro", "title": "Intro", "kind": "free"}], base=tmp_path,
    )
    narrative.create_section(PARALLEL_NETCDF_WORK, "intro", title="Intro", prose="Framing.", base=tmp_path)
    narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)

    classified = _make_classified(SAMPLE_CITING_WORKS, ["extends", "uses-as-tool", "background-mention"])
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    md = bake_markdown(PARALLEL_NETCDF_WORK, metrics, base=tmp_path)
    assert "themes_confirmed: 0" in md
    assert "themes_draft: 1" in md
    assert "narrative_status: assembled" in md
    assert "See also:" in md
    assert "[full evidence wiki](evidence/index.md)" in md
    assert "[themes](evidence/themes/index.md)" in md
    assert "[narrative](narrative.md)" in md


def test_bake_markdown_nav_line_reflects_cwd_wiki_artifacts_without_explicit_base(tmp_path, monkeypatch):
    """Regression test: bake_markdown() must resolve wiki-navigation
    state (themes/narrative/evidence existence) the same way every other
    wake-out/<seed>/ path resolves it -- explicit base, else
    WAKE_WORK_DIR, else cwd (see seed.work_dir()) -- not by treating
    base=None as "nothing exists yet". `wake bake` with no --work-dir
    flag (the common case) calls bake_and_save()/bake_markdown() with
    base=None, relying on cwd resolution; a prior bug gated the entire
    themes/narrative/evidence-dossier-link block on `base is not None`,
    which silently dropped the "See also" nav line, the frontmatter's
    themes_confirmed/narrative_status fields, and Strongest Evidence's
    dossier links whenever wake was invoked without --work-dir, even
    though the wiki artifacts were sitting right there in cwd."""
    import shutil
    from pathlib import Path as _Path
    from unittest.mock import patch
    from wake import evidence, narrative, themes
    from wake.classify import save_classified
    from wake.report import add_override, bake_and_save

    monkeypatch.chdir(tmp_path)

    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = SAMPLE_CITING_WORKS[0]
    classified = [{**work, "relationship": "extends", "confidence": 0.9, "justification": "x"}]
    save_classified(seed_id, classified)

    fixture = _Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"
    dest = tmp_path / "wake-out" / seed_id / "pdfs" / "citing.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(fixture, dest)
    fake_response = {
        "relationship": "extends", "confidence": 0.9, "justification": "j",
        "agrees_with_provisional": False,
        "quotes": [{"page": 1, "text": "Directly extends the seed.", "note": ""}],
    }
    with patch("wake.evidence.fetch_pdf", return_value={"ok": True, "path": str(dest), "source": "osti"}), \
         patch("wake.evidence.chat_json", return_value=fake_response):
        evidence.build_dossier(PARALLEL_NETCDF_WORK, work, verbose=False)

    add_override(
        seed_id, work["openalex_id"], relationship="extends", justification="ok",
        verification_source="evidence-dossier",
    )
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[work["openalex_id"]],
    )
    narrative.create_outline(
        PARALLEL_NETCDF_WORK, components=[{"slug": "intro", "title": "Intro", "kind": "free"}],
    )
    narrative.create_section(PARALLEL_NETCDF_WORK, "intro", title="Intro", prose="Framing.")
    narrative.stitch(PARALLEL_NETCDF_WORK)

    json_path, md_path = bake_and_save(PARALLEL_NETCDF_WORK, classified, verbose=False)
    md = md_path.read_text()

    assert "themes_draft: 1" in md
    assert "narrative_status: assembled" in md
    assert "See also:" in md
    assert "[full evidence wiki](evidence/index.md)" in md
    assert "[themes](evidence/themes/index.md)" in md
    assert "[narrative](narrative.md)" in md
    assert f"[{work['title']}](evidence/{work['openalex_id']}.md)" in md


def test_score_higher_for_stronger_relationship():
    w_extends = {"cited_by_count": 100, "relationship": "extends"}
    w_mention = {"cited_by_count": 100, "relationship": "background-mention"}
    assert _score(w_extends) > _score(w_mention)


def test_score_higher_for_more_cited():
    w_cited = {"cited_by_count": 1000, "relationship": "benchmarks"}
    w_few = {"cited_by_count": 1, "relationship": "benchmarks"}
    assert _score(w_cited) > _score(w_few)


def test_score_ignores_legacy_strength_field():
    """A pre-existing sidecar/override from before this change may still
    carry a stale "strength" field on disk -- _score() must not let it
    win over the label-derived, config-driven score. Deliberately sets a
    bogus strength that would flip the comparison if honored."""
    w_extends = {"cited_by_count": 100, "relationship": "extends", "strength": 1}
    w_mention = {"cited_by_count": 100, "relationship": "background-mention", "strength": 999}
    assert _score(w_extends) > _score(w_mention)


def test_relationship_score_reranks_when_config_strength_changes(monkeypatch):
    """The concrete 'rerank without reanalysis' workflow: editing
    classify.relationship_strength and recomputing (no LLM, no
    reclassification) changes the ranking."""
    assert relationship_score("extends", 10) > relationship_score("applies-to-domain", 10)

    monkeypatch.setattr(
        "wake.classify.config.classify_cfg",
        lambda: {"relationship_strength": {
            "extends": 1, "builds-on": 2, "uses-as-tool": 3, "benchmarks": 4,
            "applies-to-domain": 9, "related-infrastructure": 5, "background-mention": 1,
        }},
    )
    assert relationship_score("applies-to-domain", 10) > relationship_score("extends", 10)


# --- multi-facet scoring (MAX across facets) ------------------------------

def test_relationship_score_multi_facet_uses_max_strength():
    """A work with facets ["uses-as-tool", "applies-to-domain"] scores by
    whichever facet's configured strength is highest (MAX, not sum or
    average -- see Q1 of the multi-facet design discussion)."""
    facets = [{"label": "uses-as-tool"}, {"label": "applies-to-domain"}]
    single_stronger = relationship_score("uses-as-tool", 10)  # uses-as-tool has higher default strength
    assert relationship_score(facets, 10) == single_stronger


def test_relationship_score_multi_facet_does_not_exceed_its_strongest_single_facet():
    """MAX means a second (weaker) facet never inflates the score beyond
    what the strongest facet alone would produce."""
    weak_facets = [{"label": "background-mention"}, {"label": "related-infrastructure"}]
    assert relationship_score(weak_facets, 10) == relationship_score("related-infrastructure", 10)


def test_score_prefers_relationships_list_over_legacy_scalar():
    work = {
        "cited_by_count": 10,
        "relationship": "background-mention",  # legacy scalar, should be ignored
        "relationships": [{"label": "extends"}],
    }
    assert _score(work) == relationship_score("extends", 10)


def test_score_falls_back_to_legacy_scalar_when_no_relationships_list():
    work = {"cited_by_count": 10, "relationship": "extends"}
    assert _score(work) == relationship_score("extends", 10)


# --- by_relationship counts every facet -----------------------------------

def test_build_metrics_by_relationship_counts_every_facet():
    """A work with two facets increments both rows -- rows can therefore
    sum to more than classified_count (see Q2 of the multi-facet design
    discussion)."""
    classified = [{
        **SAMPLE_CITING_WORKS[0],
        "relationship": "uses-as-tool",
        "relationships": [{"label": "uses-as-tool"}, {"label": "applies-to-domain"}],
        "confidence": 0.9, "justification": "x", "has_abstract": True,
        "verification_status": "provisional",
    }]
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    assert metrics["classified_count"] == 1
    assert metrics["by_relationship"]["uses-as-tool"] == 1
    assert metrics["by_relationship"]["applies-to-domain"] == 1
    assert sum(metrics["by_relationship"].values()) == 2


def test_build_metrics_by_relationship_single_facet_work_counts_once():
    classified = _make_classified(SAMPLE_CITING_WORKS[:1], ["extends"])
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    assert sum(metrics["by_relationship"].values()) == 1


def test_bake_markdown_footnotes_relationship_table_when_facets_overlap(tmp_path):
    classified = [{
        **SAMPLE_CITING_WORKS[0],
        "relationship": "uses-as-tool",
        "relationships": [{"label": "uses-as-tool"}, {"label": "applies-to-domain"}],
        "confidence": 0.9, "justification": "x", "has_abstract": True,
        "verification_status": "provisional",
    }]
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    md = bake_markdown(PARALLEL_NETCDF_WORK, metrics, base=tmp_path)
    assert "Rows may sum to more than the total classified count" in md


def test_bake_markdown_no_footnote_when_all_single_facet(tmp_path):
    classified = _make_classified(SAMPLE_CITING_WORKS, ["extends", "uses-as-tool", "background-mention"])
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    md = bake_markdown(PARALLEL_NETCDF_WORK, metrics, base=tmp_path)
    assert "Rows may sum to more than the total classified count" not in md


def test_bake_markdown_strongest_evidence_shows_every_facet(tmp_path):
    classified = [{
        **SAMPLE_CITING_WORKS[0],
        "relationship": "uses-as-tool",
        "confidence": 0.95,
        "relationships": [
            {"label": "uses-as-tool", "confidence": 0.95},
            {"label": "applies-to-domain", "confidence": 0.8},
        ],
        "justification": "Uses PnetCDF and applies it to flood modeling.",
        "has_abstract": True,
        "verification_status": "provisional",
    }]
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    md = bake_markdown(PARALLEL_NETCDF_WORK, metrics, base=tmp_path)
    assert "*uses-as-tool*" in md
    assert "*applies-to-domain*" in md


def test_build_metrics_partial_coverage():
    """Reach metrics use the full citing set; relationship stats only the classified subset."""
    classified_first = {
        **SAMPLE_CITING_WORKS[0],
        "relationship": "extends",
        "confidence": 0.9,
        "justification": "Test",
        "has_abstract": True,
        "verification_status": "provisional",
    }
    mixed = [classified_first, SAMPLE_CITING_WORKS[1], SAMPLE_CITING_WORKS[2]]
    metrics = build_metrics(PARALLEL_NETCDF_WORK, mixed)

    assert metrics["total_citing_works"] == 3
    assert metrics["classified_count"] == 1
    assert metrics["coverage"] == pytest.approx(1 / 3, abs=1e-3)
    assert sum(metrics["by_relationship"].values()) == 1


def test_bake_markdown_notes_partial_coverage():
    classified_first = {
        **SAMPLE_CITING_WORKS[0],
        "relationship": "extends",
        "confidence": 0.9,
        "justification": "Test",
        "has_abstract": True,
        "verification_status": "provisional",
    }
    mixed = [classified_first, SAMPLE_CITING_WORKS[1], SAMPLE_CITING_WORKS[2]]
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, mixed)
    md = bake_markdown(seed, metrics)
    assert "Partial analysis" in md


def test_bake_markdown_full_coverage_no_partial_note():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = bake_markdown(seed, metrics)
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


def test_build_metrics_no_self_extension_by_default():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    assert metrics["self_extension_count"] == 0


def test_build_metrics_counts_self_extension():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    classified[0]["author_overlap"] = True
    classified[0]["overlapping_authors"] = ["Jianwei Li"]

    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    assert metrics["self_extension_count"] == 1


def test_top_evidence_carries_author_overlap_fields():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    classified[0]["author_overlap"] = True
    classified[0]["overlapping_authors"] = ["Jianwei Li"]

    metrics = build_metrics(PARALLEL_NETCDF_WORK, classified)
    top = metrics["top_evidence"]
    overlap_entries = [e for e in top if e["author_overlap"]]
    assert len(overlap_entries) == 1
    assert overlap_entries[0]["overlapping_authors"] == ["Jianwei Li"]

    non_overlap_entries = [e for e in top if not e["author_overlap"]]
    assert all(e["overlapping_authors"] == [] for e in non_overlap_entries)


def test_bake_markdown_shows_provisional_tag_by_default():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = bake_markdown(seed, metrics)
    assert "[PROVISIONAL" in md
    assert "provisional" in md.lower()


def test_bake_markdown_shows_verified_via_evidence_dossier():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    classified[0]["verification_status"] = "verified"
    classified[0]["verification_source"] = "evidence-dossier"
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = bake_markdown(seed, metrics)
    assert "[VERIFIED via full-text reading]" in md


def test_bake_markdown_top_evidence_doi_and_openalex_both_linked():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = bake_markdown(seed, metrics)
    top = metrics["top_evidence"][0]
    assert f"DOI: [{top['doi']}](https://doi.org/{top['doi']})" in md
    assert f"OpenAlex: [{top['openalex_id']}](https://openalex.org/{top['openalex_id']})" in md


def test_bake_markdown_top_evidence_no_doi_still_shows_openalex_link():
    works = [{**SAMPLE_CITING_WORKS[0], "doi": None}, SAMPLE_CITING_WORKS[1], SAMPLE_CITING_WORKS[2]]
    classified = _make_classified(works, ["extends", "uses-as-tool", "background-mention"])
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = bake_markdown(seed, metrics)
    top = metrics["top_evidence"][0]
    assert top["doi"] is None
    top_entry_start = md.index(f"**1. {top['title']}**")
    top_entry_end = md.index("\n\n", top_entry_start)
    top_entry = md[top_entry_start:top_entry_end]
    assert "DOI:" not in top_entry
    assert f"OpenAlex: [{top['openalex_id']}](https://openalex.org/{top['openalex_id']})" in top_entry


def test_bake_markdown_top_evidence_title_plain_when_no_dossier(tmp_path):
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = bake_markdown(seed, metrics, base=tmp_path)
    top = metrics["top_evidence"][0]
    assert f"**1. {top['title']}**" in md
    assert f"[{top['title']}]" not in md


def test_bake_markdown_top_evidence_title_links_to_dossier_when_present(tmp_path):
    from wake.evidence import dossier_path

    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    top = metrics["top_evidence"][0]

    p = dossier_path(seed["openalex_id"], top["openalex_id"], base=tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("stub dossier")

    md = bake_markdown(seed, metrics, base=tmp_path)
    assert f"**1. [{top['title']}](evidence/{top['openalex_id']}.md)**" in md


def test_bake_markdown_shows_verified_via_human_judgment():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    classified[0]["verification_status"] = "verified"
    classified[0]["verification_source"] = "human-judgment"
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = bake_markdown(seed, metrics)
    assert "[VERIFIED via human judgment]" in md


def test_bake_markdown_shows_self_extension_tag():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    classified[0]["author_overlap"] = True
    classified[0]["overlapping_authors"] = ["Jianwei Li"]
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = bake_markdown(seed, metrics)
    assert "[SELF-EXTENSION — seed's own team]" in md
    assert "own team publishing a follow-on" in md


def test_bake_markdown_omits_self_extension_summary_when_none():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = bake_markdown(seed, metrics)
    assert "own team publishing a follow-on" not in md
    assert "[SELF-EXTENSION" not in md


def test_bake_markdown_nature_of_impact_summary_counts():
    classified = _make_classified(
        SAMPLE_CITING_WORKS,
        ["extends", "uses-as-tool", "background-mention"],
    )
    classified[0]["verification_status"] = "verified"
    classified[0]["verification_source"] = "evidence-dossier"
    seed = {**PARALLEL_NETCDF_WORK, "description": "Test description."}
    metrics = build_metrics(seed, classified)
    md = bake_markdown(seed, metrics)
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
