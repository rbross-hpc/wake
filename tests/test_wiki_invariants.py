# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for tests/wiki_invariants.py's own correctness (positive + negative
cases per helper), plus one end-to-end test that builds a full wiki
(dossiers, a theme, a stitched narrative, a baked impact brief, README)
and applies every invariant to every rendered .md.

This is deliberately separate from each module's own unit tests
(test_evidence_rendering.py, test_themes.py, test_narrative.py,
test_report.py, test_evidence_wiki.py already cover individual rendering
functions in isolation) -- the point here is cross-file, whole-wiki
consistency: does every link this wiki writes actually resolve, and does
every file honor the same frontmatter/anchor conventions.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from wake import evidence, narrative, report, themes
from wake.classify import save_classified
from wake.evidence_wiki import rebuild_wiki_orientation
from wake.report import add_override

from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS
from .wiki_invariants import (
    assert_agents_md_declares_all_types,
    assert_all_relative_md_links_exist,
    assert_facet_list_valid,
    assert_frontmatter_relative_paths_resolve,
    assert_frontmatter_valid,
    assert_no_malformed_wikilinks,
    assert_r_anchors_resolve,
    assert_ref_link_syntax,
)

# AGENTS.md is a plain reference doc (mirroring a project's own
# AGENTS.md convention), not an OKF concept doc -- it carries no YAML
# frontmatter, unlike every other rendered .md in the wiki.
_NO_FRONTMATTER_FILES = {"AGENTS.md"}

_FIXTURE = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"


# --- assert_no_malformed_wikilinks ------------------------------------------

def test_assert_no_malformed_wikilinks_passes_on_plain_link():
    assert_no_malformed_wikilinks("See [W123](../../evidence/W123.md) for details.")


def test_assert_no_malformed_wikilinks_fails_on_double_bracket():
    with pytest.raises(AssertionError, match="malformed"):
        assert_no_malformed_wikilinks("See [[W123]](../../evidence/W123.md) for details.")


# --- assert_frontmatter_valid ------------------------------------------------

def test_assert_frontmatter_valid_passes_on_well_formed_doc():
    text = (
        "---\n"
        "type: theme\n"
        'title: "T"\n'
        'description: "D"\n'
        "theme_status: draft\n"
        "timestamp: 2026-01-01T00:00:00+00:00\n"
        "---\n\n# Theme: T\n"
    )
    fm = assert_frontmatter_valid(text, expected_type="theme")
    assert fm["type"] == "theme"


def test_assert_frontmatter_valid_fails_when_missing_entirely():
    with pytest.raises(AssertionError, match="missing YAML frontmatter"):
        assert_frontmatter_valid("# Just a heading\n\nNo frontmatter here.\n")


def test_assert_frontmatter_valid_fails_on_unknown_type():
    text = "---\ntype: not-a-real-type\ntitle: x\n---\n\n# X\n"
    with pytest.raises(AssertionError, match="not one of the known types"):
        assert_frontmatter_valid(text)


def test_assert_frontmatter_valid_fails_on_missing_required_key():
    text = "---\ntype: theme\ntitle: x\n---\n\n# X\n"
    with pytest.raises(AssertionError, match="missing required key"):
        assert_frontmatter_valid(text)


def test_assert_frontmatter_valid_fails_on_type_mismatch():
    text = "---\ntype: theme\ntitle: x\ndescription: d\ntheme_status: draft\ntimestamp: t\n---\n\n# X\n"
    with pytest.raises(AssertionError, match="expected type"):
        assert_frontmatter_valid(text, expected_type="narrative")


# --- assert_all_relative_md_links_exist -------------------------------------

def test_assert_all_relative_md_links_exist_passes_when_target_present(tmp_path):
    target = tmp_path / "evidence" / "W123.md"
    target.parent.mkdir(parents=True)
    target.write_text("stub")
    source = tmp_path / "narrative" / "sections" / "s1.md"
    source.parent.mkdir(parents=True)
    text = "This work. [W123](../../evidence/W123.md)"
    assert_all_relative_md_links_exist(text, source, tmp_path)


def test_assert_all_relative_md_links_exist_fails_when_target_missing(tmp_path):
    source = tmp_path / "narrative" / "sections" / "s1.md"
    source.parent.mkdir(parents=True)
    text = "This work. [W123](../../evidence/W123.md)"
    with pytest.raises(AssertionError, match="does not exist"):
        assert_all_relative_md_links_exist(text, source, tmp_path)


