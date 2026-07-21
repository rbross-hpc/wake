# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.pdf_verify -- PDF-to-citing-work metadata match check
and the `wake evidence --from-pdf` CLI flow (BACKLOG deferred item D.1)."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from wake import pdf_verify
from wake.classify import save_classified
from wake.cli.main import main
from wake.evidence_wiki import log_path
from wake.io import atomic_write_json
from wake.seed import work_dir
from wake.state import mark_stage_complete
from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS

_FIXTURE = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"


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


# --- individual signal functions -------------------------------------------

def test_title_signal_exact_match():
    title = "Parallel netCDF: A High-Performance Scientific I/O Interface"
    score = pdf_verify._title_signal(title, "Parallel netCDF: A High-Performance Scientific I/O Interface ... more text")
    assert score > 0.9


def test_title_signal_zero_on_empty():
    assert pdf_verify._title_signal(None, "some text") == 0.0
    assert pdf_verify._title_signal("title", "") == 0.0


def test_author_signal_finds_surname():
    assert pdf_verify._author_signal(["Jianwei Li", "Wei-keng Liao"], "This paper by Li and Liao presents...")


def test_author_signal_case_insensitive():
    assert pdf_verify._author_signal(["Smith"], "dr. smith published this in 2020")


def test_author_signal_false_when_no_match():
    assert not pdf_verify._author_signal(["Zzzunknown"], "completely unrelated text")


def test_author_signal_false_when_empty_authors():
    assert not pdf_verify._author_signal([], "some text with names")


def test_doi_signal_finds_doi():
    assert pdf_verify._doi_signal("10.1145/1048935.1050189",
                                   "... doi.org/10.1145/1048935.1050189 ...")


def test_doi_signal_case_insensitive():
    assert pdf_verify._doi_signal("10.1145/ABC", "DOI: 10.1145/abc accessed from publisher")


def test_doi_signal_false_when_absent():
    assert not pdf_verify._doi_signal("10.9999/nothere", "some other text entirely")


def test_doi_signal_false_when_no_doi():
    assert not pdf_verify._doi_signal(None, "some text")


# --- check_pdf_metadata decision rule --------------------------------------

def _work_with(title=None, authors=None, doi=None):
    return {
        "title": title or "Parallel netCDF: A High-Performance Scientific I/O Interface",
        "authors": authors or ["Jianwei Li"],
        "doi": doi or "10.1145/1048935.1050189",
    }


def test_check_passes_when_title_and_author_match():
    lead = "Parallel netCDF: A High-Performance Scientific I/O Interface\nJianwei Li et al."
    result = pdf_verify.check_pdf_metadata(_work_with(), lead)
    assert result["ok"] is True


def test_check_passes_when_title_and_doi_match():
    title = "High-Performance Parallel I/O for Scientific Computing Applications"
    lead = f"{title} — this paper presents a system. doi.org/10.1145/1048935.1050189 footnote"
    work = _work_with(title=title, authors=["Unknown Author"])
    result = pdf_verify.check_pdf_metadata(work, lead)
    assert result["ok"] is True


def test_check_passes_when_all_three_match():
    lead = "Parallel netCDF: A High-Performance Scientific I/O Interface\nJianwei Li\n10.1145/1048935.1050189"
    result = pdf_verify.check_pdf_metadata(_work_with(), lead)
    assert result["ok"] is True


def test_check_fails_when_only_author_matches():
    lead = "Completely different title by Li about unrelated topics"
    work = _work_with(doi=None)
    result = pdf_verify.check_pdf_metadata(work, lead)
    assert result["ok"] is False
    assert "anchor" in result["message"].lower() or "title" in result["message"].lower()


def test_check_fails_on_completely_wrong_pdf():
    lead = "A Review of Lattice Boltzmann Methods for Fluid Dynamics\nJohn Doe, 2020"
    result = pdf_verify.check_pdf_metadata(_work_with(), lead)
    assert result["ok"] is False
    assert result["title_similarity"] < 0.5


def test_check_returns_all_signal_fields():
    lead = "Parallel netCDF Li 10.1145/1048935.1050189"
    result = pdf_verify.check_pdf_metadata(_work_with(), lead)
    assert "title_similarity" in result
    assert "author_matched" in result
    assert "doi_found" in result
    assert "strong_signals" in result
    assert "message" in result


# --- CLI --from-pdf --------------------------------------------------------

def test_from_pdf_cli_passes_on_matching_fixture(tmp_path, capsys):
    """The committed OSTI fixture PDF contains 'netCDF' and 'Parallel' in its
    first page, so the title signal fires against the Parallel netCDF seed work.
    Authors in the fixture (Ross, et al.) won't match SAMPLE_CITING_WORKS[0]'s
    authors, but DOI presence in an OSTI PDF may or may not appear -- we
    mock the check to return ok=True to keep this test deterministic."""
    _seed_cached(tmp_path)
    work = _classified_work(0)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)

    pdf_copy = tmp_path / "supplied.pdf"
    shutil.copy(_FIXTURE, pdf_copy)

    fake_check = {
        "ok": True, "title_similarity": 0.75, "author_matched": True,
        "doi_found": False, "strong_signals": 2,
        "message": "PDF metadata check passed.",
    }
    fake_dossier_result = {
        "ok": True,
        "dossier_path": str(tmp_path / "evidence" / f"{work['openalex_id']}.md"),
        "dossier_json_path": str(tmp_path / "evidence" / f"{work['openalex_id']}.json"),
        "pdf_path": str(pdf_copy),
        "pdf_source": "supplied",
        "extracted_text_path": str(pdf_copy.with_suffix(".json")),
        "citing_title": work["title"],
        "citing_authors": work["authors"],
        "provisional": {"relationship": "uses-as-tool", "confidence": 0.4, "justification": "x"},
        "proposed": {"relationship": "extends", "confidence": 0.9, "justification": "y", "agrees_with_provisional": False},
        "quotes": [],
    }

    with patch("wake.pdf_verify.check_pdf_metadata", return_value=fake_check), \
         patch("wake.evidence.build_dossier", return_value=fake_dossier_result):
        code, captured = _run_cli(
            ["evidence", PARALLEL_NETCDF_WORK["openalex_id"],
             work["openalex_id"], "--from-pdf", str(pdf_copy)],
            tmp_path, capsys,
        )

    assert code == 0


