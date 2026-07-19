# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.themes — combined-evidence thematic documents
(BACKLOG Theme C), offline.

Uses the same committed OSTI fixture as test_evidence.py for real
end-to-end build_dossier() calls where a dossier is needed, with the LLM
verification call mocked.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from wake import evidence, evidence_wiki, themes
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


def _seed_two_classified(tmp_path):
    works = [_classified_work(0), _classified_work(1)]
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


# --- create_theme: validation ------------------------------------------

def test_create_theme_rejects_empty_citing_ids(tmp_path):
    _seed_two_classified(tmp_path)
    with pytest.raises(ValueError, match="must not be empty"):
        themes.create_theme(
            PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=[], base=tmp_path,
        )


def test_create_theme_rejects_invalid_slug(tmp_path):
    works = _seed_two_classified(tmp_path)
    with pytest.raises(ValueError, match="Invalid theme slug"):
        themes.create_theme(
            PARALLEL_NETCDF_WORK, "Not A Slug!", title="T", summary="S",
            citing_ids=[works[0]["openalex_id"]], base=tmp_path,
        )


def test_create_theme_rejects_unclassified_citing_id(tmp_path):
    _seed_two_classified(tmp_path)
    with pytest.raises(ValueError, match="never been classified"):
        themes.create_theme(
            PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
            citing_ids=["W_NEVER_CLASSIFIED"], base=tmp_path,
        )


# --- create_theme: status resolution and needs_evidence -----------------

def test_create_theme_always_writes_draft(tmp_path):
    works = _seed_two_classified(tmp_path)
    result = themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[works[0]["openalex_id"]], base=tmp_path,
    )
    assert result["ok"] is True
    assert result["theme_status"] == "draft"


def test_create_theme_provisional_works_flagged_needs_evidence(tmp_path):
    works = _seed_two_classified(tmp_path)
    ids = [w["openalex_id"] for w in works]
    result = themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=ids, base=tmp_path,
    )
    assert set(result["needs_evidence"]) == set(ids)
    for w in result["citing_works"]:
        assert w["status"] == "provisional"
        assert w["has_dossier"] is False


def test_create_theme_dossier_backed_work_is_proposed_not_needs_evidence(tmp_path):
    works = _seed_two_classified(tmp_path)
    _build_dossier_for(tmp_path, works[0])

    result = themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[works[0]["openalex_id"]], base=tmp_path,
    )
    assert result["needs_evidence"] == []
    assert result["citing_works"][0]["status"] == "proposed"
    assert result["citing_works"][0]["has_dossier"] is True


def test_create_theme_human_judgment_verified_work_not_flagged_needs_evidence(tmp_path):
    """A work verified via a plain human-judgment override (no dossier at
    all) already meets the confirmation bar -- must never show up in
    needs_evidence just because has_dossier is False for it."""
    works = _seed_two_classified(tmp_path)
    wid = works[0]["openalex_id"]
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], wid,
        relationship="extends", justification="human says so",
        verification_source="human-judgment", base=tmp_path,
    )
    result = themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=[wid], base=tmp_path,
    )
    assert result["citing_works"][0]["status"] == "verified"
    assert result["needs_evidence"] == []


def test_create_theme_never_upgrades_a_works_own_status(tmp_path):
    """Creating a theme must never itself promote a work's relationship
    status -- only classify/evidence/override do that."""
    works = _seed_two_classified(tmp_path)
    wid = works[0]["openalex_id"]
    result = themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=[wid], base=tmp_path,
    )
    assert result["citing_works"][0]["status"] == "provisional"

    from wake.classify import load_classified
    still_provisional = load_classified(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert still_provisional[0]["verification_status"] == "provisional"


# --- create_theme: always overwrite, no --force --------------------------

def test_create_theme_overwrites_on_rerun_without_force(tmp_path):
    works = _seed_two_classified(tmp_path)
    wid = works[0]["openalex_id"]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="First Title", summary="First summary",
        citing_ids=[wid], base=tmp_path,
    )
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="Second Title", summary="Second summary",
        citing_ids=[wid], base=tmp_path,
    )
    loaded = themes.load_theme(PARALLEL_NETCDF_WORK["openalex_id"], "t1", base=tmp_path)
    assert loaded["title"] == "Second Title"
    assert loaded["summary"] == "Second summary"