def test_assert_all_relative_md_links_exist_skips_external_and_fragment_links(tmp_path):
    source = tmp_path / "impact.md"
    text = (
        "See [DOI](https://doi.org/10.1/x) and [R1](#^r1) and "
        "[email](mailto:a@b.com)."
    )
    assert_all_relative_md_links_exist(text, source, tmp_path)


# --- assert_frontmatter_relative_paths_resolve --------------------------------

def test_assert_frontmatter_relative_paths_resolve_passes_when_target_present(tmp_path):
    (tmp_path / "pdfs").mkdir()
    (tmp_path / "pdfs" / "W123.pdf").write_text("stub")
    source = tmp_path / "evidence" / "W123.md"
    source.parent.mkdir()
    assert_frontmatter_relative_paths_resolve(
        {"type": "citing-work-evidence", "pdf": "../pdfs/W123.pdf"}, source,
    )


def test_assert_frontmatter_relative_paths_resolve_fails_when_target_missing(tmp_path):
    source = tmp_path / "evidence" / "W123.md"
    source.parent.mkdir(parents=True)
    with pytest.raises(AssertionError, match="does not exist"):
        assert_frontmatter_relative_paths_resolve(
            {"type": "citing-work-evidence", "pdf": "../pdfs/W123.pdf"}, source,
        )


def test_assert_frontmatter_relative_paths_resolve_fails_on_absolute_path(tmp_path):
    source = tmp_path / "evidence" / "W123.md"
    source.parent.mkdir(parents=True)
    with pytest.raises(AssertionError, match="absolute path"):
        assert_frontmatter_relative_paths_resolve(
            {"type": "citing-work-evidence", "pdf": "/tmp/somewhere/W123.pdf"}, source,
        )


def test_assert_frontmatter_relative_paths_resolve_noop_when_key_absent(tmp_path):
    source = tmp_path / "evidence" / "W123.md"
    source.parent.mkdir(parents=True)
    assert_frontmatter_relative_paths_resolve({"type": "citing-work-evidence"}, source)


def test_assert_frontmatter_relative_paths_resolve_noop_for_type_with_no_path_keys(tmp_path):
    source = tmp_path / "theme.md"
    assert_frontmatter_relative_paths_resolve({"type": "theme"}, source)


# --- assert_facet_list_valid --------------------------------------------------

def test_assert_facet_list_valid_passes_for_single_facet():
    assert_facet_list_valid([{"label": "extends", "confidence": 0.9, "justification": "x"}])


def test_assert_facet_list_valid_passes_for_two_confidence_descending_facets():
    assert_facet_list_valid([
        {"label": "uses-as-tool", "confidence": 0.95, "justification": "a"},
        {"label": "applies-to-domain", "confidence": 0.8, "justification": "b"},
    ])


def test_assert_facet_list_valid_passes_for_equal_confidence_facets():
    assert_facet_list_valid([
        {"label": "uses-as-tool", "confidence": 0.8, "justification": "a"},
        {"label": "applies-to-domain", "confidence": 0.8, "justification": "b"},
    ])


def test_assert_facet_list_valid_fails_on_empty_list():
    with pytest.raises(AssertionError, match="empty"):
        assert_facet_list_valid([])


def test_assert_facet_list_valid_fails_when_exceeding_max_facets():
    facets = [
        {"label": "extends", "confidence": 0.95, "justification": "a"},
        {"label": "builds-on", "confidence": 0.9, "justification": "b"},
        {"label": "uses-as-tool", "confidence": 0.85, "justification": "c"},
        {"label": "benchmarks", "confidence": 0.8, "justification": "d"},
    ]
    with pytest.raises(AssertionError, match="MAX_FACETS"):
        assert_facet_list_valid(facets)


def test_assert_facet_list_valid_fails_on_unknown_label():
    with pytest.raises(AssertionError, match="unknown label"):
        assert_facet_list_valid([{"label": "not-a-real-label", "confidence": 0.9, "justification": "x"}])


def test_assert_facet_list_valid_fails_on_confidence_below_minimum():
    with pytest.raises(AssertionError, match="outside"):
        assert_facet_list_valid([{"label": "extends", "confidence": 0.3, "justification": "x"}])


