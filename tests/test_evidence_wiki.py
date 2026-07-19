# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.evidence_wiki — OKF index/log organization layer
(BACKLOG Theme D), offline.

Uses the same committed OSTI fixture as test_evidence.py for real
end-to-end build_dossier() calls, with the LLM verification call mocked.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from wake import evidence, evidence_wiki, report
from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS

_FIXTURE = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"


def _copy_fixture_pdf(tmp_path: Path, name: str = "citing.pdf") -> Path:
    dest = tmp_path / "pdfs" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_FIXTURE, dest)
    return dest


def _classified_work(idx: int = 0, **overrides) -> dict:
    return {
        **SAMPLE_CITING_WORKS[idx],
        "relationship": "uses-as-tool",
        "confidence": 0.4,
        "justification": "Likely uses PnetCDF for I/O, based on the abstract alone.",
        "has_abstract": True,
        "strength": 5,
        "verification_status": "provisional",
        **overrides,
    }


def _fake_verification_response(relationship="extends", agrees=False, quotes=None):
    return {
        "relationship": relationship,
        "confidence": 0.9,
        "justification": "The full text clearly shows a direct extension of the seed's method.",
        "agrees_with_provisional": agrees,
        "quotes": quotes if quotes is not None else [
            {"page": 2, "text": "We directly extend the subfiling scheme introduced by the seed paper.", "note": "extension"},
        ],
    }


def _build(tmp_path, citing_work=None, pdf_name="citing.pdf", force=False):
    pdf_copy = _copy_fixture_pdf(tmp_path, pdf_name)
    citing_work = citing_work or _classified_work()
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(pdf_copy), "source": "osti",
    }), patch("wake.evidence.chat_json", return_value=_fake_verification_response()):
        return evidence.build_dossier(
            PARALLEL_NETCDF_WORK, citing_work, base=tmp_path, force=force, verbose=False,
        )


# --- rebuild_index -----------------------------------------------------

