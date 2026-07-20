# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for the wake <noun> show verbs (BACKLOG Theme J item 4):
`wake theme show`, `wake narrative show`, `wake narrative outline show`,
`wake narrative section show`, `wake show dossier`.

Full end-to-end through wake.cli.main.main() via sys.argv, same as a
real invocation -- these are integration tests, not unit tests of a
single function, since the point being verified is that the CLI wiring
(parser -> dispatch -> handler -> emit) is correct end to end.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from wake import evidence, narrative, themes
from wake.classify import save_classified
from wake.cli.main import main
from wake.io import atomic_write_json
from wake.report import add_override
from wake.seed import work_dir
from wake.state import mark_stage_complete
from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS

_FIXTURE = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"


def _seed_cached(tmp_path):
    """Pre-seed seed.json + stage marker so resolve_and_cache() short-
    circuits to the cache with no network call, exactly like a real
    packet the agent has already resolved once this session."""
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
        "relationship": "extends",
        "confidence": 0.9,
        "justification": "The full text clearly shows a direct extension.",
        "agrees_with_provisional": False,
        "quotes": [{"page": 2, "text": "We directly extend the seed's method here.", "note": "x"}],
    }
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(dest), "source": "osti",
    }), patch("wake.evidence.chat_json", return_value=fake_response):
        return evidence.build_dossier(PARALLEL_NETCDF_WORK, citing_work, base=tmp_path, verbose=False)


def _make_confirmed_theme(tmp_path, slug="t1"):
    works = [_classified_work(0), _classified_work(1)]
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], works, base=tmp_path)
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


# --- wake theme show ------------------------------------------------------

def test_theme_show_prints_theme_markdown(tmp_path, capsys):
    _seed_cached(tmp_path)
    _make_confirmed_theme(tmp_path, "t1")

    code, captured = _run_cli(["theme", "show", "W2156077349", "t1"], tmp_path, capsys)
    assert code == 0
    assert "Theme One" in captured.out
    assert "CONFIRMED" in captured.out


def test_theme_show_json_mode(tmp_path, capsys):
    _seed_cached(tmp_path)
    _make_confirmed_theme(tmp_path, "t1")

    code, captured = _run_cli(["--json", "theme", "show", "W2156077349", "t1"], tmp_path, capsys)
    assert code == 0
    envelope = json.loads(captured.out)
    assert envelope["ok"] is True
    assert "Theme One" in envelope["data"]["markdown"]


def test_theme_show_missing_slug_errors(tmp_path, capsys):
    _seed_cached(tmp_path)
    code, captured = _run_cli(["--json", "theme", "show", "W2156077349", "nope"], tmp_path, capsys)
    assert code == 1
    envelope = json.loads(captured.out)
    assert envelope["ok"] is False
    assert "nope" in envelope["error"]["message"]


# --- wake narrative outline show / section show / show -------------------

def test_narrative_outline_show(tmp_path, capsys):
    _seed_cached(tmp_path)
    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "intro", "title": "Introduction", "kind": "free"}],
        base=tmp_path,
    )
    code, captured = _run_cli(["narrative", "outline", "show", "W2156077349"], tmp_path, capsys)
    assert code == 0
    assert "Introduction" in captured.out


def test_narrative_outline_show_missing_errors(tmp_path, capsys):
    _seed_cached(tmp_path)
    code, captured = _run_cli(["--json", "narrative", "outline", "show", "W2156077349"], tmp_path, capsys)
    assert code == 1
    envelope = json.loads(captured.out)
    assert envelope["ok"] is False


def test_narrative_section_show(tmp_path, capsys):
    _seed_cached(tmp_path)
    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "intro", "title": "Introduction", "kind": "free"}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "intro", title="Introduction", prose="Opening paragraph.", base=tmp_path,
    )
    code, captured = _run_cli(["narrative", "section", "show", "W2156077349", "intro"], tmp_path, capsys)
    assert code == 0
    assert "Opening paragraph." in captured.out


def test_narrative_section_show_missing_errors(tmp_path, capsys):
    _seed_cached(tmp_path)
    code, captured = _run_cli(["--json", "narrative", "section", "show", "W2156077349", "nope"], tmp_path, capsys)
    assert code == 1
    envelope = json.loads(captured.out)
    assert envelope["ok"] is False


def test_narrative_show_stitched_document(tmp_path, capsys):
    _seed_cached(tmp_path)
    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "intro", "title": "Introduction", "kind": "free"}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "intro", title="Introduction", prose="Opening paragraph.", base=tmp_path,
    )
    narrative.stitch(PARALLEL_NETCDF_WORK, base=tmp_path)

    code, captured = _run_cli(["narrative", "show", "W2156077349"], tmp_path, capsys)
    assert code == 0
    assert "Opening paragraph." in captured.out


def test_narrative_show_before_stitch_errors(tmp_path, capsys):
    _seed_cached(tmp_path)
    code, captured = _run_cli(["--json", "narrative", "show", "W2156077349"], tmp_path, capsys)
    assert code == 1
    envelope = json.loads(captured.out)
    assert envelope["ok"] is False


# --- wake show dossier -----------------------------------------------------

def test_show_dossier_prints_dossier_markdown(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work(0)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)
    _build_dossier_for(tmp_path, work, pdf_name="w.pdf")

    code, captured = _run_cli(["show", "dossier", "W2156077349", work["openalex_id"]], tmp_path, capsys)
    assert code == 0
    assert work["title"] in captured.out


def test_show_dossier_missing_errors(tmp_path, capsys):
    _seed_cached(tmp_path)
    code, captured = _run_cli(["--json", "show", "dossier", "W2156077349", "W_NOPE"], tmp_path, capsys)
    assert code == 1
    envelope = json.loads(captured.out)
    assert envelope["ok"] is False
