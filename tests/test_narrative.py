# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.narrative — narrative drafting (BACKLOG Theme F1/F2
seed), offline.

Uses the same committed OSTI fixture as test_themes.py for real
end-to-end build_dossier() calls where a dossier is needed, with the LLM
verification call mocked.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from wake import evidence, narrative, themes
from wake.classify import save_classified
from wake.report import add_override
from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS

_FIXTURE = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"


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


def _seed_classified(tmp_path, n=2):
    works = [_classified_work(i) for i in range(n)]
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], works, base=tmp_path)
    return works


def _fake_verification_response():
    return {
        "relationship": "extends",
        "confidence": 0.9,
        "justification": "The full text clearly shows a direct extension.",
        "agrees_with_provisional": False,
        "quotes": [{"page": 2, "text": "We directly extend the seed's method here.", "note": "x"}],
    }


def _build_dossier_for(tmp_path, citing_work, pdf_name="citing.pdf"):
    dest = tmp_path / "pdfs" / pdf_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_FIXTURE, dest)
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(dest), "source": "osti",
    }), patch("wake.evidence.chat_json", return_value=_fake_verification_response()):
        return evidence.build_dossier(PARALLEL_NETCDF_WORK, citing_work, base=tmp_path, verbose=False)


def _make_confirmed_theme(tmp_path, slug="t1"):
    """Build a two-work theme, verify both works, and confirm the theme --
    the standard "everything checks out" fixture used across many tests."""
    works = _seed_classified(tmp_path, 2)
    for w in works:
        _build_dossier_for(tmp_path, w, pdf_name=f"{w['openalex_id']}.pdf")
        add_override(
            PARALLEL_NETCDF_WORK["openalex_id"], w["openalex_id"],
            relationship="extends", justification="accepted", base=tmp_path,
            verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
        )
    themes.create_theme(
        PARALLEL_NETCDF_WORK, slug, title="Theme One", summary="Summary one.",
        citing_ids=[w["openalex_id"] for w in works], base=tmp_path,
    )
    themes.confirm_theme(PARALLEL_NETCDF_WORK, slug, base=tmp_path)
    return works


# --- create_outline: validation -----------------------------------------

def test_create_outline_rejects_empty_components(tmp_path):
    with pytest.raises(ValueError, match="must not be empty"):
        narrative.create_outline(PARALLEL_NETCDF_WORK, components=[], base=tmp_path)


def test_create_outline_rejects_bad_kind(tmp_path):
    with pytest.raises(ValueError, match="kind"):
        narrative.create_outline(
            PARALLEL_NETCDF_WORK,
            components=[{"slug": "a", "title": "A", "kind": "bogus"}],
            base=tmp_path,
        )


def test_create_outline_rejects_invalid_slug(tmp_path):
    with pytest.raises(ValueError, match="Invalid slug"):
        narrative.create_outline(
            PARALLEL_NETCDF_WORK,
            components=[{"slug": "Not A Slug!", "title": "A", "kind": "free"}],
            base=tmp_path,
        )


def test_create_outline_rejects_duplicate_slug(tmp_path):
    with pytest.raises(ValueError, match="Duplicate"):
        narrative.create_outline(
            PARALLEL_NETCDF_WORK,
            components=[
                {"slug": "a", "title": "A", "kind": "free"},
                {"slug": "a", "title": "A again", "kind": "free"},
            ],
            base=tmp_path,
        )


def test_create_outline_theme_kind_requires_theme_slugs(tmp_path):
    with pytest.raises(ValueError, match="no theme_slugs"):
        narrative.create_outline(
            PARALLEL_NETCDF_WORK,
            components=[{"slug": "a", "title": "A", "kind": "theme", "theme_slugs": []}],
            base=tmp_path,
        )


def test_create_outline_free_kind_rejects_theme_slugs(tmp_path):
    with pytest.raises(ValueError, match="kind='free' but theme_slugs"):
        narrative.create_outline(
            PARALLEL_NETCDF_WORK,
            components=[{"slug": "a", "title": "A", "kind": "free", "theme_slugs": ["t1"]}],
            base=tmp_path,
        )