def test_rebuild_index_no_dossiers_returns_path_without_writing(tmp_path):
    p = evidence_wiki.rebuild_index(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert not p.exists()


def test_index_created_as_side_effect_of_build_dossier(tmp_path):
    _build(tmp_path)
    p = evidence_wiki.index_path(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert p.exists()
    text = p.read_text()
    assert "type: index" in text
    assert "## Verified (0)" in text
    assert "## Pending Review (1)" in text
    assert SAMPLE_CITING_WORKS[0]["openalex_id"] in text


def test_index_groups_by_status_and_sorts_by_score(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]

    # Two dossiers: one high cited_by_count (should rank first), one low.
    _build(tmp_path, citing_work=_classified_work(0), pdf_name="a.pdf")  # cited_by_count=250
    _build(tmp_path, citing_work=_classified_work(1), pdf_name="b.pdf")  # cited_by_count=42

    text = evidence_wiki.index_path(seed_id, base=tmp_path).read_text()
    idx_high = text.index(SAMPLE_CITING_WORKS[0]["openalex_id"])
    idx_low = text.index(SAMPLE_CITING_WORKS[1]["openalex_id"])
    assert idx_high < idx_low  # higher-cited work ranks first within its group


def test_index_moves_entry_from_pending_to_verified(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    _build(tmp_path, citing_work=_classified_work(0))

    report.add_override(
        seed_id, citing_id, relationship="extends", justification="confirmed",
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
        base=tmp_path,
    )

    text = evidence_wiki.index_path(seed_id, base=tmp_path).read_text()
    assert "## Verified (1)" in text
    assert "## Pending Review (0)" in text


# --- append_log_entry ----------------------------------------------------

def test_log_created_with_header_on_first_write(tmp_path):
    seed_id = "W_SEED"
    evidence_wiki.append_log_entry(
        seed_id, event="dossier_built", citing_id="W_CITING",
        detail="proposed: extends (1 quotes)", seed_title="Some Seed", base=tmp_path,
    )
    p = evidence_wiki.log_path(seed_id, base=tmp_path)
    text = p.read_text()
    assert "type: log" in text
    assert "dossier_built" in text
    assert "W_CITING" in text


def test_log_appends_without_duplicating_header(tmp_path):
    seed_id = "W_SEED"
    evidence_wiki.append_log_entry(seed_id, event="dossier_built", citing_id="A", base=tmp_path)
    evidence_wiki.append_log_entry(seed_id, event="dossier_built", citing_id="B", base=tmp_path)
    text = evidence_wiki.log_path(seed_id, base=tmp_path).read_text()
    assert text.count("type: log") == 1
    assert "A" in text and "B" in text


def test_log_links_to_dossier_when_it_exists(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    _build(tmp_path, citing_work=_classified_work(0))
    text = evidence_wiki.log_path(seed_id, base=tmp_path).read_text()
    assert f"[{citing_id}]({citing_id}.md)" in text


def test_log_plain_text_when_no_dossier_exists(tmp_path):
    seed_id = "W_SEED"
    evidence_wiki.append_log_entry(seed_id, event="investigation_failed", citing_id="W_NOPE", base=tmp_path)
    text = evidence_wiki.log_path(seed_id, base=tmp_path).read_text()
    assert "[W_NOPE](W_NOPE.md)" not in text
    assert "W_NOPE" in text


def test_build_dossier_logs_failure_when_no_pdf(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_work = _classified_work(0)
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": False, "tried": ["osti", "semanticscholar"], "fallback_links": {},
    }):
        evidence.build_dossier(PARALLEL_NETCDF_WORK, citing_work, base=tmp_path, verbose=False)

    text = evidence_wiki.log_path(seed_id, base=tmp_path).read_text()
    assert "investigation_failed" in text
    assert "no PDF found" in text


def test_build_dossier_does_not_log_on_cache_hit(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_work = _classified_work(0)
    _build(tmp_path, citing_work=citing_work)
    log_text_after_first = evidence_wiki.log_path(seed_id, base=tmp_path).read_text()

    # second call, force=False -> cache hit, must not append another entry
    pdf_copy = tmp_path / "pdfs" / "citing.pdf"
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(pdf_copy), "source": "osti",
    }), patch("wake.evidence.chat_json", return_value=_fake_verification_response()):
        evidence.build_dossier(PARALLEL_NETCDF_WORK, citing_work, base=tmp_path, verbose=False)

    log_text_after_second = evidence_wiki.log_path(seed_id, base=tmp_path).read_text()
    assert log_text_after_first == log_text_after_second


# --- mark_verified -------------------------------------------------------

def test_mark_verified_missing_dossier_returns_false(tmp_path):
    assert evidence_wiki.mark_verified("W999", "W888", base=tmp_path) is False


def test_mark_verified_patches_json_and_markdown(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    _build(tmp_path, citing_work=_classified_work(0))

    ok = evidence_wiki.mark_verified(seed_id, citing_id, justification="looks right", base=tmp_path)
    assert ok is True

    loaded = evidence.load_dossier(seed_id, citing_id, base=tmp_path)
    assert loaded["verification_status"] == "verified"
    assert loaded["human_verification"]["justification"] == "looks right"

    md_text = evidence.dossier_path(seed_id, citing_id, base=tmp_path).read_text()
    assert "status:verified" in md_text
    assert "## Status: verified" in md_text
    assert "pending your review" not in md_text.lower()


def test_mark_verified_same_relationship_does_not_mark_corrected(tmp_path):
    """The dossier's own build_dossier() fixture proposes 'extends' — accepting
    it as-is (relationship == proposed.relationship) should not trigger the
    correction path or touch proposed.model_relationship."""
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    _build(tmp_path, citing_work=_classified_work(0))

    ok = evidence_wiki.mark_verified(
        seed_id, citing_id, justification="agreed", relationship="extends", base=tmp_path,
    )
    assert ok is True

    loaded = evidence.load_dossier(seed_id, citing_id, base=tmp_path)
    assert loaded["proposed"]["relationship"] == "extends"
    assert "model_relationship" not in loaded["proposed"]
    assert "corrected_from" not in loaded["human_verification"]


def test_mark_verified_relationship_correction_updates_proposed_and_index(tmp_path):
    """A human override that *disagrees* with the dossier's own proposed
    finding (e.g. correcting a model reasoning miss after checking the raw
    extraction directly) must update proposed.relationship so index.md/log.md
    reflect the human-confirmed relationship, not the superseded model
    conclusion -- otherwise the wiki silently drifts from what the impact
    brief actually uses."""
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    _build(tmp_path, citing_work=_classified_work(0))  # dossier proposes "extends"

    ok = evidence_wiki.mark_verified(
        seed_id, citing_id,
        justification="Full text actually shows plain adoption, not an extension.",
        relationship="uses-as-tool",
        base=tmp_path,
    )
    assert ok is True

    loaded = evidence.load_dossier(seed_id, citing_id, base=tmp_path)
    assert loaded["proposed"]["relationship"] == "uses-as-tool"
    assert loaded["proposed"]["model_relationship"] == "extends"
    assert loaded["proposed"]["model_justification"]
    assert loaded["human_verification"]["corrected_from"] == "extends"

    md_text = evidence.dossier_path(seed_id, citing_id, base=tmp_path).read_text()
    assert "proposed:uses-as-tool" in md_text
    assert "proposed:extends" not in md_text
    assert "corrected the model's reading from *extends* to *uses-as-tool*" in md_text

    index_p = evidence_wiki.rebuild_index(seed_id, base=tmp_path)
    index_text = index_p.read_text()
    assert "*uses-as-tool*" in index_text
    assert "*extends*" not in index_text


# --- add_override wiring --------------------------------------------------

def test_add_override_evidence_dossier_marks_verified_and_logs(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    _build(tmp_path, citing_work=_classified_work(0))

    report.add_override(
        seed_id, citing_id, relationship="extends", justification="confirmed",
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
        base=tmp_path,
    )

    loaded = evidence.load_dossier(seed_id, citing_id, base=tmp_path)
    assert loaded["verification_status"] == "verified"

    log_text = evidence_wiki.log_path(seed_id, base=tmp_path).read_text()
    assert "verified_by_human" in log_text


def test_add_override_human_judgment_does_not_touch_evidence_wiki(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    _build(tmp_path, citing_work=_classified_work(0))

    report.add_override(
        seed_id, citing_id, relationship="extends", justification="manual call",
        verification_source="human-judgment", seed_title=PARALLEL_NETCDF_WORK["title"],
        base=tmp_path,
    )

    loaded = evidence.load_dossier(seed_id, citing_id, base=tmp_path)
    assert loaded["verification_status"] == "pending-human-review"

    log_text = evidence_wiki.log_path(seed_id, base=tmp_path).read_text()
    assert "verified_by_human" not in log_text


def test_add_override_evidence_dossier_no_dossier_is_noop(tmp_path):
    # No wake evidence call ever happened for this citing work -- override
    # with verification_source=evidence-dossier should not blow up, and
    # should leave no evidence/ directory behind.
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    entry = report.add_override(
        seed_id, "W_NEVER_INVESTIGATED", relationship="extends", justification="x",
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
        base=tmp_path,
    )
    assert entry["relationship"] == "extends"
    assert not evidence_wiki.index_path(seed_id, base=tmp_path).exists()


# --- force reset -----------------------------------------------------------

def test_force_rerun_resets_verified_dossier_to_pending(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    citing_work = _classified_work(0)
    _build(tmp_path, citing_work=citing_work)

    report.add_override(
        seed_id, citing_id, relationship="extends", justification="confirmed",
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
        base=tmp_path,
    )
    assert evidence.load_dossier(seed_id, citing_id, base=tmp_path)["verification_status"] == "verified"

    _build(tmp_path, citing_work=citing_work, force=True)
    assert evidence.load_dossier(seed_id, citing_id, base=tmp_path)["verification_status"] == "pending-human-review"

    text = evidence_wiki.index_path(seed_id, base=tmp_path).read_text()
    assert "## Verified (0)" in text
    assert "## Pending Review (1)" in text

    log_text = evidence_wiki.log_path(seed_id, base=tmp_path).read_text()
    assert "dossier_rebuilt" in log_text
