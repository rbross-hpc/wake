# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.exclude — first-class, explicit exclusion of a citing
work (BACKLOG Theme J item 10), offline."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from wake import exclude, narrative, themes
from wake.classify import save_classified
from wake.report import add_override, bake_and_save
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


def _build_dossier_for(tmp_path, citing_work, pdf_name="citing.pdf"):
    dest = tmp_path / "pdfs" / pdf_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_FIXTURE, dest)
    fake_response = {
        "relationship": "extends", "confidence": 0.9, "justification": "j",
        "agrees_with_provisional": False,
        "quotes": [{"page": 2, "text": "We directly extend the seed's method here.", "note": "x"}],
    }
    from wake import evidence
    with patch("wake.evidence.fetch_pdf", return_value={"ok": True, "path": str(dest), "source": "osti"}), \
         patch("wake.evidence.chat_json", return_value=fake_response):
        return evidence.build_dossier(PARALLEL_NETCDF_WORK, citing_work, base=tmp_path, verbose=False)


# --- exclude_work / unexclude_work --------------------------------------

def test_exclude_work_requires_reason(tmp_path):
    with pytest.raises(ValueError, match="reason must not be empty"):
        exclude.exclude_work(PARALLEL_NETCDF_WORK["openalex_id"], "W1", reason="", base=tmp_path)


def test_exclude_work_requires_valid_category(tmp_path):
    with pytest.raises(ValueError, match="category must be one of"):
        exclude.exclude_work(
            PARALLEL_NETCDF_WORK["openalex_id"], "W1", reason="not relevant",
            category="bogus-category", base=tmp_path,
        )


def test_exclude_work_writes_entry(tmp_path):
    result = exclude.exclude_work(
        PARALLEL_NETCDF_WORK["openalex_id"], "W1",
        reason="Only mentions the seed in its bibliography.",
        category="not-about-seed", base=tmp_path,
    )
    assert result["ok"] is True
    exclusions = exclude.load_exclusions(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert exclude.is_excluded("W1", exclusions) is True


def test_is_excluded_false_for_unknown_work(tmp_path):
    exclusions = exclude.load_exclusions(PARALLEL_NETCDF_WORK["openalex_id"], base=tmp_path)
    assert exclude.is_excluded("W_NEVER_SEEN", exclusions) is False


def test_unexclude_work_requires_reason(tmp_path):
    exclude.exclude_work(PARALLEL_NETCDF_WORK["openalex_id"], "W1", reason="x", base=tmp_path)
    with pytest.raises(ValueError, match="reason must not be empty"):
        exclude.unexclude_work(PARALLEL_NETCDF_WORK["openalex_id"], "W1", reason="", base=tmp_path)


def test_unexclude_work_requires_prior_exclusion(tmp_path):
    with pytest.raises(ValueError, match="not currently excluded"):
        exclude.unexclude_work(
            PARALLEL_NETCDF_WORK["openalex_id"], "W_NEVER_EXCLUDED", reason="mistake", base=tmp_path,
        )


def test_unexclude_work_reverses_exclusion(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    exclude.exclude_work(seed_id, "W1", reason="x", base=tmp_path)
    result = exclude.unexclude_work(seed_id, "W1", reason="Was a mistake -- it's actually relevant.", base=tmp_path)
    assert result["ok"] is True

    exclusions = exclude.load_exclusions(seed_id, base=tmp_path)
    assert exclude.is_excluded("W1", exclusions) is False


def test_last_write_wins_across_exclude_and_unexclude(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    exclude.exclude_work(seed_id, "W1", reason="x", base=tmp_path)
    exclude.unexclude_work(seed_id, "W1", reason="undo", base=tmp_path)
    exclude.exclude_work(seed_id, "W1", reason="re-excluded", base=tmp_path)

    exclusions = exclude.load_exclusions(seed_id, base=tmp_path)
    assert exclude.is_excluded("W1", exclusions) is True
    assert exclusions["W1"]["reason"] == "re-excluded"


# --- downstream exclusion: bake / theme / narrative / gaps / queue ------

def test_bake_excludes_excluded_work_from_reach_metrics(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    works = [_classified_work(0), _classified_work(1)]
    exclude.exclude_work(seed_id, works[0]["openalex_id"], reason="Not about the seed.", base=tmp_path)

    json_path, md_path = bake_and_save(PARALLEL_NETCDF_WORK, works, base=tmp_path, verbose=False)
    metrics = json.loads(json_path.read_text())
    assert metrics["total_citing_works"] == 1


def test_theme_create_refuses_excluded_work(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    works = [_classified_work(0)]
    save_classified(seed_id, works, base=tmp_path)
    exclude.exclude_work(seed_id, works[0]["openalex_id"], reason="Not about the seed.", base=tmp_path)

    with pytest.raises(ValueError, match="excluded"):
        themes.create_theme(
            PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
            citing_ids=[works[0]["openalex_id"]], base=tmp_path,
        )


def test_narrative_section_refuses_excluded_ref(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)
    _build_dossier_for(tmp_path, work, pdf_name="w.pdf")
    add_override(
        seed_id, work["openalex_id"],
        relationship="extends", justification="accepted", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    # Verified first, then excluded -- the realistic sequence: a human
    # notices after the fact that a verified work shouldn't count.
    exclude.exclude_work(seed_id, work["openalex_id"], reason="On reflection, background-mention only.", base=tmp_path)

    with pytest.raises(ValueError, match="excluded"):
        narrative.create_section(
            PARALLEL_NETCDF_WORK, "s1", title="S",
            prose=f"Some claim. [ref:{work['openalex_id']}]", base=tmp_path,
        )


def test_gaps_does_not_surface_excluded_work(tmp_path):
    from wake.gaps import find_gaps

    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = {**_classified_work(0), "abstract": None, "cited_by_count": 999}
    exclude.exclude_work(seed_id, work["openalex_id"], reason="Not about the seed.", base=tmp_path)

    gaps = find_gaps([work], seed_id=seed_id, base=tmp_path, min_cited_by_count=1, try_auto_backfill=False)
    assert gaps == []


def test_theme_queue_does_not_surface_excluded_work(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    works = [_classified_work(0), _classified_work(1)]
    save_classified(seed_id, works, base=tmp_path)
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[w["openalex_id"] for w in works], base=tmp_path,
    )
    # Exclude one of the theme's needs_evidence works *after* the theme
    # was created -- list_theme_needs_evidence must filter it out fresh,
    # not rely on create_theme() having refused it upfront (it wasn't
    # excluded yet at creation time).
    exclude.exclude_work(seed_id, works[0]["openalex_id"], reason="On reflection, not relevant.", base=tmp_path)

    entries = themes.list_theme_needs_evidence(seed_id, base=tmp_path)
    surfaced_ids = {e["citing_id"] for e in entries}
    assert works[0]["openalex_id"] not in surfaced_ids
    assert works[1]["openalex_id"] in surfaced_ids
