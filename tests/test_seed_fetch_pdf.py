# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake seed PDF acquisition (wake seed fetch-pdf):
- fetch_seed_pdf core: cache hit, first-source hit, chain exhaustion.
- acquire_seed_pdf: seed.json gets seed_pdf sub-object on success/failure.
- Extraction: runs after fetch, failure recorded gracefully.
- --from-pdf: match / mismatch / --force override + logging.
- Auto-attempt at resolve time: silent success and silent failure.
- CLI shape: wake seed fetch-pdf.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from wake import seed_pdf as seed_pdf_mod
from wake.cli.main import main
from wake.evidence_wiki import log_path
from wake.io import atomic_write_json
from wake.pdf_fetch import fetch_seed_pdf, seed_pdf_path
from wake.seed import load_seed, work_dir
from wake.seed_pdf import acquire_seed_pdf, acquire_seed_pdf_from_path
from wake.state import mark_stage_complete
from .conftest import PARALLEL_NETCDF_WORK

_FIXTURE = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"

_SEED = PARALLEL_NETCDF_WORK


def _seed_cached(tmp_path, seed=None):
    s = seed or _SEED
    wd = work_dir(s["openalex_id"], tmp_path)
    wd.mkdir(parents=True, exist_ok=True)
    atomic_write_json(wd / "seed.json", {**s, "resolved_at": "2020-01-01T00:00:00"})
    mark_stage_complete(wd, "seed", seed_id=s["openalex_id"], prompt_version="seed-1")


def _run_cli(argv, tmp_path, capsys):
    with patch.object(sys, "argv", ["wake", "--work-dir", str(tmp_path), *argv]):
        try:
            main()
            code = 0
        except SystemExit as exc:
            code = exc.code or 0
    return code, capsys.readouterr()


def _fake_pdf_bytes():
    return b"%PDF-1.4 " + b"x" * 3000


# --- fetch_seed_pdf core ---------------------------------------------------

def test_fetch_seed_pdf_cache_hit(tmp_path):
    _seed_cached(tmp_path)
    dest = seed_pdf_path(_SEED["openalex_id"], tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_fake_pdf_bytes())

    result = fetch_seed_pdf(_SEED, base=tmp_path, verbose=False)
    assert result["ok"] is True
    assert result["source"] == "cache"


def test_fetch_seed_pdf_cache_hit_not_logged(tmp_path):
    _seed_cached(tmp_path)
    dest = seed_pdf_path(_SEED["openalex_id"], tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_fake_pdf_bytes())

    fetch_seed_pdf(_SEED, base=tmp_path, verbose=False)
    assert not log_path(_SEED["openalex_id"], tmp_path).exists()


def test_fetch_seed_pdf_success_logs_seed_pdf_fetched(tmp_path):
    _seed_cached(tmp_path)
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value="http://example.com/seed.pdf"), \
         patch("wake.pdf_fetch.requests.get") as mock_get, \
         patch("wake.pdf_fetch.time.sleep"):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = _fake_pdf_bytes()
        result = fetch_seed_pdf(_SEED, base=tmp_path, verbose=False)

    assert result["ok"] is True
    p = log_path(_SEED["openalex_id"], tmp_path)
    assert p.exists()
    assert "seed_pdf_fetched" in p.read_text()


def test_fetch_seed_pdf_failure_logs_seed_pdf_fetch_failed(tmp_path):
    _seed_cached(tmp_path)
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.unpaywall.get_oa_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.springer.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.core.is_enabled", return_value=False), \
         patch("wake.pdf_fetch.time.sleep"):
        result = fetch_seed_pdf(_SEED, base=tmp_path, verbose=False)

    assert result["ok"] is False
    assert "fallback_links" in result
    p = log_path(_SEED["openalex_id"], tmp_path)
    assert p.exists()
    assert "seed_pdf_fetch_failed" in p.read_text()


def test_fetch_seed_pdf_stored_at_seed_pdf_path_not_pdfs(tmp_path):
    _seed_cached(tmp_path)
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value="http://example.com/seed.pdf"), \
         patch("wake.pdf_fetch.requests.get") as mock_get, \
         patch("wake.pdf_fetch.time.sleep"):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = _fake_pdf_bytes()
        result = fetch_seed_pdf(_SEED, base=tmp_path, verbose=False)

    assert result["ok"] is True
    assert "seed.pdf" in result["path"]
    assert "/pdfs/" not in result["path"]