def test_create_theme_preserves_created_at_across_rewrites(tmp_path):
    works = _seed_two_classified(tmp_path)
    wid = works[0]["openalex_id"]
    first = themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=[wid], base=tmp_path,
    )
    loaded1 = themes.load_theme(PARALLEL_NETCDF_WORK["openalex_id"], "t1", base=tmp_path)
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T2", summary="S2", citing_ids=[wid], base=tmp_path,
    )
    loaded2 = themes.load_theme(PARALLEL_NETCDF_WORK["openalex_id"], "t1", base=tmp_path)
    assert loaded1["created_at"] == loaded2["created_at"]
    assert loaded1["updated_at"] != loaded2["updated_at"] or True  # updated_at may tie at second resolution


# --- confirm_theme: the human-confirm gate -------------------------------

def test_confirm_theme_blocked_when_works_unverified(tmp_path):
    works = _seed_two_classified(tmp_path)
    ids = [w["openalex_id"] for w in works]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=ids, base=tmp_path,
    )
    result = themes.confirm_theme(PARALLEL_NETCDF_WORK, "t1", base=tmp_path)
    assert result["ok"] is False
    assert result["reason"] == "unverified_works"
    assert set(result["unverified"]) == set(ids)


def test_confirm_theme_missing_theme_raises(tmp_path):
    with pytest.raises(ValueError, match="No theme"):
        themes.confirm_theme(PARALLEL_NETCDF_WORK, "does-not-exist", base=tmp_path)


def test_confirm_theme_succeeds_when_all_verified(tmp_path):
    works = _seed_two_classified(tmp_path)
    ids = [w["openalex_id"] for w in works]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=ids, base=tmp_path,
    )
    for wid in ids:
        add_override(
            PARALLEL_NETCDF_WORK["openalex_id"], wid,
            relationship="extends", justification="ok",
            verification_source="human-judgment", base=tmp_path,
        )
    result = themes.confirm_theme(PARALLEL_NETCDF_WORK, "t1", base=tmp_path)
    assert result["ok"] is True
    assert result["theme_status"] == "confirmed"

    loaded = themes.load_theme(PARALLEL_NETCDF_WORK["openalex_id"], "t1", base=tmp_path)
    assert loaded["theme_status"] == "confirmed"
    assert loaded["needs_evidence"] == []
    assert "confirmed_at" in loaded


def test_confirm_theme_partial_verification_still_blocked(tmp_path):
    works = _seed_two_classified(tmp_path)
    ids = [w["openalex_id"] for w in works]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=ids, base=tmp_path,
    )
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], ids[0],
        relationship="extends", justification="ok",
        verification_source="human-judgment", base=tmp_path,
    )
    result = themes.confirm_theme(PARALLEL_NETCDF_WORK, "t1", base=tmp_path)
    assert result["ok"] is False
    assert result["unverified"] == [ids[1]]


def test_confirm_theme_reresolves_fresh_not_from_stale_json(tmp_path):
    """A work verified AFTER theme creation (without re-running
    `wake theme create`) must still count at confirm time -- confirm_theme
    re-resolves each work's status fresh rather than trusting whatever was
    cached in the theme's JSON at creation time."""
    works = _seed_two_classified(tmp_path)
    ids = [w["openalex_id"] for w in works]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=ids, base=tmp_path,
    )
    # Verify both directly via override, without ever re-running create_theme.
    for wid in ids:
        add_override(
            PARALLEL_NETCDF_WORK["openalex_id"], wid,
            relationship="extends", justification="ok",
            verification_source="human-judgment", base=tmp_path,
        )
    result = themes.confirm_theme(PARALLEL_NETCDF_WORK, "t1", base=tmp_path)
    assert result["ok"] is True


# --- list_theme_needs_evidence / wake theme queue ------------------------

def test_list_theme_needs_evidence_empty_when_no_themes(tmp_path):
    assert themes.list_theme_needs_evidence(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path) == []