def test_create_outline_rejects_nonexistent_theme(tmp_path):
    with pytest.raises(ValueError, match="don't exist yet"):
        narrative.create_outline(
            PARALLEL_NETCDF_WORK,
            components=[{"slug": "a", "title": "A", "kind": "theme", "theme_slugs": ["nope"]}],
            base=tmp_path,
        )


def test_create_outline_theme_need_not_be_confirmed_yet(tmp_path):
    """Planning ahead of confirmation is fine -- create_theme() always
    writes draft, and the outline should accept a draft theme reference."""
    works = _seed_classified(tmp_path, 1)
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[works[0]["openalex_id"]], base=tmp_path,
    )
    result = narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "a", "title": "A", "kind": "theme", "theme_slugs": ["t1"]}],
        base=tmp_path,
    )
    assert result["ok"] is True


# --- create_outline: success + persistence -------------------------------

def test_create_outline_writes_json_and_markdown(tmp_path):
    result = narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[
            {"slug": "intro", "title": "Introduction", "kind": "free"},
        ],
        base=tmp_path,
    )
    assert result["ok"] is True
    assert Path(result["outline_json_path"]).exists()
    assert Path(result["outline_path"]).exists()

    loaded = narrative.load_outline(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert loaded["components"][0]["slug"] == "intro"
    assert loaded["components"][0]["kind"] == "free"
    assert loaded["components"][0]["theme_slugs"] == []


def test_create_outline_overwrites_and_preserves_created_at(tmp_path):
    first = narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "intro", "title": "Introduction", "kind": "free"}],
        base=tmp_path,
    )
    loaded1 = narrative.load_outline(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    created_at = loaded1["created_at"]

    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[
            {"slug": "intro", "title": "Introduction (revised)", "kind": "free"},
            {"slug": "outro", "title": "Conclusion", "kind": "free"},
        ],
        base=tmp_path,
    )
    loaded2 = narrative.load_outline(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert loaded2["created_at"] == created_at
    assert len(loaded2["components"]) == 2
    assert loaded2["components"][0]["title"] == "Introduction (revised)"


def test_load_outline_missing_returns_none(tmp_path):
    assert narrative.load_outline("W999", base=tmp_path) is None


# --- create_section: validation -------------------------------------------

def test_create_section_rejects_empty_prose(tmp_path):
    with pytest.raises(ValueError, match="must not be empty"):
        narrative.create_section(
            PARALLEL_NETCDF_WORK, "intro", title="Intro", prose="   ", base=tmp_path,
        )


def test_create_section_rejects_invalid_slug(tmp_path):
    with pytest.raises(ValueError, match="Invalid slug"):
        narrative.create_section(
            PARALLEL_NETCDF_WORK, "Not A Slug!", title="Intro", prose="Some prose.", base=tmp_path,
        )


def test_create_section_rejects_nonexistent_theme(tmp_path):
    with pytest.raises(ValueError, match="don't exist yet"):
        narrative.create_section(
            PARALLEL_NETCDF_WORK, "a", title="A", prose="Prose.",
            theme_slugs=["nope"], base=tmp_path,
        )


def test_create_section_infers_free_kind_with_no_theme_slugs(tmp_path):
    result = narrative.create_section(
        PARALLEL_NETCDF_WORK, "intro", title="Introduction", prose="Framing prose.", base=tmp_path,
    )
    assert result["kind"] == "free"
    assert result["section_status"] == "draft"


def test_create_section_infers_theme_kind_with_theme_slugs(tmp_path):
    works = _seed_classified(tmp_path, 1)
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[works[0]["openalex_id"]], base=tmp_path,
    )
    result = narrative.create_section(
        PARALLEL_NETCDF_WORK, "a", title="A", prose="Prose grounded in t1.",
        theme_slugs=["t1"], base=tmp_path,
    )
    assert result["kind"] == "theme"
    assert result["theme_slugs"] == ["t1"]