# --- acquire_seed_pdf updates seed.json ------------------------------------

def test_acquire_seed_pdf_updates_seed_json_on_success(tmp_path):
    _seed_cached(tmp_path)
    fake_pages = ["Page 1 text", "Page 2 text"]
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value="http://example.com/seed.pdf"), \
         patch("wake.pdf_fetch.requests.get") as mock_get, \
         patch("wake.pdf_fetch.time.sleep"), \
         patch("wake.sources.pdf_fulltext.extract_pages_cached", return_value=fake_pages), \
         patch("wake.sources.pdf_fulltext.extract_full_text_from_pages", return_value="Full seed text here"):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = _fake_pdf_bytes()
        result = acquire_seed_pdf(_SEED, base=tmp_path, verbose=False)

    assert result["ok"] is True
    assert result["extracted_text_path"] is not None

    cached = load_seed(_SEED["openalex_id"], tmp_path)
    assert cached is not None
    sp = cached.get("seed_pdf", {})
    assert sp["path"] is not None
    assert "seed.pdf" in sp["path"]
    assert sp["source"] == "osti"
    assert sp["extracted_text_path"] is not None


def test_acquire_seed_pdf_updates_seed_json_on_failure(tmp_path):
    _seed_cached(tmp_path)
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.unpaywall.get_oa_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.springer.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.core.is_enabled", return_value=False), \
         patch("wake.pdf_fetch.time.sleep"):
        result = acquire_seed_pdf(_SEED, base=tmp_path, verbose=False)

    assert result["ok"] is False

    cached = load_seed(_SEED["openalex_id"], tmp_path)
    sp = cached.get("seed_pdf", {})
    assert sp["path"] is None
    assert "attempted_at" in sp
    assert isinstance(sp["tried"], list)
    assert "fallback_links" in sp


def test_acquire_seed_pdf_extraction_failure_graceful(tmp_path):
    _seed_cached(tmp_path)
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value="http://x/s.pdf"), \
         patch("wake.pdf_fetch.requests.get") as mock_get, \
         patch("wake.pdf_fetch.time.sleep"), \
         patch("wake.sources.pdf_fulltext.extract_pages_cached", side_effect=Exception("bad PDF")):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = _fake_pdf_bytes()
        result = acquire_seed_pdf(_SEED, base=tmp_path, verbose=False)

    assert result["ok"] is True
    assert result["extracted_text_path"] is None

    cached = load_seed(_SEED["openalex_id"], tmp_path)
    assert cached["seed_pdf"]["path"] is not None
    assert cached["seed_pdf"]["extracted_text_path"] is None


# --- acquire_seed_pdf_from_path --------------------------------------------

def test_from_pdf_match_copies_and_updates_seed_json(tmp_path):
    _seed_cached(tmp_path)
    pdf_copy = tmp_path / "supplied.pdf"
    shutil.copy(_FIXTURE, pdf_copy)

    fake_check = {
        "ok": True, "title_similarity": 0.75, "author_matched": True,
        "doi_found": False, "strong_signals": 2, "message": "ok",
    }
    with patch("wake.pdf_verify.check_pdf_metadata", return_value=fake_check), \
         patch("wake.sources.pdf_fulltext.extract_pages_cached", return_value=["page 1"]), \
         patch("wake.sources.pdf_fulltext.extract_full_text_from_pages", return_value="extracted"):
        result = acquire_seed_pdf_from_path(_SEED, pdf_copy, base=tmp_path, verbose=False)

    assert result["ok"] is True
    assert result["source"] == "supplied"
    assert seed_pdf_path(_SEED["openalex_id"], tmp_path).exists()
    cached = load_seed(_SEED["openalex_id"], tmp_path)
    assert cached["seed_pdf"]["source"] == "supplied"