def test_assert_facet_list_valid_fails_on_confidence_above_one():
    with pytest.raises(AssertionError, match="outside"):
        assert_facet_list_valid([{"label": "extends", "confidence": 1.5, "justification": "x"}])


def test_assert_facet_list_valid_fails_on_non_numeric_confidence():
    with pytest.raises(AssertionError, match="not a number"):
        assert_facet_list_valid([{"label": "extends", "confidence": "high", "justification": "x"}])


def test_assert_facet_list_valid_fails_when_not_confidence_descending():
    with pytest.raises(AssertionError, match="not confidence-descending"):
        assert_facet_list_valid([
            {"label": "uses-as-tool", "confidence": 0.6, "justification": "a"},
            {"label": "applies-to-domain", "confidence": 0.9, "justification": "b"},
        ])


# --- assert_ref_link_syntax ---------------------------------------------------

def test_assert_ref_link_syntax_passes_for_correct_rendering():
    text = (
        "Some claim. [W111](../../evidence/W111.md) "
        "Another claim. [ref:W222] "
        "Seed claim. [SEED](../../impact.md)"
    )
    assert_ref_link_syntax(
        text, ids_with_dossier={"W111"}, ids_without_dossier={"W222"}, seed_linked=True,
    )


def test_assert_ref_link_syntax_fails_on_malformed_dossier_link():
    text = "Some claim. [[W111]](../../evidence/W111.md)"
    with pytest.raises(AssertionError, match="not found"):
        assert_ref_link_syntax(text, ids_with_dossier={"W111"}, ids_without_dossier=set())


def test_assert_ref_link_syntax_fails_when_dossier_id_left_as_raw_marker():
    text = "Some claim. [ref:W111]"
    with pytest.raises(AssertionError, match="not found"):
        assert_ref_link_syntax(text, ids_with_dossier={"W111"}, ids_without_dossier=set())


# --- assert_r_anchors_resolve ------------------------------------------------

def test_assert_r_anchors_resolve_passes_for_correct_stitched_doc():
    text = (
        "Body. [R1](#^r1) more body [R2](#^r2).\n\n"
        "## References\n\n"
        "1. Some Author. Title. ^r1\n\n"
        "2. Other Author. Title. ^r2\n"
    )
    assert_r_anchors_resolve(text)


def test_assert_r_anchors_resolve_fails_on_html_anchor():
    text = '<a name="r1"></a>1. Some Author.'
    with pytest.raises(AssertionError, match="HTML"):
        assert_r_anchors_resolve(text)


def test_assert_r_anchors_resolve_fails_on_bare_fragment_link():
    text = "Body. [R1](#r1)\n\n## References\n\n1. Author. ^r1\n"
    with pytest.raises(AssertionError, match="bare"):
        assert_r_anchors_resolve(text)


def test_assert_r_anchors_resolve_fails_on_dangling_link():
    text = "Body. [R1](#^r1)\n\n## References\n\n(no block id here)\n"
    with pytest.raises(AssertionError, match="no matching"):
        assert_r_anchors_resolve(text)


def test_assert_r_anchors_resolve_fails_on_unused_block_id():
    text = "Body, no refs used.\n\n## References\n\n1. Author. ^r1\n"
    with pytest.raises(AssertionError, match="no matching"):
        assert_r_anchors_resolve(text)


# --- end-to-end: build a full wiki, check every invariant on every file -----

def _classified_work(idx: int, **overrides) -> dict:
    return {
        **SAMPLE_CITING_WORKS[idx],
        "relationship": "uses-as-tool",
        "confidence": 0.4,
        "justification": "Likely uses PnetCDF for I/O.",
        "has_abstract": True,
        "strength": 5,
        "verification_status": "provisional",
        **overrides,
    }


def _fake_verification_response():
    return {
        "relationship": "extends",
        "confidence": 0.9,
        "justification": "The full text clearly shows a direct extension.",
        "agrees_with_provisional": False,
        "quotes": [{"page": 2, "text": "We directly extend the seed's method here.", "note": "x"}],
    }


def _fake_multi_facet_verification_response():
    return {
        "relationships": [
            {
                "label": "uses-as-tool", "confidence": 0.95,
                "justification": "Integrates PnetCDF for all I/O.",
                "quotes": [{"page": 9, "text": "PnetCDF was integrated for all I/O.", "note": "Direct statement."}],
            },
            {
                "label": "applies-to-domain", "confidence": 0.8,
                "justification": "Applies it to flood modeling on supercomputers.",
                "quotes": [{"page": 2, "text": "IFM is a flood-modeling framework for petascale HPC.", "note": "Domain framing."}],
            },
        ],
        "agrees_with_provisional": True,
    }