def test_create_section_theme_need_not_be_confirmed_yet(tmp_path):
    works = _seed_classified(tmp_path, 1)
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[works[0]["openalex_id"]], base=tmp_path,
    )
    result = narrative.create_section(
        PARALLEL_NETCDF_WORK, "a", title="A", prose="Prose.",
        theme_slugs=["t1"], base=tmp_path,
    )
    assert result["ok"] is True


# --- create_section: success + persistence --------------------------------

def test_create_section_always_writes_draft(tmp_path):
    result = narrative.create_section(
        PARALLEL_NETCDF_WORK, "intro", title="Introduction", prose="Framing prose.", base=tmp_path,
    )
    assert result["section_status"] == "draft"

    loaded = narrative.load_section(PARALLEL_NETCDF_WORK["openalex_id"], "intro", base=tmp_path)
    assert loaded["section_status"] == "draft"
    assert loaded["prose"] == "Framing prose."


def test_create_section_overwrite_resets_to_draft_and_preserves_created_at(tmp_path):
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "intro", title="Introduction", prose="V1.", base=tmp_path,
    )
    narrative.confirm_section(PARALLEL_NETCDF_WORK, "intro", base=tmp_path)
    confirmed = narrative.load_section(PARALLEL_NETCDF_WORK["openalex_id"], "intro", base=tmp_path)
    assert confirmed["section_status"] == "confirmed"
    created_at = confirmed["created_at"]

    narrative.create_section(
        PARALLEL_NETCDF_WORK, "intro", title="Introduction", prose="V2 (revised).", base=tmp_path,
    )
    reverted = narrative.load_section(PARALLEL_NETCDF_WORK["openalex_id"], "intro", base=tmp_path)
    assert reverted["section_status"] == "draft"
    assert reverted["prose"] == "V2 (revised)."
    assert reverted["created_at"] == created_at


def test_load_section_missing_returns_none(tmp_path):
    assert narrative.load_section("W999", "nope", base=tmp_path) is None


# --- confirm_section: free-kind -------------------------------------------

def test_confirm_section_missing_raises(tmp_path):
    with pytest.raises(ValueError, match="No section"):
        narrative.confirm_section(PARALLEL_NETCDF_WORK, "nope", base=tmp_path)


def test_confirm_free_section_always_succeeds(tmp_path):
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "intro", title="Introduction", prose="Framing prose.", base=tmp_path,
    )
    result = narrative.confirm_section(PARALLEL_NETCDF_WORK, "intro", base=tmp_path)
    assert result["ok"] is True
    assert result["section_status"] == "confirmed"

    loaded = narrative.load_section(PARALLEL_NETCDF_WORK["openalex_id"], "intro", base=tmp_path)
    assert loaded["section_status"] == "confirmed"
    assert "confirmed_at" in loaded


# --- confirm_section: theme-kind gate -------------------------------------

def test_confirm_theme_section_blocked_when_theme_unconfirmed(tmp_path):
    works = _seed_classified(tmp_path, 1)
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[works[0]["openalex_id"]], base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "a", title="A", prose="Prose.", theme_slugs=["t1"], base=tmp_path,
    )
    result = narrative.confirm_section(PARALLEL_NETCDF_WORK, "a", base=tmp_path)
    assert result["ok"] is False
    assert result["reason"] == "unconfirmed_themes"
    assert result["unconfirmed"] == ["t1"]

    loaded = narrative.load_section(PARALLEL_NETCDF_WORK["openalex_id"], "a", base=tmp_path)
    assert loaded["section_status"] == "draft"


def test_confirm_theme_section_succeeds_when_theme_confirmed(tmp_path):
    _make_confirmed_theme(tmp_path, "t1")
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "a", title="A", prose="Prose grounded in t1.",
        theme_slugs=["t1"], base=tmp_path,
    )
    result = narrative.confirm_section(PARALLEL_NETCDF_WORK, "a", base=tmp_path)
    assert result["ok"] is True


