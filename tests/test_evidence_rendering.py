# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for the evidence pre-verify rendering improvements:
- Dossier JSON now carries citing_title and citing_authors.
- wake evidence CLI human output shows title/authors header and inline quotes.
- Backward-compat: old dossiers (missing the new fields) still render.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from wake import evidence
from wake.classify import save_classified
from wake.cli.main import main
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


def _build_dossier(tmp_path, citing_work=None, pdf_name="citing.pdf", quotes=None):
    dest = tmp_path / "pdfs" / pdf_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_FIXTURE, dest)
    if quotes is None:
        quotes = [
            {"page": 2, "text": "We directly extend the seed's method here.", "note": "clear extension"},
            {"page": 5, "text": "Further evidence on page five that this is an extension.", "note": ""},
            {"page": 7, "text": "A third passage confirming the extension.", "note": ""},
            {"page": 9, "text": "A fourth passage, should not appear inline (capped at 3).", "note": ""},
        ]
    fake_response = {
        "relationship": "extends", "confidence": 0.9,
        "justification": "The full text clearly shows a direct extension of the seed's method.",
        "agrees_with_provisional": False,
        "quotes": quotes,
    }
    citing_work = citing_work or _classified_work()
    with patch("wake.evidence.fetch_pdf", return_value={"ok": True, "path": str(dest), "source": "osti"}), \
         patch("wake.evidence.chat_json", return_value=fake_response):
        return evidence.build_dossier(PARALLEL_NETCDF_WORK, citing_work, base=tmp_path, verbose=False)


# --- dossier JSON fields ---------------------------------------------------

def test_dossier_json_includes_citing_title_and_authors(tmp_path):
    work = _classified_work()
    _build_dossier(tmp_path, citing_work=work)
    loaded = evidence.load_dossier(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"], base=tmp_path,
    )
    assert loaded["citing_title"] == work["title"]
    assert loaded["citing_authors"] == work["authors"]


def test_dossier_json_authors_empty_list_when_none(tmp_path):
    work = _classified_work(authors=[], author_ids=[])
    _build_dossier(tmp_path, citing_work=work)
    loaded = evidence.load_dossier(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"], base=tmp_path,
    )
    assert loaded["citing_authors"] == []


# --- CLI human output ------------------------------------------------------

def test_evidence_human_output_includes_title_and_authors(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work()
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)
    _build_dossier(tmp_path, citing_work=work)

    code, captured = _run_cli(
        ["evidence", PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"]],
        tmp_path, capsys,
    )
    assert code == 0
    assert work["title"] in captured.out
    assert work["authors"][0] in captured.out


def test_evidence_human_output_quotes_inline(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work()
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)
    _build_dossier(tmp_path, citing_work=work)

    code, captured = _run_cli(
        ["evidence", PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"]],
        tmp_path, capsys,
    )
    assert code == 0
    assert "We directly extend the seed" in captured.out
    assert "p. 2" in captured.out
    assert "clear extension" in captured.out


def test_evidence_human_output_caps_inline_quotes_at_3(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work()
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)
    _build_dossier(tmp_path, citing_work=work)

    code, captured = _run_cli(
        ["evidence", PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"]],
        tmp_path, capsys,
    )
    assert code == 0
    assert "A fourth passage" not in captured.out
    assert "+ 1 more" in captured.out


def test_evidence_human_output_no_quotes(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work()
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)
    _build_dossier(tmp_path, citing_work=work, quotes=[])

    code, captured = _run_cli(
        ["evidence", PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"]],
        tmp_path, capsys,
    )
    assert code == 0
    assert "No supporting passages" in captured.out


# --- backward-compat: old dossier without new fields -----------------------

def test_evidence_human_output_graceful_without_title_authors(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work()
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)

    dest = tmp_path / "pdfs" / "citing.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_FIXTURE, dest)
    fake_response = {
        "relationship": "extends", "confidence": 0.9,
        "justification": "Clear extension.",
        "agrees_with_provisional": False,
        "quotes": [{"page": 1, "text": "Some evidence.", "note": ""}],
    }
    with patch("wake.evidence.fetch_pdf", return_value={"ok": True, "path": str(dest), "source": "osti"}), \
         patch("wake.evidence.chat_json", return_value=fake_response):
        evidence.build_dossier(PARALLEL_NETCDF_WORK, work, base=tmp_path, verbose=False)

    json_path = evidence.dossier_json_path(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"], base=tmp_path,
    )
    payload = json.loads(json_path.read_text())
    payload.pop("citing_title", None)
    payload.pop("citing_authors", None)
    atomic_write_json(json_path, payload)

    code, captured = _run_cli(
        ["evidence", PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"]],
        tmp_path, capsys,
    )
    assert code == 0
    assert "Some evidence." in captured.out
