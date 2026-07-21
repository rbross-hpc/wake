# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.missing_pdfs and the fetch-attempt log entries written by
wake.pdf_fetch (BACKLOG deferred item A), offline."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from wake import missing_pdfs
from wake.classify import save_classified
from wake.cli.main import main
from wake.evidence_wiki import append_log_entry, log_path
from wake.io import atomic_write_json
from wake.pdf_fetch import pdf_path, fetch_pdf
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


def _classified_work(idx: int = 0, **overrides) -> dict:
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


# --- log-parsing helpers ---------------------------------------------------

def test_parse_log_events_empty_when_no_log(tmp_path):
    events = missing_pdfs._parse_log_events(PARALLEL_NETCDF_WORK["openalex_id"], tmp_path)
    assert events == {}


def test_parse_log_events_ignores_non_pdf_events(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    append_log_entry(seed_id, event="dossier_built", citing_id="W1", detail="proposed: extends", base=tmp_path)
    events = missing_pdfs._parse_log_events(seed_id, tmp_path)
    assert events == {}


def test_parse_log_events_reads_pdf_fetch_failed(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    append_log_entry(seed_id, event="pdf_fetch_failed", citing_id="W1",
                     detail="tried: osti, semanticscholar", base=tmp_path)
    events = missing_pdfs._parse_log_events(seed_id, tmp_path)
    assert "W1" in events
    assert events["W1"]["event"] == "pdf_fetch_failed"
    assert "osti" in events["W1"]["detail"]


def test_parse_log_events_reads_pdf_fetched(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    append_log_entry(seed_id, event="pdf_fetched", citing_id="W1",
                     detail="via osti", base=tmp_path)
    events = missing_pdfs._parse_log_events(seed_id, tmp_path)
    assert events["W1"]["event"] == "pdf_fetched"


def test_parse_log_events_last_write_wins(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    append_log_entry(seed_id, event="pdf_fetch_failed", citing_id="W1",
                     detail="tried: osti", base=tmp_path)
    append_log_entry(seed_id, event="pdf_fetched", citing_id="W1",
                     detail="via semanticscholar", base=tmp_path)
    events = missing_pdfs._parse_log_events(seed_id, tmp_path)
    assert events["W1"]["event"] == "pdf_fetched"


# --- pdf_fetch logs events -------------------------------------------------

def test_fetch_pdf_logs_failure_event(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.unpaywall.get_oa_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.springer.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.core.is_enabled", return_value=False), \
         patch("wake.pdf_fetch.time.sleep"):
        result = fetch_pdf(seed_id, "W1", doi="10.1234/fake", title=None,
                           seed_title="Parallel netCDF", base=tmp_path, verbose=False)

    assert result["ok"] is False
    events = missing_pdfs._parse_log_events(seed_id, tmp_path)
    assert "W1" in events
    assert events["W1"]["event"] == "pdf_fetch_failed"


def test_fetch_pdf_logs_success_event(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 " + b"x" * 3000)

    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value="http://example.com/fake.pdf"), \
         patch("wake.pdf_fetch.requests.get") as mock_get, \
         patch("wake.pdf_fetch.time.sleep"):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"%PDF-1.4 " + b"x" * 3000
        result = fetch_pdf(seed_id, "W_FETCH_OK", doi="10.1234/fake",
                           seed_title="Parallel netCDF", base=tmp_path, verbose=False)

    assert result["ok"] is True
    events = missing_pdfs._parse_log_events(seed_id, tmp_path)
    assert events["W_FETCH_OK"]["event"] == "pdf_fetched"
    assert "osti" in events["W_FETCH_OK"]["detail"]


def test_fetch_pdf_cache_hit_does_not_log(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    dest = pdf_path(seed_id, "W_CACHED", tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-1.4 " + b"x" * 3000)

    fetch_pdf(seed_id, "W_CACHED", doi="10.1234/fake", base=tmp_path, verbose=False)

    p = log_path(seed_id, tmp_path)
    assert not p.exists()


# --- list_missing_pdfs -----------------------------------------------------

def test_list_missing_pdfs_never_attempted(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)

    results = missing_pdfs.list_missing_pdfs(seed_id, base=tmp_path)
    assert len(results) == 1
    assert results[0]["citing_id"] == work["openalex_id"]
    assert results[0]["fetch_state"] == "never-attempted"
    assert results[0]["sources_tried"] == []


def test_list_missing_pdfs_exhausted(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)
    append_log_entry(seed_id, event="pdf_fetch_failed", citing_id=work["openalex_id"],
                     detail="tried: osti, semanticscholar", base=tmp_path)

    results = missing_pdfs.list_missing_pdfs(seed_id, base=tmp_path)
    assert results[0]["fetch_state"] == "exhausted"
    assert "osti" in results[0]["sources_tried"]


def test_list_missing_pdfs_fetched_but_gone(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)
    append_log_entry(seed_id, event="pdf_fetched", citing_id=work["openalex_id"],
                     detail="via osti", base=tmp_path)

    results = missing_pdfs.list_missing_pdfs(seed_id, base=tmp_path)
    assert results[0]["fetch_state"] == "fetched-but-gone"


def test_list_missing_pdfs_excludes_cached(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)

    dest = pdf_path(seed_id, work["openalex_id"], tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-1.4 " + b"x" * 3000)

    results = missing_pdfs.list_missing_pdfs(seed_id, base=tmp_path)
    assert results == []


def test_list_missing_pdfs_excludes_excluded_work(tmp_path):
    from wake.exclude import exclude_work
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0)
    save_classified(seed_id, [work], base=tmp_path)
    exclude_work(seed_id, work["openalex_id"], reason="Not relevant.", base=tmp_path)

    results = missing_pdfs.list_missing_pdfs(seed_id, base=tmp_path)
    assert results == []


def test_list_missing_pdfs_sorted_by_cited_by(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    w0 = _classified_work(0, cited_by_count=10)
    w1 = _classified_work(1, cited_by_count=500)
    w2 = _classified_work(2, cited_by_count=100)
    save_classified(seed_id, [w0, w1, w2], base=tmp_path)

    results = missing_pdfs.list_missing_pdfs(seed_id, base=tmp_path)
    assert [r["cited_by_count"] for r in results] == [500, 100, 10]


def test_list_missing_pdfs_min_cited_by_filter(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    w0 = _classified_work(0, cited_by_count=10)
    w1 = _classified_work(1, cited_by_count=500)
    save_classified(seed_id, [w0, w1], base=tmp_path)

    results = missing_pdfs.list_missing_pdfs(seed_id, base=tmp_path, min_cited_by_count=50)
    assert len(results) == 1
    assert results[0]["cited_by_count"] == 500


def test_list_missing_pdfs_limit(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    works = [_classified_work(i) for i in range(3)]
    save_classified(seed_id, works, base=tmp_path)

    results = missing_pdfs.list_missing_pdfs(seed_id, base=tmp_path, limit=2)
    assert len(results) == 2


# --- CLI -------------------------------------------------------------------

def test_missing_pdfs_cli_no_results(tmp_path, capsys):
    _seed_cached(tmp_path)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [], base=tmp_path)

    code, captured = _run_cli(
        ["missing-pdfs", PARALLEL_NETCDF_WORK["openalex_id"]], tmp_path, capsys,
    )
    assert code == 0
    assert "No classified works" in captured.out


def test_missing_pdfs_cli_json(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work(0)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)

    code, captured = _run_cli(
        ["--json", "missing-pdfs", PARALLEL_NETCDF_WORK["openalex_id"]], tmp_path, capsys,
    )
    assert code == 0
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["data"]["count"] == 1
    assert data["data"]["missing"][0]["fetch_state"] == "never-attempted"