def _build_multi_facet_dossier_for(tmp_path, citing_work, pdf_name):
    dest = tmp_path / "pdfs" / pdf_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_FIXTURE, dest)
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(dest), "source": "osti",
    }), patch("wake.evidence.config.evidence_cfg", return_value={"prompt_version": "evidence-2"}), \
         patch("wake.evidence.chat_json", return_value=_fake_multi_facet_verification_response()):
        return evidence.build_dossier(PARALLEL_NETCDF_WORK, citing_work, base=tmp_path, verbose=False)


def _build_dossier_for(tmp_path, citing_work, pdf_name):
    dest = tmp_path / "pdfs" / pdf_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_FIXTURE, dest)
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(dest), "source": "osti",
    }), patch("wake.evidence.chat_json", return_value=_fake_verification_response()):
        return evidence.build_dossier(PARALLEL_NETCDF_WORK, citing_work, base=tmp_path, verbose=False)


_MULTI_FACET_WORK = {
    "openalex_id": "W1000000004",
    "title": "IFM: A Scalable High Resolution Flood Modeling Framework",
    "authors": ["Some Author"],
    "year": 2014,
    "venue": "Lecture Notes in Computer Science",
    "venue_type": "conference",
    "doi": "10.1145/fake.004",
    "cited_by_count": 30,
    "type": "proceedings-article",
    "abstract": "IFM uses Parallel netCDF for I/O and applies it to flood modeling at supercomputer scale.",
    "topics": ["High-performance computing"],
}


def _build_full_wiki(tmp_path):
    """Build a minimal-but-complete wiki: two dossier-backed verified
    works (one grounding a theme + narrative section, one left as a
    verified-but-unreferenced dossier -- exercising the 'no back-link
    line' path), one classified-but-never-evidenced work (exercising the
    raw-[ref:...]-marker path), one multi-facet dossier (both
    "uses-as-tool" and "applies-to-domain", exercising the per-facet
    rendering path), a confirmed theme, a stitched narrative with one
    theme-grounded section, and a baked impact brief."""
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    w0 = _classified_work(0)  # referenced by theme + section
    w1 = _classified_work(1)  # verified dossier, but not referenced anywhere
    w2 = _classified_work(2, doi=None)  # never evidenced -- provisional only
    w3 = {
        **_MULTI_FACET_WORK,
        "relationship": "uses-as-tool",
        "confidence": 0.6,
        "justification": "Likely uses PnetCDF and applies it to flood modeling.",
        "relationships": [
            {"label": "uses-as-tool", "confidence": 0.6, "justification": "Likely uses PnetCDF."},
            {"label": "applies-to-domain", "confidence": 0.55, "justification": "Applies it to flood modeling."},
        ],
        "has_abstract": True,
        "verification_status": "provisional",
    }

    save_classified(seed_id, [w0, w1, w2, w3], base=tmp_path)

    _build_dossier_for(tmp_path, w0, pdf_name=f"{w0['openalex_id']}.pdf")
    _build_dossier_for(tmp_path, w1, pdf_name=f"{w1['openalex_id']}.pdf")
    _build_multi_facet_dossier_for(tmp_path, w3, pdf_name=f"{w3['openalex_id']}.pdf")

    for w in (w0, w1):
        add_override(
            seed_id, w["openalex_id"], relationship="extends", justification="accepted",
            base=tmp_path, verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
        )

    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="Theme One", summary="Summary one.",
        citing_ids=[w0["openalex_id"]], base=tmp_path,
    )
    themes.confirm_theme(PARALLEL_NETCDF_WORK, "t1", base=tmp_path)

    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "s1", "title": "Section One", "kind": "theme", "theme_slugs": ["t1"]}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="Section One",
        prose=(
            f"This work extends PnetCDF. [ref:{w0['openalex_id']}] "
            f"Also PnetCDF itself. [ref:SEED]"
        ),
        theme_slugs=["t1"], base=tmp_path,
    )
    narrative.confirm_section(PARALLEL_NETCDF_WORK, "s1", base=tmp_path)
    narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)

    classified = [
        {**w0, "relationship": "extends", "confidence": 1.0, "justification": "accepted",
         "verification_status": "verified", "verification_source": "evidence-dossier"},
        {**w1, "relationship": "extends", "confidence": 1.0, "justification": "accepted",
         "verification_status": "verified", "verification_source": "evidence-dossier"},
        {**w2, "relationship": "background-mention", "confidence": 0.3, "justification": "Mentioned only."},
        w3,
    ]
    report.bake_and_save(PARALLEL_NETCDF_WORK, classified, base=tmp_path, verbose=False)

    rebuild_wiki_orientation(seed_id, PARALLEL_NETCDF_WORK, base=tmp_path)

    return {
        "seed_id": seed_id,
        "w0": w0, "w1": w1, "w2": w2, "w3": w3,
        "wiki_root": tmp_path / "wake-out" / seed_id,
    }


