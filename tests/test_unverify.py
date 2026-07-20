# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.unverify — first-class undo for a mistaken verification
(BACKLOG Theme J item 11), offline.

Covers both cases: a plain human-judgment override (no evidence dossier
behind it -- unverifying just removes the overrides.jsonl entry) and an
evidence-dossier-backed override (unverifying also patches the dossier
back to pending-human-review, undoing any relationship correction the
reverted verification made).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from wake import evidence, evidence_wiki, report, unverify
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


def _build_dossier(tmp_path, citing_work=None, pdf_name="citing.pdf", relationship="extends"):
    pdf_copy = _copy_fixture_pdf(tmp_path, pdf_name)
    citing_work = citing_work or _classified_work()
    fake_response = {
        "relationship": relationship, "confidence": 0.9,
        "justification": "The full text clearly shows a direct extension of the seed's method.",
        "agrees_with_provisional": False,
        "quotes": [{"page": 2, "text": "We directly extend the seed's method here.", "note": "x"}],
    }
    with patch("wake.evidence.fetch_pdf", return_value={"ok": True, "path": str(pdf_copy), "source": "osti"}), \
         patch("wake.evidence.chat_json", return_value=fake_response):
        return evidence.build_dossier(PARALLEL_NETCDF_WORK, citing_work, base=tmp_path, verbose=False)


# --- report.remove_override ------------------------------------------------