def test_from_pdf_cli_refuses_mismatch_without_force(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work(0)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)

    pdf_copy = tmp_path / "wrong.pdf"
    shutil.copy(_FIXTURE, pdf_copy)

    fake_check = {
        "ok": False, "title_similarity": 0.10, "author_matched": False,
        "doi_found": False, "strong_signals": 0,
        "message": "PDF metadata check failed: neither title similarity nor DOI matched. Pass --force to override.",
    }

    with patch("wake.pdf_verify.check_pdf_metadata", return_value=fake_check):
        code, captured = _run_cli(
            ["evidence", PARALLEL_NETCDF_WORK["openalex_id"],
             work["openalex_id"], "--from-pdf", str(pdf_copy)],
            tmp_path, capsys,
        )

    assert code == 1
    assert "metadata check failed" in captured.out.lower() or "metadata check failed" in (captured.err or "").lower() or "Error" in captured.out


def test_from_pdf_cli_force_overrides_mismatch(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work(0)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)

    pdf_copy = tmp_path / "maybe_wrong.pdf"
    shutil.copy(_FIXTURE, pdf_copy)

    fake_check = {
        "ok": False, "title_similarity": 0.20, "author_matched": False,
        "doi_found": False, "strong_signals": 0,
        "message": "PDF metadata check failed. Pass --force to override.",
    }
    fake_dossier_result = {
        "ok": True,
        "dossier_path": str(tmp_path / "evidence" / f"{work['openalex_id']}.md"),
        "dossier_json_path": str(tmp_path / "evidence" / f"{work['openalex_id']}.json"),
        "pdf_path": str(pdf_copy), "pdf_source": "supplied",
        "extracted_text_path": str(pdf_copy.with_suffix(".json")),
        "citing_title": work["title"], "citing_authors": work["authors"],
        "provisional": {"relationship": "uses-as-tool", "confidence": 0.4, "justification": "x"},
        "proposed": {"relationship": "extends", "confidence": 0.9, "justification": "y", "agrees_with_provisional": False},
        "quotes": [],
    }

    with patch("wake.pdf_verify.check_pdf_metadata", return_value=fake_check), \
         patch("wake.evidence.build_dossier", return_value=fake_dossier_result):
        code, captured = _run_cli(
            ["evidence", PARALLEL_NETCDF_WORK["openalex_id"],
             work["openalex_id"], "--from-pdf", str(pdf_copy), "--force"],
            tmp_path, capsys,
        )

    assert code == 0


def test_from_pdf_cli_logs_mismatch_even_with_force(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work(0)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)

    pdf_copy = tmp_path / "maybe_wrong.pdf"
    shutil.copy(_FIXTURE, pdf_copy)

    fake_check = {
        "ok": False, "title_similarity": 0.10, "author_matched": False,
        "doi_found": False, "strong_signals": 0,
        "message": "PDF metadata check failed.",
    }
    fake_dossier_result = {
        "ok": True,
        "dossier_path": str(tmp_path / "evidence" / f"{work['openalex_id']}.md"),
        "dossier_json_path": str(tmp_path / "evidence" / f"{work['openalex_id']}.json"),
        "pdf_path": str(pdf_copy), "pdf_source": "supplied",
        "extracted_text_path": str(pdf_copy.with_suffix(".json")),
        "citing_title": work["title"], "citing_authors": work["authors"],
        "provisional": {"relationship": "uses-as-tool", "confidence": 0.4, "justification": "x"},
        "proposed": {"relationship": "extends", "confidence": 0.9, "justification": "y", "agrees_with_provisional": False},
        "quotes": [],
    }

    with patch("wake.pdf_verify.check_pdf_metadata", return_value=fake_check), \
         patch("wake.evidence.build_dossier", return_value=fake_dossier_result):
        _run_cli(
            ["evidence", PARALLEL_NETCDF_WORK["openalex_id"],
             work["openalex_id"], "--from-pdf", str(pdf_copy), "--force"],
            tmp_path, capsys,
        )

    p = log_path(PARALLEL_NETCDF_WORK["openalex_id"], tmp_path)
    assert p.exists()
    log_text = p.read_text()
    assert "pdf_forced_despite_mismatch" in log_text


def test_from_pdf_cli_error_on_missing_file(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work(0)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)

    code, captured = _run_cli(
        ["evidence", PARALLEL_NETCDF_WORK["openalex_id"],
         work["openalex_id"], "--from-pdf", "/nonexistent/path.pdf"],
        tmp_path, capsys,
    )
    assert code == 1