def test_confirm_theme_section_rechecks_fresh_not_cached(tmp_path):
    """If a theme is reopened to draft (e.g. by re-running create_theme
    with a new unverified work) after a section referencing it was
    drafted, confirm_section must catch that -- not rely on a stale
    'was confirmed once' cache."""
    works = _make_confirmed_theme(tmp_path, "t1")
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "a", title="A", prose="Prose grounded in t1.",
        theme_slugs=["t1"], base=tmp_path,
    )
    # Reopen t1 to draft by adding a fresh, unverified work.
    more_works = _seed_classified(tmp_path, 3)  # index 2 is new
    all_ids = [w["openalex_id"] for w in works] + [more_works[2]["openalex_id"]]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=all_ids, base=tmp_path,
    )
    reopened = themes.load_theme(PARALLEL_NETCDF_WORK["openalex_id"], "t1", base=tmp_path)
    assert reopened["theme_status"] == "draft"

    result = narrative.confirm_section(PARALLEL_NETCDF_WORK, "a", base=tmp_path)
    assert result["ok"] is False
    assert result["reason"] == "unconfirmed_themes"


def test_confirm_theme_section_with_multiple_themes_requires_all_confirmed(tmp_path):
    _make_confirmed_theme(tmp_path, "t1")  # uses indices 0, 1
    # t2 exists (uses the remaining sample work) but is never confirmed.
    works2 = _seed_classified(tmp_path, 3)  # re-saves 0,1,2 -- t1's overrides are keyed
                                             # by citing_id in overrides.jsonl, unaffected
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t2", title="T2", summary="S2",
        citing_ids=[works2[2]["openalex_id"]], base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "a", title="A", prose="Spans two themes.",
        theme_slugs=["t1", "t2"], base=tmp_path,
    )
    result = narrative.confirm_section(PARALLEL_NETCDF_WORK, "a", base=tmp_path)
    assert result["ok"] is False
    assert result["unconfirmed"] == ["t2"]


# --- stitch ----------------------------------------------------------------

def test_stitch_without_outline_raises(tmp_path):
    with pytest.raises(ValueError, match="No narrative outline"):
        narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)


def test_stitch_all_confirmed(tmp_path):
    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "intro", "title": "Introduction", "kind": "free"}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "intro", title="Introduction", prose="Opening paragraph.", base=tmp_path,
    )
    narrative.confirm_section(PARALLEL_NETCDF_WORK, "intro", base=tmp_path)

    result = narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert result["ok"] is True
    assert result["confirmed_sections"] == 1
    assert result["draft_sections"] == 0
    assert result["missing_sections"] == []

    text = Path(result["narrative_path"]).read_text()
    assert "Opening paragraph." in text
    assert "DRAFT" not in text
    assert "Partial narrative" not in text


def test_stitch_marks_partial_narrative_for_draft_and_missing_sections(tmp_path):
    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[
            {"slug": "intro", "title": "Introduction", "kind": "free"},
            {"slug": "outro", "title": "Conclusion", "kind": "free"},
        ],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "intro", title="Introduction", prose="Opening paragraph.", base=tmp_path,
    )
    # "outro" never drafted, "intro" never confirmed.

    result = narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert result["draft_sections"] == 1
    assert result["missing_sections"] == ["outro"]

    text = Path(result["narrative_path"]).read_text()
    assert "Partial narrative" in text
    assert "DRAFT" in text
    assert "not yet drafted" in text


def test_stitch_preserves_outline_order(tmp_path):
    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[
            {"slug": "z-section", "title": "Z Comes First", "kind": "free"},
            {"slug": "a-section", "title": "A Comes Second", "kind": "free"},
        ],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "z-section", title="Z Comes First", prose="Z prose.", base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "a-section", title="A Comes Second", prose="A prose.", base=tmp_path,
    )
    result = narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    text = Path(result["narrative_path"]).read_text()
    assert text.index("Z Comes First") < text.index("A Comes Second")


# --- reference markers: packet consistency & per-marker validation ------