def test_remove_override_returns_false_when_none_exists(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    assert report.remove_override(seed_id, "W_NEVER_VERIFIED", base=tmp_path) is False


def test_remove_override_removes_entry(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    report.add_override(seed_id, "W1", relationship="extends", justification="x", base=tmp_path)
    removed = report.remove_override(seed_id, "W1", base=tmp_path)
    assert removed is True
    assert "W1" not in report.load_overrides(seed_id, base=tmp_path)


def test_remove_override_only_removes_matching_id(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    report.add_override(seed_id, "W1", relationship="extends", justification="x", base=tmp_path)
    report.add_override(seed_id, "W2", relationship="uses-as-tool", justification="y", base=tmp_path)
    report.remove_override(seed_id, "W1", base=tmp_path)

    overrides = report.load_overrides(seed_id, base=tmp_path)
    assert "W1" not in overrides
    assert "W2" in overrides


def test_remove_override_handles_multiple_prior_entries_for_same_id(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    report.add_override(seed_id, "W1", relationship="extends", justification="first", base=tmp_path)
    report.add_override(seed_id, "W1", relationship="uses-as-tool", justification="second", base=tmp_path)
    removed = report.remove_override(seed_id, "W1", base=tmp_path)
    assert removed is True
    assert "W1" not in report.load_overrides(seed_id, base=tmp_path)


# --- evidence_wiki.mark_pending --------------------------------------------

def test_mark_pending_missing_dossier_returns_false(tmp_path):
    assert evidence_wiki.mark_pending(PARALLEL_NETCDF_WORK["openalex_id"], "W_NO_DOSSIER", base=tmp_path) is False


def test_mark_pending_reverts_status(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    _build_dossier(tmp_path, citing_work=_classified_work(0))
    evidence_wiki.mark_verified(seed_id, citing_id, justification="accepted", relationship="extends", base=tmp_path)

    ok = evidence_wiki.mark_pending(seed_id, citing_id, reason="was a mistake", base=tmp_path)
    assert ok is True

    loaded = evidence.load_dossier(seed_id, citing_id, base=tmp_path)
    assert loaded["verification_status"] == "pending-human-review"
    assert "human_verification" not in loaded

    md_text = evidence.dossier_path(seed_id, citing_id, base=tmp_path).read_text()
    assert "status:pending-human-review" in md_text
    assert "## Status: pending your review" in md_text


def test_mark_pending_undoes_relationship_correction(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    _build_dossier(tmp_path, citing_work=_classified_work(0), relationship="extends")
    evidence_wiki.mark_verified(
        seed_id, citing_id, justification="corrected", relationship="uses-as-tool", base=tmp_path,
    )
    loaded = evidence.load_dossier(seed_id, citing_id, base=tmp_path)
    assert loaded["proposed"]["relationship"] == "uses-as-tool"

    evidence_wiki.mark_pending(seed_id, citing_id, base=tmp_path)

    loaded = evidence.load_dossier(seed_id, citing_id, base=tmp_path)
    assert loaded["proposed"]["relationship"] == "extends"
    assert "model_relationship" not in loaded["proposed"]
    assert "model_justification" not in loaded["proposed"]

    md_text = evidence.dossier_path(seed_id, citing_id, base=tmp_path).read_text()
    assert "proposed:extends" in md_text
    assert "proposed:uses-as-tool" not in md_text


# --- unverify_work -----------------------------------------------------

def test_unverify_work_requires_prior_verification(tmp_path):
    with pytest.raises(ValueError, match="not currently verified"):
        unverify.unverify_work(PARALLEL_NETCDF_WORK, "W_NEVER_VERIFIED", base=tmp_path)


def test_unverify_work_plain_human_judgment_no_dossier(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    report.add_override(seed_id, "W1", relationship="extends", justification="x", base=tmp_path)

    result = unverify.unverify_work(PARALLEL_NETCDF_WORK, "W1", reason="mistake", base=tmp_path)
    assert result["ok"] is True
    assert result["had_dossier"] is False
    assert "W1" not in report.load_overrides(seed_id, base=tmp_path)


def test_unverify_work_with_dossier_reverts_it(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    _build_dossier(tmp_path, citing_work=_classified_work(0))
    report.add_override(
        seed_id, citing_id, relationship="extends", justification="accepted",
        base=tmp_path, verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )

    result = unverify.unverify_work(PARALLEL_NETCDF_WORK, citing_id, reason="was a mistake", base=tmp_path)
    assert result["ok"] is True
    assert result["had_dossier"] is True

    loaded = evidence.load_dossier(seed_id, citing_id, base=tmp_path)
    assert loaded["verification_status"] == "pending-human-review"
    assert citing_id not in report.load_overrides(seed_id, base=tmp_path)


def test_unverify_work_writes_log_entry(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    report.add_override(seed_id, "W1", relationship="extends", justification="x", base=tmp_path)
    unverify.unverify_work(PARALLEL_NETCDF_WORK, "W1", reason="misread bulk go-ahead", base=tmp_path)

    log_text = evidence_wiki.log_path(seed_id, base=tmp_path).read_text()
    assert "verification_reverted" in log_text
    assert "misread bulk go-ahead" in log_text
    assert "W1" in log_text


def test_unverify_work_default_reason_matches_ad_hoc_format(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    report.add_override(seed_id, "W1", relationship="extends", justification="x", base=tmp_path)
    unverify.unverify_work(PARALLEL_NETCDF_WORK, "W1", base=tmp_path)

    log_text = evidence_wiki.log_path(seed_id, base=tmp_path).read_text()
    assert "the prior verified_by_human entry for this work was recorded without" in log_text


# --- unverify_batch ------------------------------------------------------

def test_unverify_batch_requires_exactly_one_of_since_or_last(tmp_path):
    with pytest.raises(ValueError, match="Exactly one of"):
        unverify.unverify_batch(PARALLEL_NETCDF_WORK, base=tmp_path)
    with pytest.raises(ValueError, match="Exactly one of"):
        unverify.unverify_batch(PARALLEL_NETCDF_WORK, since="2024-01-01T00:00:00", last=5, base=tmp_path)


def test_unverify_batch_rejects_non_positive_last(tmp_path):
    with pytest.raises(ValueError, match="positive integer"):
        unverify.unverify_batch(PARALLEL_NETCDF_WORK, last=0, base=tmp_path)


def test_unverify_batch_last_n(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    for cid in ["W1", "W2", "W3", "W4"]:
        report.add_override(seed_id, cid, relationship="extends", justification="x", base=tmp_path)

    result = unverify.unverify_batch(PARALLEL_NETCDF_WORK, last=2, reason="bulk mistake", base=tmp_path)
    assert result["ok"] is True
    assert result["count"] == 2

    remaining = report.load_overrides(seed_id, base=tmp_path)
    assert set(remaining.keys()) == {"W1", "W2"}


def test_unverify_batch_since_timestamp(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    report.add_override(seed_id, "W_OLD", relationship="extends", justification="x", base=tmp_path)

    cutoff = "2099-01-01T00:00:00+00:00"
    with patch("wake.report.now_iso", return_value=cutoff):
        report.add_override(seed_id, "W_NEW", relationship="extends", justification="y", base=tmp_path)

    result = unverify.unverify_batch(PARALLEL_NETCDF_WORK, since=cutoff, reason="bulk mistake", base=tmp_path)
    assert result["count"] == 1
    assert result["reverted"][0]["citing_id"] == "W_NEW"

    remaining = report.load_overrides(seed_id, base=tmp_path)
    assert "W_OLD" in remaining
    assert "W_NEW" not in remaining


def test_unverify_batch_no_matches_returns_empty(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    report.add_override(seed_id, "W1", relationship="extends", justification="x", base=tmp_path)

    result = unverify.unverify_batch(
        PARALLEL_NETCDF_WORK, since="2099-01-01T00:00:00+00:00", reason="x", base=tmp_path,
    )
    assert result["count"] == 0
