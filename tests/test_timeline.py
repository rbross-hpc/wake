# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.timeline -- curated timeline periods (BACKLOG Theme G),
offline.

Mirrors the fixture/CLI conventions of test_themes.py/test_report.py:
build_candidates() (the read-only scored/dated/bucketed feed) is the
analog of report.build_metrics()/build_assessment(); create_period()/
confirm_period() are the analog of theme create/confirm; stitch() is the
analog of narrative.stitch().
"""
from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest

from wake import timeline
from wake.classify import save_classified
from wake.cli.main import main
from wake.evidence import dossier_json_path
from wake.exclude import exclude_work
from wake.io import atomic_write_json
from wake.report import add_override
from wake.seed import work_dir
from wake.state import mark_stage_complete

from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS


def _seed_cached(tmp_path):
    wd = work_dir(PARALLEL_NETCDF_WORK["openalex_id"], tmp_path)
    wd.mkdir(parents=True, exist_ok=True)
    atomic_write_json(wd / "seed.json", {**PARALLEL_NETCDF_WORK, "resolved_at": "2020-01-01T00:00:00"})
    mark_stage_complete(wd, "seed", seed_id=PARALLEL_NETCDF_WORK["openalex_id"], prompt_version="seed-1")


def _run_cli(argv, tmp_path, capsys):
    with patch.object(sys, "argv", ["wake", "--work-dir", str(tmp_path), *argv]):
        try:
            main()
            code = 0
        except SystemExit as exc:
            code = exc.code or 0
    return code, capsys.readouterr()


def _classified_work(idx: int, **overrides) -> dict:
    return {
        **SAMPLE_CITING_WORKS[idx],
        "relationship": "uses-method-from",
        "relationships": [{"label": "uses-method-from", "confidence": 0.8,
                            "justification": "x", "quotes": [], "verified": None}],
        "confidence": 0.8,
        "justification": "Uses PnetCDF for I/O.",
        "has_abstract": True,
        "verification_status": "provisional",
        "author_overlap": False,
        **overrides,
    }


def _write_dossier(seed_id, citing_id, base):
    p = dossier_json_path(seed_id, citing_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, {
        "schema_version": 1,
        "citing_openalex_id": citing_id,
        "seed_openalex_id": seed_id,
        "verification_status": "pending-human-review",
        "provisional": {}, "proposed": {}, "quotes": [],
    })


# --- build_candidates ----------------------------------------------------

def test_build_candidates_empty_when_no_classified(tmp_path):
    data = timeline.build_candidates(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert data["buckets"] == []
    assert data["undated_count"] == 0


def test_build_candidates_buckets_by_year(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    # SAMPLE_CITING_WORKS years: 2005, 2008, 2010
    works = [_classified_work(0), _classified_work(1), _classified_work(2)]
    save_classified(seed_id, works, base=tmp_path)

    data = timeline.build_candidates(PARALLEL_NETCDF_WORK, base=tmp_path)
    years = [b["bucket_start"] for b in data["buckets"]]
    assert years == [2005, 2008, 2010]
    assert all(b["bucket_start"] == b["bucket_end"] for b in data["buckets"])


def test_build_candidates_bucket_years_groups_windows(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    works = [_classified_work(0), _classified_work(1), _classified_work(2)]
    save_classified(seed_id, works, base=tmp_path)

    data = timeline.build_candidates(PARALLEL_NETCDF_WORK, base=tmp_path, bucket_years=5)
    # min year 2005 -> bucket 2005-2009 catches 2005, 2008; 2010-2014 catches 2010
    assert len(data["buckets"]) == 2
    assert data["buckets"][0]["bucket_start"] == 2005
    assert data["buckets"][0]["bucket_end"] == 2009
    assert data["buckets"][0]["count"] == 2
    assert data["buckets"][1]["bucket_start"] == 2010


def test_build_candidates_no_pre_selection_includes_all_relationships(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    weak = {**_classified_work(0), "relationship": "cites",
            "relationships": [{"label": "cites", "confidence": 0.5,
                                "justification": "x", "quotes": [], "verified": None}]}
    save_classified(seed_id, [weak], base=tmp_path)

    data = timeline.build_candidates(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert data["buckets"][0]["works"][0]["relationship"] == "cites"


def test_build_candidates_min_strength_filters(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    weak = {**_classified_work(0), "relationship": "cites",
            "relationships": [{"label": "cites", "confidence": 0.5,
                                "justification": "x", "quotes": [], "verified": None}]}
    strong = {**_classified_work(1), "relationship": "extends",
              "relationships": [{"label": "extends", "confidence": 0.9,
                                  "justification": "x", "quotes": [], "verified": None}]}
    save_classified(seed_id, [weak, strong], base=tmp_path)

    data = timeline.build_candidates(PARALLEL_NETCDF_WORK, base=tmp_path, min_strength=5)
    all_ids = [w["openalex_id"] for b in data["buckets"] for w in b["works"]]
    assert weak["openalex_id"] not in all_ids
    assert strong["openalex_id"] in all_ids


def test_build_candidates_since_until_filters(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    works = [_classified_work(0), _classified_work(1), _classified_work(2)]
    save_classified(seed_id, works, base=tmp_path)

    data = timeline.build_candidates(PARALLEL_NETCDF_WORK, base=tmp_path, since=2007, until=2009)
    years = [b["bucket_start"] for b in data["buckets"]]
    assert years == [2008]


def test_build_candidates_undated_work_excluded_and_counted(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    undated = {**_classified_work(0), "year": None}
    save_classified(seed_id, [undated], base=tmp_path)

    data = timeline.build_candidates(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert data["buckets"] == []
    assert data["undated_count"] == 1


def test_build_candidates_errored_work_excluded(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    errored = {"openalex_id": "W_ERR", "title": "Errored", "year": 2010, "error": "timeout"}
    save_classified(seed_id, [errored], base=tmp_path)

    data = timeline.build_candidates(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert data["buckets"] == []
    assert data["undated_count"] == 0


def test_build_candidates_reports_override_verification_and_exclusion_flags(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    verified_work = _classified_work(0)
    excluded_work = _classified_work(1)
    save_classified(seed_id, [verified_work, excluded_work], base=tmp_path)
    add_override(seed_id, verified_work["openalex_id"], relationship="extends", base=tmp_path)
    exclude_work(seed_id, excluded_work["openalex_id"], reason="Not relevant.", base=tmp_path)

    data = timeline.build_candidates(PARALLEL_NETCDF_WORK, base=tmp_path)
    all_works = {w["openalex_id"]: w for b in data["buckets"] for w in b["works"]}
    assert all_works[verified_work["openalex_id"]]["verification_status"] == "verified"
    assert all_works[excluded_work["openalex_id"]]["excluded"] is True
    assert data["excluded_count"] == 1


def test_build_candidates_confirmed_duplicate_counted(tmp_path):
    from wake.dedup import confirm_duplicate

    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    dup_work = _classified_work(0)
    canonical_work = {**_classified_work(1), "openalex_id": "W_CANON"}
    save_classified(seed_id, [dup_work, canonical_work], base=tmp_path)
    confirm_duplicate(seed_id, dup_work["openalex_id"], canonical_id="W_CANON", base=tmp_path)

    data = timeline.build_candidates(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert data["duplicate_count"] == 1
    all_works = {w["openalex_id"]: w for b in data["buckets"] for w in b["works"]}
    assert all_works[dup_work["openalex_id"]]["duplicate"] is True


def test_build_candidates_score_descending_within_bucket(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    low = {**_classified_work(2), "cited_by_count": 1, "year": 2005}
    high = {**_classified_work(0), "cited_by_count": 900, "year": 2005}
    save_classified(seed_id, [low, high], base=tmp_path)

    data = timeline.build_candidates(PARALLEL_NETCDF_WORK, base=tmp_path)
    ids = [w["openalex_id"] for w in data["buckets"][0]["works"]]
    assert ids == [high["openalex_id"], low["openalex_id"]]


# --- create_period: validation --------------------------------------------

def test_create_period_rejects_empty_highlights(tmp_path):
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [_classified_work(0)], base=tmp_path)
    with pytest.raises(ValueError, match="must not be empty"):
        timeline.create_period(
            PARALLEL_NETCDF_WORK, "2005", highlight_ids=[], base=tmp_path,
        )


def test_create_period_rejects_invalid_slug(tmp_path):
    works = [_classified_work(0)]
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], works, base=tmp_path)
    with pytest.raises(ValueError, match="Invalid slug"):
        timeline.create_period(
            PARALLEL_NETCDF_WORK, "Not A Slug!", highlight_ids=[works[0]["openalex_id"]], base=tmp_path,
        )


def test_create_period_rejects_unclassified_highlight(tmp_path):
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [], base=tmp_path)
    with pytest.raises(ValueError, match="never been classified"):
        timeline.create_period(
            PARALLEL_NETCDF_WORK, "2005", highlight_ids=["W_NEVER_CLASSIFIED"], base=tmp_path,
        )


def test_create_period_rejects_excluded_highlight(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)
    exclude_work(seed_id, work["openalex_id"], reason="Not about the seed.", base=tmp_path)

    with pytest.raises(ValueError, match="excluded work"):
        timeline.create_period(
            PARALLEL_NETCDF_WORK, "2005", highlight_ids=[work["openalex_id"]], base=tmp_path,
        )


def test_create_period_rejects_confirmed_duplicate_highlight(tmp_path):
    from wake.dedup import confirm_duplicate

    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    dup_work = _classified_work(0)
    canonical_work = {**_classified_work(1), "openalex_id": "W_CANON"}
    save_classified(seed_id, [dup_work, canonical_work], base=tmp_path)
    confirm_duplicate(seed_id, dup_work["openalex_id"], canonical_id="W_CANON", base=tmp_path)

    with pytest.raises(ValueError, match="confirmed duplicate"):
        timeline.create_period(
            PARALLEL_NETCDF_WORK, "2005", highlight_ids=[dup_work["openalex_id"]], base=tmp_path,
        )


# --- create_period: emergent vs named span ---------------------------------

def test_create_period_bare_year_slug_defaults_range(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0, year=2012)
    save_classified(seed_id, [work], base=tmp_path)

    timeline.create_period(PARALLEL_NETCDF_WORK, "2012", highlight_ids=[work["openalex_id"]], base=tmp_path)
    period = timeline.load_period(seed_id, "2012", tmp_path)
    assert period["from_year"] == 2012
    assert period["to_year"] == 2012
    assert period.get("label") is None


def test_create_period_named_span_keeps_explicit_range(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)

    timeline.create_period(
        PARALLEL_NETCDF_WORK, "early-adoption", highlight_ids=[work["openalex_id"]],
        label="Early adoption", from_year=2003, to_year=2007, note="Initial uptake.",
        base=tmp_path,
    )
    period = timeline.load_period(seed_id, "early-adoption", tmp_path)
    assert period["label"] == "Early adoption"
    assert period["from_year"] == 2003
    assert period["to_year"] == 2007
    assert period["note"] == "Initial uptake."


def test_create_period_always_writes_draft(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)

    result = timeline.create_period(PARALLEL_NETCDF_WORK, "2005", highlight_ids=[work["openalex_id"]], base=tmp_path)
    assert result["ok"] is True
    assert result["period_status"] == "draft"


def test_create_period_highlight_status_and_notes(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    verified = _classified_work(0)
    proposed = _classified_work(1)
    provisional = _classified_work(2)
    save_classified(seed_id, [verified, proposed, provisional], base=tmp_path)
    add_override(seed_id, verified["openalex_id"], relationship="extends", base=tmp_path)
    _write_dossier(seed_id, proposed["openalex_id"], tmp_path)

    result = timeline.create_period(
        PARALLEL_NETCDF_WORK, "mixed",
        highlight_ids=[verified["openalex_id"], proposed["openalex_id"], provisional["openalex_id"]],
        from_year=2005, to_year=2010,
        highlight_notes={verified["openalex_id"]: "First major reuse."},
        base=tmp_path,
    )
    by_id = {h["citing_id"]: h for h in result["highlights"]}
    assert by_id[verified["openalex_id"]]["status"] == "verified"
    assert by_id[verified["openalex_id"]]["note"] == "First major reuse."
    assert by_id[proposed["openalex_id"]]["status"] == "proposed"
    assert by_id[proposed["openalex_id"]]["has_dossier"] is True
    assert by_id[provisional["openalex_id"]]["status"] == "provisional"
    assert by_id[provisional["openalex_id"]]["note"] is None


def test_create_period_overwrite_preserves_created_at(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)

    timeline.create_period(PARALLEL_NETCDF_WORK, "2005", highlight_ids=[work["openalex_id"]], base=tmp_path)
    first = timeline.load_period(seed_id, "2005", tmp_path)

    timeline.create_period(PARALLEL_NETCDF_WORK, "2005", highlight_ids=[work["openalex_id"]], note="updated", base=tmp_path)
    second = timeline.load_period(seed_id, "2005", tmp_path)

    assert second["created_at"] == first["created_at"]
    assert second["note"] == "updated"


# --- confirm_period ---------------------------------------------------------

def test_confirm_period_raises_if_not_found(tmp_path):
    with pytest.raises(ValueError, match="No timeline period"):
        timeline.confirm_period(PARALLEL_NETCDF_WORK, "nope", base=tmp_path)


def test_confirm_period_blocked_by_unverified_highlight(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)
    timeline.create_period(PARALLEL_NETCDF_WORK, "2005", highlight_ids=[work["openalex_id"]], base=tmp_path)

    result = timeline.confirm_period(PARALLEL_NETCDF_WORK, "2005", base=tmp_path)
    assert result["ok"] is False
    assert result["reason"] == "unverified_works"
    assert work["openalex_id"] in result["unverified"]


def test_confirm_period_succeeds_when_all_verified(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)
    add_override(seed_id, work["openalex_id"], relationship="extends", base=tmp_path)
    timeline.create_period(PARALLEL_NETCDF_WORK, "2005", highlight_ids=[work["openalex_id"]], base=tmp_path)

    result = timeline.confirm_period(PARALLEL_NETCDF_WORK, "2005", base=tmp_path)
    assert result["ok"] is True
    assert result["period_status"] == "confirmed"

    period = timeline.load_period(seed_id, "2005", tmp_path)
    assert period["period_status"] == "confirmed"
    assert period["confirmed_at"] is not None


def test_confirm_period_re_resolves_fresh_verification(tmp_path):
    """A work verified AFTER the period was created still counts --
    confirm_period() re-resolves status fresh, not from the period's own
    possibly-stale JSON (same rule as confirm_theme())."""
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)
    timeline.create_period(PARALLEL_NETCDF_WORK, "2005", highlight_ids=[work["openalex_id"]], base=tmp_path)

    blocked = timeline.confirm_period(PARALLEL_NETCDF_WORK, "2005", base=tmp_path)
    assert blocked["ok"] is False

    add_override(seed_id, work["openalex_id"], relationship="extends", base=tmp_path)
    result = timeline.confirm_period(PARALLEL_NETCDF_WORK, "2005", base=tmp_path)
    assert result["ok"] is True


# --- stitch ------------------------------------------------------------

def test_stitch_no_periods_returns_not_ok(tmp_path):
    result = timeline.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert result["ok"] is False


def test_stitch_chronological_order(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    works = [_classified_work(0), _classified_work(1), _classified_work(2)]
    save_classified(seed_id, works, base=tmp_path)

    timeline.create_period(PARALLEL_NETCDF_WORK, "2010", highlight_ids=[works[2]["openalex_id"]], base=tmp_path)
    timeline.create_period(PARALLEL_NETCDF_WORK, "2005", highlight_ids=[works[0]["openalex_id"]], base=tmp_path)
    timeline.create_period(PARALLEL_NETCDF_WORK, "2008", highlight_ids=[works[1]["openalex_id"]], base=tmp_path)

    result = timeline.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert result["ok"] is True
    md_text = (work_dir(seed_id, tmp_path) / "timeline.md").read_text()
    assert md_text.index("2005") < md_text.index("2008") < md_text.index("2010")


def test_stitch_confirmed_vs_draft_counts_and_json_only_confirmed(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    verified_work = _classified_work(0)
    provisional_work = _classified_work(1)
    save_classified(seed_id, [verified_work, provisional_work], base=tmp_path)
    add_override(seed_id, verified_work["openalex_id"], relationship="extends", base=tmp_path)

    timeline.create_period(
        PARALLEL_NETCDF_WORK, "confirmed-period", highlight_ids=[verified_work["openalex_id"]],
        from_year=2005, to_year=2005, base=tmp_path,
    )
    timeline.confirm_period(PARALLEL_NETCDF_WORK, "confirmed-period", base=tmp_path)

    timeline.create_period(
        PARALLEL_NETCDF_WORK, "draft-period", highlight_ids=[provisional_work["openalex_id"]],
        from_year=2008, to_year=2008, base=tmp_path,
    )

    result = timeline.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert result["confirmed_count"] == 1
    assert result["draft_count"] == 1

    json_path = work_dir(seed_id, tmp_path) / "timeline.json"
    data = json.loads(json_path.read_text())
    slugs = [p["slug"] for p in data["periods"]]
    assert slugs == ["confirmed-period"]


def test_stitch_reports_overlaps_without_blocking(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    works = [_classified_work(0), _classified_work(1)]
    save_classified(seed_id, works, base=tmp_path)

    timeline.create_period(
        PARALLEL_NETCDF_WORK, "a", highlight_ids=[works[0]["openalex_id"]],
        from_year=2000, to_year=2010, base=tmp_path,
    )
    timeline.create_period(
        PARALLEL_NETCDF_WORK, "b", highlight_ids=[works[1]["openalex_id"]],
        from_year=2005, to_year=2015, base=tmp_path,
    )

    result = timeline.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    assert result["ok"] is True
    assert len(result["overlaps"]) == 1
    assert {result["overlaps"][0]["a"], result["overlaps"][0]["b"]} == {"a", "b"}


def test_stitch_writes_frontmatter(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)
    timeline.create_period(PARALLEL_NETCDF_WORK, "2005", highlight_ids=[work["openalex_id"]], base=tmp_path)

    timeline.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)
    md_text = (work_dir(seed_id, tmp_path) / "timeline.md").read_text()
    assert "type: timeline" in md_text
    assert "confirmed_periods: 0" in md_text
    assert "draft_periods: 1" in md_text


# --- rerender_all_periods ---------------------------------------------------

def test_rerender_all_periods_writes_md_from_json(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)
    timeline.create_period(
        PARALLEL_NETCDF_WORK, "early-adoption", highlight_ids=[work["openalex_id"]],
        label="Early adoption", from_year=2003, to_year=2007, base=tmp_path,
    )

    rerendered = timeline.rerender_all_periods(seed_id, PARALLEL_NETCDF_WORK, base=tmp_path)
    assert rerendered == ["early-adoption"]
    md_path = timeline.period_md_path(seed_id, "early-adoption", tmp_path)
    assert md_path.exists()
    assert "Early adoption" in md_path.read_text()


# --- CLI -----------------------------------------------------------------

def test_timeline_candidates_cli_json(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work(0)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)

    code, captured = _run_cli(["--json", "timeline", "candidates", PARALLEL_NETCDF_WORK["openalex_id"]], tmp_path, capsys)
    assert code == 0
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert len(data["data"]["buckets"]) == 1


def test_timeline_period_create_and_confirm_cli(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work(0)
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    save_classified(seed_id, [work], base=tmp_path)

    code, captured = _run_cli(
        ["--json", "timeline", "period", "create", seed_id, "2005",
         "--highlights", work["openalex_id"]],
        tmp_path, capsys,
    )
    assert code == 0
    data = json.loads(captured.out)
    assert data["data"]["period_status"] == "draft"

    code, captured = _run_cli(
        ["timeline", "period", "confirm", seed_id, "2005"], tmp_path, capsys,
    )
    assert code == 1
    assert "not yet human-verified" in captured.out

    add_override(seed_id, work["openalex_id"], relationship="extends", base=tmp_path)
    code, captured = _run_cli(
        ["timeline", "period", "confirm", seed_id, "2005"], tmp_path, capsys,
    )
    assert code == 0
    assert "Period confirmed" in captured.out


def test_timeline_stitch_and_show_cli(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work(0)
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    save_classified(seed_id, [work], base=tmp_path)
    timeline.create_period(PARALLEL_NETCDF_WORK, "2005", highlight_ids=[work["openalex_id"]], base=tmp_path)

    code, captured = _run_cli(["timeline", "stitch", seed_id], tmp_path, capsys)
    assert code == 0
    assert "Timeline written" in captured.out

    code, captured = _run_cli(["timeline", "show", seed_id], tmp_path, capsys)
    assert code == 0
    assert "Timeline:" in captured.out


def test_timeline_show_cli_errors_when_no_periods(tmp_path, capsys):
    _seed_cached(tmp_path)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [], base=tmp_path)

    code, captured = _run_cli(["timeline", "show", PARALLEL_NETCDF_WORK["openalex_id"]], tmp_path, capsys)
    assert code == 1
    assert "No timeline found" in captured.err