def test_create_section_packet_consistency_pass_rejects_missing_dossier(tmp_path):
    """If overrides.jsonl calls a work verified but its dossier file is
    missing on disk, the packet is inconsistent -- refuse before even
    looking at this section's own markers."""
    works = _seed_classified(tmp_path, 1)
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], works[0]["openalex_id"],
        relationship="extends", justification="accepted", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    # No dossier was ever built for this work -- packet is inconsistent.
    with pytest.raises(ValueError, match="Packet inconsistency"):
        narrative.create_section(
            PARALLEL_NETCDF_WORK, "s1", title="S", prose="No refs here at all.", base=tmp_path,
        )


def test_create_section_accepts_valid_seed_ref(tmp_path):
    result = narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="S",
        prose="PnetCDF was introduced in 2003. [ref:SEED]", base=tmp_path,
    )
    assert result["ok"] is True


def test_create_section_accepts_valid_verified_work_ref(tmp_path):
    works = _seed_classified(tmp_path, 1)
    _build_dossier_for(tmp_path, works[0], pdf_name="w.pdf")
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], works[0]["openalex_id"],
        relationship="extends", justification="accepted", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    result = narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="S",
        prose=f"This work extends PnetCDF. [ref:{works[0]['openalex_id']}]", base=tmp_path,
    )
    assert result["ok"] is True


def test_create_section_accepts_multi_id_marker(tmp_path):
    works = _seed_classified(tmp_path, 2)
    for w in works:
        _build_dossier_for(tmp_path, w, pdf_name=f"{w['openalex_id']}.pdf")
        add_override(
            PARALLEL_NETCDF_WORK["openalex_id"], w["openalex_id"],
            relationship="extends", justification="accepted", base=tmp_path,
            verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
        )
    ids = ",".join(w["openalex_id"] for w in works)
    result = narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="S",
        prose=f"Both works extend PnetCDF. [ref:{ids}]", base=tmp_path,
    )
    assert result["ok"] is True


def test_create_section_rejects_unknown_ref_id(tmp_path):
    with pytest.raises(ValueError, match="W9999999999"):
        narrative.create_section(
            PARALLEL_NETCDF_WORK, "s1", title="S",
            prose="Some claim. [ref:W9999999999]", base=tmp_path,
        )


def test_create_section_rejects_unverified_ref_id(tmp_path):
    """A work that's classified but never overridden/verified is not a
    valid reference, even though it's a real citing work in this packet."""
    works = _seed_classified(tmp_path, 1)
    with pytest.raises(ValueError, match=works[0]["openalex_id"]):
        narrative.create_section(
            PARALLEL_NETCDF_WORK, "s1", title="S",
            prose=f"Some claim. [ref:{works[0]['openalex_id']}]", base=tmp_path,
        )


def test_create_section_rejects_dossier_only_unoverridden_ref_id(tmp_path):
    """A dossier exists (proposed, LLM-verified) but no human override was
    ever recorded -- themes.py's own status model calls this "proposed",
    not "verified", and narrative refs use the same bar."""
    works = _seed_classified(tmp_path, 1)
    _build_dossier_for(tmp_path, works[0], pdf_name="w.pdf")
    with pytest.raises(ValueError, match=works[0]["openalex_id"]):
        narrative.create_section(
            PARALLEL_NETCDF_WORK, "s1", title="S",
            prose=f"Some claim. [ref:{works[0]['openalex_id']}]", base=tmp_path,
        )


def test_create_section_reports_all_bad_ids_together(tmp_path):
    with pytest.raises(ValueError, match=r"W9999999999.*W8888888888|W8888888888.*W9999999999"):
        narrative.create_section(
            PARALLEL_NETCDF_WORK, "s1", title="S",
            prose="Some claim. [ref:W9999999999] Another. [ref:W8888888888]", base=tmp_path,
        )


def test_create_section_no_markers_still_works(tmp_path):
    """Framing prose with no factual claim needs no markers at all."""
    result = narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="S", prose="This paper set the stage for what followed.",
        base=tmp_path,
    )
    assert result["ok"] is True