def test_from_pdf_mismatch_refuses_without_force(tmp_path):
    _seed_cached(tmp_path)
    pdf_copy = tmp_path / "wrong.pdf"
    shutil.copy(_FIXTURE, pdf_copy)

    fake_check = {
        "ok": False, "title_similarity": 0.05, "author_matched": False,
        "doi_found": False, "strong_signals": 0,
        "message": "PDF metadata check failed: ... Pass --force to override.",
    }
    with patch("wake.pdf_verify.check_pdf_metadata", return_value=fake_check):
        with pytest.raises(ValueError, match="metadata check failed"):
            acquire_seed_pdf_from_path(_SEED, pdf_copy, base=tmp_path, verbose=False)

    assert not seed_pdf_path(_SEED["openalex_id"], tmp_path).exists()


def test_from_pdf_force_overrides_mismatch_and_logs(tmp_path):
    _seed_cached(tmp_path)
    pdf_copy = tmp_path / "maybe_wrong.pdf"
    shutil.copy(_FIXTURE, pdf_copy)

    fake_check = {
        "ok": False, "title_similarity": 0.10, "author_matched": False,
        "doi_found": False, "strong_signals": 0,
        "message": "PDF metadata check failed.",
    }
    with patch("wake.pdf_verify.check_pdf_metadata", return_value=fake_check), \
         patch("wake.sources.pdf_fulltext.extract_pages_cached", return_value=["p1"]), \
         patch("wake.sources.pdf_fulltext.extract_full_text_from_pages", return_value="text"):
        result = acquire_seed_pdf_from_path(
            _SEED, pdf_copy, base=tmp_path, force=True, verbose=False,
        )

    assert result["ok"] is True
    p = log_path(_SEED["openalex_id"], tmp_path)
    assert "seed_pdf_forced_despite_mismatch" in p.read_text()


def test_from_pdf_match_logs_verified(tmp_path):
    _seed_cached(tmp_path)
    pdf_copy = tmp_path / "good.pdf"
    shutil.copy(_FIXTURE, pdf_copy)

    fake_check = {
        "ok": True, "title_similarity": 0.8, "author_matched": True,
        "doi_found": True, "strong_signals": 3, "message": "ok",
    }
    with patch("wake.pdf_verify.check_pdf_metadata", return_value=fake_check), \
         patch("wake.sources.pdf_fulltext.extract_pages_cached", return_value=["p1"]), \
         patch("wake.sources.pdf_fulltext.extract_full_text_from_pages", return_value="text"):
        acquire_seed_pdf_from_path(_SEED, pdf_copy, base=tmp_path, verbose=False)

    p = log_path(_SEED["openalex_id"], tmp_path)
    assert "seed_pdf_supplied_verified" in p.read_text()


def test_from_pdf_missing_file_raises(tmp_path):
    _seed_cached(tmp_path)
    with pytest.raises(FileNotFoundError):
        acquire_seed_pdf_from_path(_SEED, "/nonexistent/path.pdf", base=tmp_path, verbose=False)


# --- auto-attempt at resolve time ------------------------------------------

def test_resolve_and_cache_auto_attempts_seed_pdf(tmp_path):
    fake_pdf = _fake_pdf_bytes()
    with patch("wake.seed.resolve", return_value={**_SEED}), \
         patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value="http://x/seed.pdf"), \
         patch("wake.pdf_fetch.requests.get") as mock_get, \
         patch("wake.pdf_fetch.time.sleep"), \
         patch("wake.sources.pdf_fulltext.extract_pages_cached", return_value=["p1"]), \
         patch("wake.sources.pdf_fulltext.extract_full_text_from_pages", return_value="full text"):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = fake_pdf
        from wake.seed import resolve_and_cache
        work = resolve_and_cache(_SEED["openalex_id"], base=tmp_path)

    assert seed_pdf_path(_SEED["openalex_id"], tmp_path).exists()
    cached = load_seed(_SEED["openalex_id"], tmp_path)
    assert cached.get("seed_pdf", {}).get("path") is not None


def test_resolve_and_cache_auto_attempt_silent_on_failure(tmp_path):
    with patch("wake.seed.resolve", return_value={**_SEED}), \
         patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.unpaywall.get_oa_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.springer.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.core.is_enabled", return_value=False), \
         patch("wake.pdf_fetch.time.sleep"):
        from wake.seed import resolve_and_cache
        work = resolve_and_cache(_SEED["openalex_id"], base=tmp_path)

    assert not seed_pdf_path(_SEED["openalex_id"], tmp_path).exists()
    cached = load_seed(_SEED["openalex_id"], tmp_path)
    sp = cached.get("seed_pdf", {})
    assert sp.get("path") is None
    assert "fallback_links" in sp