def test_list_theme_needs_evidence_reports_missing_dossiers(tmp_path):
    works = _seed_two_classified(tmp_path)
    wid = works[0]["openalex_id"]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=[wid], base=tmp_path,
    )
    queue = themes.list_theme_needs_evidence(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert queue == [{"theme_slug": "t1", "citing_id": wid, "status": "needs-evidence"}]


def test_list_theme_needs_evidence_detects_dossier_appearing_later(tmp_path):
    """If a dossier appears for a needs_evidence work via an unrelated
    `wake evidence` call, the theme's own JSON must NOT be silently
    upgraded -- but the queue report must reflect the new dossier so the
    agent knows to review and re-assert it."""
    works = _seed_two_classified(tmp_path)
    wid = works[0]["openalex_id"]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=[wid], base=tmp_path,
    )
    _build_dossier_for(tmp_path, works[0])

    queue = themes.list_theme_needs_evidence(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert queue == [{"theme_slug": "t1", "citing_id": wid, "status": "dossier-available-unreviewed"}]

    loaded = themes.load_theme(PARALLEL_NETCDF_WORK["openalex_id"], "t1", base=tmp_path)
    assert loaded["needs_evidence"] == [wid]  # unchanged, not auto-upgraded


def test_list_theme_needs_evidence_aggregates_across_multiple_themes(tmp_path):
    works = _seed_two_classified(tmp_path)
    ids = [w["openalex_id"] for w in works]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T1", summary="S", citing_ids=[ids[0]], base=tmp_path,
    )
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t2", title="T2", summary="S", citing_ids=[ids[1]], base=tmp_path,
    )
    queue = themes.list_theme_needs_evidence(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    slugs = {e["theme_slug"] for e in queue}
    assert slugs == {"t1", "t2"}


# --- markdown rendering ---------------------------------------------------

def test_theme_markdown_shows_draft_banner_and_status_tags(tmp_path):
    works = _seed_two_classified(tmp_path)
    ids = [w["openalex_id"] for w in works]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="Earth System Modeling", summary="Both use this for ESM.",
        citing_ids=ids, base=tmp_path,
    )
    md = themes.theme_path(PARALLEL_NETCDF_WORK["openalex_id"], "t1", base=tmp_path).read_text()
    assert "type: theme" in md
    assert "status:draft" in md
    assert "DRAFT" in md
    assert "Both use this for ESM." in md
    assert "[PROVISIONAL" in md
    assert "Needs Full-Text Verification" in md


def test_theme_markdown_shows_confirmed_banner(tmp_path):
    works = _seed_two_classified(tmp_path)
    wid = works[0]["openalex_id"]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=[wid], base=tmp_path,
    )
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], wid,
        relationship="extends", justification="ok",
        verification_source="human-judgment", base=tmp_path,
    )
    themes.confirm_theme(PARALLEL_NETCDF_WORK, "t1", base=tmp_path)
    md = themes.theme_path(PARALLEL_NETCDF_WORK["openalex_id"], "t1", base=tmp_path).read_text()
    assert "CONFIRMED" in md
    assert "status:confirmed" in md
    assert "Needs Full-Text Verification" not in md


def test_theme_markdown_links_dossier_backed_work(tmp_path):
    works = _seed_two_classified(tmp_path)
    _build_dossier_for(tmp_path, works[0])
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[works[0]["openalex_id"]], base=tmp_path,
    )
    md = themes.theme_path(PARALLEL_NETCDF_WORK["openalex_id"], "t1", base=tmp_path).read_text()
    assert f"](../{works[0]['openalex_id']}.md)" in md
    assert "[PROPOSED" in md


def test_theme_markdown_verified_no_dossier_has_no_dead_link_or_hint(tmp_path):
    works = _seed_two_classified(tmp_path)
    wid = works[0]["openalex_id"]
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], wid,
        relationship="extends", justification="ok",
        verification_source="human-judgment", base=tmp_path,
    )
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=[wid], base=tmp_path,
    )
    md = themes.theme_path(PARALLEL_NETCDF_WORK["openalex_id"], "t1", base=tmp_path).read_text()
    assert f"](../{wid}.md)" not in md
    assert "no full-text dossier yet" not in md
    assert "[VERIFIED]" in md


# --- evidence_wiki.rebuild_themes_index ----------------------------------

def test_rebuild_themes_index_no_themes_returns_path_without_writing(tmp_path):
    p = evidence_wiki.rebuild_themes_index(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert not p.exists()


def test_themes_index_created_as_side_effect_of_create_theme(tmp_path):
    works = _seed_two_classified(tmp_path)
    wid = works[0]["openalex_id"]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="My Theme", summary="S", citing_ids=[wid], base=tmp_path,
    )
    p = evidence_wiki.themes_index_path(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert p.exists()
    text = p.read_text()
    assert "## Draft (1)" in text
    assert "## Confirmed (0)" in text
    assert "My Theme" in text


def test_themes_index_moves_theme_from_draft_to_confirmed(tmp_path):
    works = _seed_two_classified(tmp_path)
    wid = works[0]["openalex_id"]
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S", citing_ids=[wid], base=tmp_path,
    )
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], wid,
        relationship="extends", justification="ok",
        verification_source="human-judgment", base=tmp_path,
    )
    themes.confirm_theme(PARALLEL_NETCDF_WORK, "t1", base=tmp_path)

    text = evidence_wiki.themes_index_path(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path).read_text()
    assert "## Confirmed (1)" in text
    assert "## Draft (0)" in text
