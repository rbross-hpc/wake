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

from wake import evidence, narrative, themes
from wake.classify import save_classified
from wake.cli.main import main
from wake.io import atomic_write_json
from wake.report import add_override
from wake.seed import work_dir
from wake.state import mark_stage_complete

from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS
from .wiki_invariants import assert_no_malformed_wikilinks

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
        "relationship": "uses-method-from",
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
        result = evidence.build_dossier(PARALLEL_NETCDF_WORK, citing_work, base=tmp_path, verbose=False)
    # build_dossier() only writes JSON now (rendering is an explicit
    # `wake rebuild` step, see build.py's module docstring) -- render the
    # .md immediately so this helper's callers can keep reading it as
    # before.
    evidence.rerender_dossier_md(PARALLEL_NETCDF_WORK, citing_work["openalex_id"], base=tmp_path)
    return result


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


# --- dossier "Referenced by" back-links -------------------------------------

def test_dossier_md_has_no_referenced_by_line_when_orphan(tmp_path):
    work = _classified_work()
    _build_dossier(tmp_path, citing_work=work)
    text = evidence.dossier_path(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"], base=tmp_path,
    ).read_text()
    assert "Referenced by" not in text


def test_dossier_md_referenced_by_theme(tmp_path):
    work = _classified_work()
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)
    _build_dossier(tmp_path, citing_work=work)
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"],
        relationship="extends", justification="accepted", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="Theme One", summary="Summary.",
        citing_ids=[work["openalex_id"]], base=tmp_path,
    )
    # Themes no longer re-render affected dossiers as a write-time side
    # effect (see build.py's module docstring) -- render explicitly.
    evidence.rerender_dossier_md(PARALLEL_NETCDF_WORK, work["openalex_id"], base=tmp_path)
    text = evidence.dossier_path(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"], base=tmp_path,
    ).read_text()
    assert "**Referenced by:**" in text
    assert "theme [Theme One](themes/t1.md)" in text
    assert_no_malformed_wikilinks(text)


def test_dossier_md_referenced_by_narrative_section(tmp_path):
    work = _classified_work()
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)
    _build_dossier(tmp_path, citing_work=work)
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"],
        relationship="extends", justification="accepted", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="Section One",
        prose=f"This work extends PnetCDF. [ref:{work['openalex_id']}]", base=tmp_path,
    )
    # Sections no longer re-render referenced dossiers as a write-time
    # side effect -- render explicitly.
    evidence.rerender_dossier_md(PARALLEL_NETCDF_WORK, work["openalex_id"], base=tmp_path)
    text = evidence.dossier_path(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"], base=tmp_path,
    ).read_text()
    assert "**Referenced by:**" in text
    assert "narrative section [Section One](../narrative/sections/s1.md)" in text


def test_dossier_md_referenced_by_both_theme_and_section(tmp_path):
    work = _classified_work()
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)
    _build_dossier(tmp_path, citing_work=work)
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"],
        relationship="extends", justification="accepted", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="Theme One", summary="Summary.",
        citing_ids=[work["openalex_id"]], base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "s1", title="Section One",
        prose=f"This work extends PnetCDF. [ref:{work['openalex_id']}]", base=tmp_path,
    )
    evidence.rerender_dossier_md(PARALLEL_NETCDF_WORK, work["openalex_id"], base=tmp_path)
    text = evidence.dossier_path(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"], base=tmp_path,
    ).read_text()
    assert "theme [Theme One](themes/t1.md)" in text
    assert "narrative section [Section One](../narrative/sections/s1.md)" in text


# --- rerender_dossier_md / rerender_all_dossiers ----------------------------

def test_rerender_dossier_md_missing_dossier_returns_none(tmp_path):
    result = evidence.rerender_dossier_md(PARALLEL_NETCDF_WORK, "W_NOPE", base=tmp_path)
    assert result is None


def test_rerender_dossier_md_picks_up_new_theme_membership(tmp_path):
    """A dossier rendered before a theme existed has no back-link; a
    targeted re-render after the theme is created picks it up without
    re-running the LLM or re-fetching the PDF."""
    work = _classified_work()
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)
    _build_dossier(tmp_path, citing_work=work)
    text_before = evidence.dossier_path(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"], base=tmp_path,
    ).read_text()
    assert "Referenced by" not in text_before

    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"],
        relationship="extends", justification="accepted", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="Theme One", summary="Summary.",
        citing_ids=[work["openalex_id"]], base=tmp_path,
    )
    # create_theme() writes JSON only now (rendering is `wake rebuild`'s
    # job, see build.py's module docstring) -- render explicitly here to
    # test the rerender primitive itself.
    evidence.rerender_dossier_md(PARALLEL_NETCDF_WORK, work["openalex_id"], base=tmp_path)
    text_after = evidence.dossier_path(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"], base=tmp_path,
    ).read_text()
    assert "theme [Theme One](themes/t1.md)" in text_after


def test_rerender_dossier_md_preserves_verified_status_block(tmp_path):
    work = _classified_work()
    _build_dossier(tmp_path, citing_work=work)
    add_override(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"],
        relationship="extends", justification="human accepted the finding", base=tmp_path,
        verification_source="evidence-dossier", seed_title=PARALLEL_NETCDF_WORK["title"],
    )
    evidence.rerender_dossier_md(PARALLEL_NETCDF_WORK, work["openalex_id"], base=tmp_path)
    text = evidence.dossier_path(
        PARALLEL_NETCDF_WORK["openalex_id"], work["openalex_id"], base=tmp_path,
    ).read_text()
    assert "## Status: verified" in text
    assert "Verified by a human on" in text
    assert "human accepted the finding" in text
    assert "verification_status: verified" in text


def test_rerender_all_dossiers_returns_sorted_ids(tmp_path):
    w1 = _classified_work(0)
    w2 = {**_classified_work(1)}
    _build_dossier(tmp_path, citing_work=w1, pdf_name="w1.pdf")
    _build_dossier(tmp_path, citing_work=w2, pdf_name="w2.pdf")
    result = evidence.rerender_all_dossiers(
        PARALLEL_NETCDF_WORK["openalex_id"], PARALLEL_NETCDF_WORK, base=tmp_path,
    )
    assert result == sorted([w1["openalex_id"], w2["openalex_id"]])


def test_rerender_all_dossiers_empty_when_no_evidence_dir(tmp_path):
    result = evidence.rerender_all_dossiers(
        PARALLEL_NETCDF_WORK["openalex_id"], PARALLEL_NETCDF_WORK, base=tmp_path,
    )
    assert result == []