# --- stitch: R-numbering and Chicago references -------------------------

def test_stitch_renumbers_refs_and_builds_reference_list(tmp_path):
    works = _seed_classified(tmp_path, 1)
    _build_dossier_for(tmp_path, works[0], pdf_name="w.pdf")
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], works[0]["openalex_id"],
        relationship="extends", justification="accepted", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    cid = works[0]["openalex_id"]

    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "s1", "title": "Section One", "kind": "free"}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="Section One",
        prose=f"PnetCDF was introduced in 2003. [ref:SEED] This work extends it. [ref:{cid}]",
        base=tmp_path,
    )
    narrative.confirm_section(PARALLEL_NETCDF_WORK, "s1", base=tmp_path)

    result = narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert result["reference_count"] == 2

    text = Path(result["narrative_path"]).read_text()
    assert "[ref:" not in text
    assert "[R1]" in text
    assert "[R2]" in text
    assert "## References" in text
    assert "1. " in text
    assert "2. " in text
    # SEED's own bibliographic fields (from PARALLEL_NETCDF_WORK) show up.
    assert PARALLEL_NETCDF_WORK["doi"] in text
    assert works[0]["doi"] in text


def test_stitch_ref_numbers_are_stable_across_reuse(tmp_path):
    """The same source cited in two different sections keeps one number,
    assigned on its first appearance in outline order."""
    works = _seed_classified(tmp_path, 2)
    for w in works:
        _build_dossier_for(tmp_path, w, pdf_name=f"{w['openalex_id']}.pdf")
        add_override(
            PARALLEL_NETCDF_WORK["openalex_id"], w["openalex_id"],
            relationship="extends", justification="accepted", base=tmp_path,
            verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
        )
    cid0, cid1 = works[0]["openalex_id"], works[1]["openalex_id"]

    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[
            {"slug": "s1", "title": "Section One", "kind": "free"},
            {"slug": "s2", "title": "Section Two", "kind": "free"},
        ],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="Section One",
        prose=f"First mention. [ref:{cid0}]", base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s2", title="Section Two",
        prose=f"Second mention, same source again. [ref:{cid0}] And a new one. [ref:{cid1}]",
        base=tmp_path,
    )
    result = narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert result["reference_count"] == 2

    text = Path(result["narrative_path"]).read_text()
    # cid0 got R1 (first section, first appearance); reused unchanged in
    # section two; cid1 got R2 (first appears in section two).
    assert "First mention. [R1](#r1)" in text
    assert "same source again. [R1](#r1)" in text
    assert "a new one. [R2](#r2)" in text


def test_stitch_multi_id_marker_renders_multiple_ref_links(tmp_path):
    works = _seed_classified(tmp_path, 2)
    for w in works:
        _build_dossier_for(tmp_path, w, pdf_name=f"{w['openalex_id']}.pdf")
        add_override(
            PARALLEL_NETCDF_WORK["openalex_id"], w["openalex_id"],
            relationship="extends", justification="accepted", base=tmp_path,
            verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
        )
    ids = ",".join(w["openalex_id"] for w in works)

    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "s1", "title": "Section One", "kind": "free"}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="Section One",
        prose=f"Both works agree. [ref:{ids}]", base=tmp_path,
    )
    result = narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    text = Path(result["narrative_path"]).read_text()
    assert "[R1](#r1), [R2](#r2)" in text


def test_stitch_no_references_section_when_no_markers_used(tmp_path):
    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "s1", "title": "Section One", "kind": "free"}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="Section One", prose="No sources here.", base=tmp_path,
    )
    result = narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert result["reference_count"] == 0
    text = Path(result["narrative_path"]).read_text()
    assert "## References" not in text