def test_resolve_and_cache_skips_auto_attempt_when_already_cached(tmp_path):
    _seed_cached(tmp_path)
    dest = seed_pdf_path(_SEED["openalex_id"], tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_fake_pdf_bytes())

    acquire_called = []
    original_acquire = seed_pdf_mod.acquire_seed_pdf

    def spy(*a, **kw):
        acquire_called.append(1)
        return original_acquire(*a, **kw)

    with patch("wake.seed.resolve", return_value={**_SEED}), \
         patch("wake.seed_pdf.acquire_seed_pdf", side_effect=spy):
        from wake.seed import resolve_and_cache
        resolve_and_cache(_SEED["openalex_id"], base=tmp_path)

    assert len(acquire_called) == 0


def test_resolve_and_cache_respects_seed_pdf_at_resolve_false(tmp_path):
    with patch("wake.seed.resolve", return_value={**_SEED}), \
         patch("wake.config.pdf_fetch_cfg", return_value={"seed_pdf_at_resolve": False}):
        from wake.seed import resolve_and_cache
        resolve_and_cache(_SEED["openalex_id"], base=tmp_path)

    assert not seed_pdf_path(_SEED["openalex_id"], tmp_path).exists()


# --- CLI -------------------------------------------------------------------

def test_seed_fetch_pdf_cli_success(tmp_path, capsys):
    _seed_cached(tmp_path)

    fake_result = {
        "ok": True, "path": str(seed_pdf_path(_SEED["openalex_id"], tmp_path)),
        "extracted_text_path": str(tmp_path / "wake-out" / _SEED["openalex_id"] / "seed.pdf.json"),
        "source": "osti",
    }
    with patch("wake.seed_pdf.acquire_seed_pdf", return_value=fake_result):
        code, captured = _run_cli(
            ["seed", "fetch-pdf", _SEED["openalex_id"]], tmp_path, capsys,
        )

    assert code == 0
    assert "osti" in captured.out


def test_seed_fetch_pdf_cli_failure(tmp_path, capsys):
    _seed_cached(tmp_path)

    fake_result = {
        "ok": False,
        "tried": ["osti", "semanticscholar"],
        "fallback_links": {"google_scholar": "https://scholar.google.com/scholar?q=Parallel+netCDF"},
    }
    with patch("wake.seed_pdf.acquire_seed_pdf", return_value=fake_result):
        code, captured = _run_cli(
            ["seed", "fetch-pdf", _SEED["openalex_id"]], tmp_path, capsys,
        )

    assert code == 0
    assert "Could not" in captured.out
    assert "google_scholar" in captured.out


def test_seed_fetch_pdf_cli_json(tmp_path, capsys):
    _seed_cached(tmp_path)

    fake_result = {
        "ok": True,
        "path": str(seed_pdf_path(_SEED["openalex_id"], tmp_path)),
        "extracted_text_path": None,
        "source": "cache",
    }
    with patch("wake.seed_pdf.acquire_seed_pdf", return_value=fake_result):
        code, captured = _run_cli(
            ["--json", "seed", "fetch-pdf", _SEED["openalex_id"]], tmp_path, capsys,
        )

    assert code == 0
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["data"]["source"] == "cache"


def test_seed_fetch_pdf_cli_from_pdf_missing_file(tmp_path, capsys):
    _seed_cached(tmp_path)

    code, captured = _run_cli(
        ["seed", "fetch-pdf", _SEED["openalex_id"], "--from-pdf", "/nonexistent/paper.pdf"],
        tmp_path, capsys,
    )
    assert code == 1


def test_status_shows_seed_pdf_line(tmp_path, capsys):
    _seed_cached(tmp_path)

    code, captured = _run_cli(
        ["status", _SEED["openalex_id"]], tmp_path, capsys,
    )
    assert code == 0
    assert "Seed PDF" in captured.out