def test_full_wiki_output_satisfies_all_invariants(tmp_path):
    ctx = _build_full_wiki(tmp_path)
    wiki_root = ctx["wiki_root"]

    md_files = sorted(wiki_root.rglob("*.md"))
    assert len(md_files) >= 7, f"expected at least 7 rendered .md files, found {len(md_files)}: {md_files}"

    for md_path in md_files:
        text = md_path.read_text(encoding="utf-8")
        assert_no_malformed_wikilinks(text, source=md_path)
        assert_all_relative_md_links_exist(text, md_path, wiki_root)
        if md_path.name in _NO_FRONTMATTER_FILES:
            continue
        frontmatter = assert_frontmatter_valid(text, source=md_path)
        assert_frontmatter_relative_paths_resolve(frontmatter, md_path)

    section_text = (wiki_root / "narrative" / "sections" / "s1.md").read_text()
    assert_ref_link_syntax(
        section_text,
        ids_with_dossier={ctx["w0"]["openalex_id"]},
        ids_without_dossier=set(),
        seed_linked=True,
        source="narrative/sections/s1.md",
    )

    narrative_text = (wiki_root / "narrative.md").read_text()
    assert_r_anchors_resolve(narrative_text, source="narrative.md")

    # The unreferenced-but-verified dossier (w1) has no "Referenced by"
    # line; the theme/section-grounded one (w0) does.
    w0_dossier = (wiki_root / "evidence" / f"{ctx['w0']['openalex_id']}.md").read_text()
    w1_dossier = (wiki_root / "evidence" / f"{ctx['w1']['openalex_id']}.md").read_text()
    assert "**Referenced by:**" in w0_dossier
    assert "**Referenced by:**" not in w1_dossier

    # w2 was never evidenced -- no dossier file at all.
    assert not (wiki_root / "evidence" / f"{ctx['w2']['openalex_id']}.md").exists()

    readme_text = (wiki_root / "README.md").read_text()
    assert "[Impact Brief](impact.md)" in readme_text
    assert "[Narrative](narrative.md)" in readme_text
    assert "[Evidence Wiki](evidence/index.md)" in readme_text
    assert "[Themes](evidence/themes/index.md)" in readme_text
    assert "[AGENTS.md](AGENTS.md)" in readme_text

    agents_text = (wiki_root / "AGENTS.md").read_text()
    assert_agents_md_declares_all_types(agents_text, md_files, source="AGENTS.md")

    # w3's dossier has two facets (uses-as-tool + applies-to-domain) --
    # its JSON sidecar's proposed.relationships must satisfy the facet
    # invariant, and its rendered .md must show both per-facet sections.
    w3_json = evidence.load_dossier(ctx["seed_id"], ctx["w3"]["openalex_id"], base=tmp_path)
    assert_facet_list_valid(w3_json["proposed"]["relationships"], source="evidence/W1000000004.json (proposed)")
    assert_facet_list_valid(w3_json["provisional"]["relationships"], source="evidence/W1000000004.json (provisional)")

    w3_dossier = (wiki_root / "evidence" / f"{ctx['w3']['openalex_id']}.md").read_text()
    assert "### uses-as-tool (confidence: 0.95)" in w3_dossier
    assert "### applies-to-domain (confidence: 0.80)" in w3_dossier

    # impact.md's relationship table footnotes the over-count caused by
    # w3's two facets.
    impact_text = (wiki_root / "impact.md").read_text()
    assert "Rows may sum to more than the total classified count" in impact_text