def test_stitch_reference_entry_omits_missing_doi_cleanly(tmp_path):
    """SAMPLE_CITING_WORKS[2] has doi=None -- the Chicago entry should
    simply skip the DOI clause rather than render a broken link."""
    works = [_classified_work(2)]
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], works, base=tmp_path)
    _build_dossier_for(tmp_path, works[0], pdf_name="w.pdf")
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], works[0]["openalex_id"],
        relationship="extends", justification="accepted", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    cid = works[0]["openalex_id"]

    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "s1", "title": "Section One", "kind": "free"}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="Section One",
        prose=f"A survey paper. [ref:{cid}]", base=tmp_path,
    )
    result = narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    text = Path(result["narrative_path"]).read_text()
    assert "DOI:" not in text
    assert works[0]["title"] in text


# --- export_refs -----------------------------------------------------------

def test_export_refs_writes_numbered_json_matching_stitch_order(tmp_path):
    works = _seed_classified(tmp_path, 1)
    _build_dossier_for(tmp_path, works[0], pdf_name="w.pdf")
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], works[0]["openalex_id"],
        relationship="extends", justification="accepted", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    cid = works[0]["openalex_id"]

    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "s1", "title": "Section One", "kind": "free"}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="Section One",
        prose=f"PnetCDF was introduced. [ref:SEED] This work extends it. [ref:{cid}]",
        base=tmp_path,
    )

    result = narrative.export_refs(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert result["ok"] is True
    assert result["reference_count"] == 2

    refs = json.loads(Path(result["refs_json_path"]).read_text())
    assert len(refs) == 2
    assert refs[0]["index"] == 1
    assert refs[0]["title"] == PARALLEL_NETCDF_WORK["title"]
    assert refs[0]["doi"] == PARALLEL_NETCDF_WORK["doi"]
    assert refs[1]["index"] == 2
    assert refs[1]["title"] == works[0]["title"]

    # Same R-numbering as stitch() would produce for the same document.
    stitched = narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    text = Path(stitched["narrative_path"]).read_text()
    assert "[R1](#r1)" in text
    assert "[R2](#r2)" in text


def test_export_refs_raises_without_outline(tmp_path):
    with pytest.raises(ValueError, match="No narrative outline"):
        narrative.export_refs(PARALLEL_NETCDF_WORK, base=tmp_path)


def test_export_refs_omits_missing_fields_cleanly(tmp_path):
    """SAMPLE_CITING_WORKS[2] has doi=None -- the exported ref entry
    should simply omit the doi key rather than including doi: null."""
    works = [_classified_work(2)]
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], works, base=tmp_path)
    _build_dossier_for(tmp_path, works[0], pdf_name="w.pdf")
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], works[0]["openalex_id"],
        relationship="extends", justification="accepted", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    cid = works[0]["openalex_id"]

    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "s1", "title": "Section One", "kind": "free"}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="Section One",
        prose=f"A survey paper. [ref:{cid}]", base=tmp_path,
    )
    result = narrative.export_refs(PARALLEL_NETCDF_WORK, base=tmp_path)
    refs = json.loads(Path(result["refs_json_path"]).read_text())
    assert "doi" not in refs[0]


def test_export_refs_writes_no_refs_when_no_markers_used(tmp_path):
    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "s1", "title": "Section One", "kind": "free"}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="Section One", prose="No sources here.", base=tmp_path,
    )
    result = narrative.export_refs(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert result["reference_count"] == 0
    refs = json.loads(Path(result["refs_json_path"]).read_text())
    assert refs == []


# --- summarize_refs_check ---------------------------------------------------

def _fake_results_sidecar(entries: list[dict]) -> dict:
    """Build a minimal ref-checker results.json (schema_version 3) shape
    from a compact list of (index, title, status, **extra) dicts --
    mirrors the real sidecar structure captured from a live ref-checker
    run against the Parallel netCDF narrative's own references."""
    references = {}
    for e in entries:
        idx = e["index"]
        references[str(idx)] = {
            "ref": {"index": idx, "title": e["title"]},
            "result": {
                "status": e["status"],
                "display_score": e.get("score", 1.0),
                "best_source": e.get("best_source", "openalex"),
                "year_mismatch_note": e.get("year_mismatch_note"),
                "id_notes": e.get("id_notes", []),
                "dead_urls": e.get("dead_urls", []),
                "exhausted_sources": e.get("exhausted_sources", []),
            },
        }
    return {"schema_version": 3, "references": references}


def test_summarize_refs_check_all_ok(tmp_path):
    results_path = tmp_path / "refs.results.json"
    results_path.write_text(json.dumps(_fake_results_sidecar([
        {"index": 1, "title": "Parallel netCDF", "status": "OK"},
        {"index": 2, "title": "Supporting Seamless Remote I/O", "status": "OK"},
    ])))

    result = narrative.summarize_refs_check(
        PARALLEL_NETCDF_WORK["openalex_id"], results_path, base=tmp_path,
    )
    assert result["ok"] is True
    assert result["total"] == 2
    assert result["ok_count"] == 2
    assert result["flagged_count"] == 0
    assert result["flagged"] == []


def test_summarize_refs_check_flags_closest_and_no_match(tmp_path):
    results_path = tmp_path / "refs.results.json"
    results_path.write_text(json.dumps(_fake_results_sidecar([
        {"index": 1, "title": "A Real Paper", "status": "OK"},
        {"index": 2, "title": "A Fuzzy Match", "status": "CLOSEST", "score": 0.85},
        {"index": 3, "title": "Nonexistent Paper", "status": "NO MATCH", "score": 0.3},
    ])))

    result = narrative.summarize_refs_check(
        PARALLEL_NETCDF_WORK["openalex_id"], results_path, base=tmp_path,
    )
    assert result["total"] == 3
    assert result["ok_count"] == 1
    assert result["flagged_count"] == 2
    statuses = {e["index"]: e["status"] for e in result["flagged"]}
    assert statuses[2] == "CLOSEST"
    assert statuses[3] == "NO MATCH"


def test_summarize_refs_check_flags_ok_status_with_year_mismatch_note(tmp_path):
    """A status=OK match (identifier-confirmed) can still carry a year-
    mismatch note -- the match itself is confirmed, but the discrepancy
    is still worth a human's eye, so it's flagged rather than silently
    bucketed as a clean OK."""
    results_path = tmp_path / "refs.results.json"
    results_path.write_text(json.dumps(_fake_results_sidecar([
        {"index": 1, "title": "Clean Match", "status": "OK"},
        {
            "index": 2, "title": "Year Mismatch Paper", "status": "OK",
            "year_mismatch_note": "year mismatch (ref year=2019, match year=2020)",
        },
    ])))

    result = narrative.summarize_refs_check(
        PARALLEL_NETCDF_WORK["openalex_id"], results_path, base=tmp_path,
    )
    assert result["ok_count"] == 1
    assert result["flagged_count"] == 1
    assert result["flagged"][0]["index"] == 2
    assert result["flagged"][0]["status"] == "OK"
    assert "year mismatch" in result["flagged"][0]["year_mismatch_note"]


def test_summarize_refs_check_missing_file_raises(tmp_path):
    with pytest.raises(ValueError, match="No ref-checker results file"):
        narrative.summarize_refs_check(
            PARALLEL_NETCDF_WORK["openalex_id"], tmp_path / "nope.json", base=tmp_path,
        )


def test_summarize_refs_check_malformed_file_raises(tmp_path):
    results_path = tmp_path / "bad.json"
    results_path.write_text("not json at all")
    with pytest.raises(ValueError, match="not valid JSON"):
        narrative.summarize_refs_check(
            PARALLEL_NETCDF_WORK["openalex_id"], results_path, base=tmp_path,
        )


def test_summarize_refs_check_wrong_shape_raises(tmp_path):
    results_path = tmp_path / "wrong_shape.json"
    results_path.write_text(json.dumps({"not_a_results_file": True}))
    with pytest.raises(ValueError, match="doesn't look like a ref-checker results sidecar"):
        narrative.summarize_refs_check(
            PARALLEL_NETCDF_WORK["openalex_id"], results_path, base=tmp_path,
        )
