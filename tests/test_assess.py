# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for `wake assess` (report.build_assessment), offline.

Evidence-gap triage report joining classified.json, overrides.jsonl,
dossier existence, theme sidecars, and the PDF fetch log into one
per-work document -- see report.py's build_assessment() docstring.
"""
from __future__ import annotations

import json
import sys
from unittest.mock import patch

from wake import themes
from wake.classify import save_classified
from wake.cli.main import main
from wake.evidence import dossier_json_path
from wake.evidence_wiki import append_log_entry
from wake.exclude import exclude_work
from wake.io import atomic_write_json
from wake.report import _score, add_override, build_assessment
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
        "relationship": "uses-as-tool",
        "relationships": [{"label": "uses-as-tool", "confidence": 0.8,
                            "justification": "x", "quotes": [], "verified": None}],
        "confidence": 0.8,
        "justification": "Uses PnetCDF for I/O.",
        "has_abstract": True,
        "verification_status": "provisional",
        "author_overlap": False,
        **overrides,
    }


def _write_dossier(seed_id, citing_id, base, *, verified=False):
    p = dossier_json_path(seed_id, citing_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, {
        "schema_version": 1,
        "citing_openalex_id": citing_id,
        "seed_openalex_id": seed_id,
        "verification_status": "verified" if verified else "pending-human-review",
        "provisional": {}, "proposed": {}, "quotes": [],
    })


def test_build_assessment_no_classified_works(tmp_path):
    data = build_assessment(PARALLEL_NETCDF_WORK, tmp_path)
    assert data["totals"]["classified"] == 0
    assert data["works"] == []
    assert data["triage"] == []
    assert data["themes"] == []


def test_build_assessment_mixed_states(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]

    verified_work = _classified_work(0)          # will be overridden -> verified
    proposed_work = _classified_work(1)           # has a dossier -> proposed
    provisional_a = _classified_work(2, cited_by_count=500)
    provisional_b = {**_classified_work(2), "openalex_id": "W_LOW", "cited_by_count": 1}
    errored_work = {"openalex_id": "W_ERR", "title": "Errored classify call",
                     "error": "LLM timeout", "cited_by_count": 3}

    save_classified(
        seed_id,
        [verified_work, proposed_work, provisional_a, provisional_b, errored_work],
        base=tmp_path,
    )

    add_override(seed_id, verified_work["openalex_id"], relationship="uses-as-tool", base=tmp_path)
    _write_dossier(seed_id, proposed_work["openalex_id"], tmp_path)

    data = build_assessment(PARALLEL_NETCDF_WORK, tmp_path)

    assert data["totals"]["classified"] == 5
    assert data["totals"]["verified"] == 1
    assert data["totals"]["proposed"] == 1
    assert data["totals"]["provisional"] == 2
    assert data["totals"]["error"] == 1

    by_id = {w["openalex_id"]: w for w in data["works"]}
    assert by_id[verified_work["openalex_id"]]["status"] == "verified"
    assert by_id[proposed_work["openalex_id"]]["status"] == "proposed"
    assert by_id[proposed_work["openalex_id"]]["has_dossier"] is True
    assert by_id[provisional_a["openalex_id"]]["status"] == "provisional"
    assert by_id["W_ERR"]["status"] is None
    assert by_id["W_ERR"]["error"] == "LLM timeout"
    assert by_id["W_ERR"]["score"] is None

    # Only provisional, non-excluded, non-duplicate works enter triage,
    # ranked by score descending (higher cited_by_count wins here since
    # both provisional works share the same relationship label/strength).
    assert set(data["triage"]) == {provisional_a["openalex_id"], provisional_b["openalex_id"]}
    assert data["triage"][0] == provisional_a["openalex_id"]


def test_build_assessment_score_matches_report_score(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    work = _classified_work(0, cited_by_count=123)
    save_classified(seed_id, [work], base=tmp_path)

    data = build_assessment(PARALLEL_NETCDF_WORK, tmp_path)
    row = data["works"][0]
    assert row["score"] == round(_score(work), 3)
    assert row["score_inputs"]["cited_by_count"] == 123


def test_build_assessment_excluded_and_duplicate_flags(tmp_path):
    from wake.dedup import confirm_duplicate

    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    excluded_work = _classified_work(0)
    dup_work = _classified_work(1)
    canonical_work = {**_classified_work(2), "openalex_id": "W_CANON"}

    save_classified(seed_id, [excluded_work, dup_work, canonical_work], base=tmp_path)
    exclude_work(seed_id, excluded_work["openalex_id"], reason="Not relevant.", base=tmp_path)
    confirm_duplicate(seed_id, dup_work["openalex_id"], canonical_id="W_CANON", base=tmp_path)

    data = build_assessment(PARALLEL_NETCDF_WORK, tmp_path)
    by_id = {w["openalex_id"]: w for w in data["works"]}

    assert by_id[excluded_work["openalex_id"]]["excluded"] is True
    assert by_id[dup_work["openalex_id"]]["duplicate"] is True
    assert data["totals"]["excluded"] == 1
    assert data["totals"]["duplicate"] == 1
    # Excluded/duplicate works never appear in the triage worklist even
    # though their underlying status is "provisional".
    assert excluded_work["openalex_id"] not in data["triage"]
    assert dup_work["openalex_id"] not in data["triage"]


def test_build_assessment_pdf_states(tmp_path):
    from wake.pdf_fetch import pdf_path

    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    never = _classified_work(0)
    cached = {**_classified_work(1), "openalex_id": "W_CACHED"}
    exhausted = {**_classified_work(2), "openalex_id": "W_EXHAUSTED"}

    save_classified(seed_id, [never, cached, exhausted], base=tmp_path)

    dest = pdf_path(seed_id, "W_CACHED", tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-1.4 " + b"x" * 3000)

    append_log_entry(seed_id, event="pdf_fetch_failed", citing_id="W_EXHAUSTED",
                      detail="tried: osti, semanticscholar", base=tmp_path)

    data = build_assessment(PARALLEL_NETCDF_WORK, tmp_path)
    by_id = {w["openalex_id"]: w for w in data["works"]}

    assert by_id[never["openalex_id"]]["pdf"]["fetch_state"] == "never-attempted"
    assert by_id["W_CACHED"]["pdf"]["cached"] is True
    assert by_id["W_CACHED"]["pdf"]["fetch_state"] == "cached"
    assert by_id["W_EXHAUSTED"]["pdf"]["fetch_state"] == "exhausted"
    assert "osti" in by_id["W_EXHAUSTED"]["pdf"]["sources_tried"]


def test_build_assessment_theme_membership_and_coverage(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    verified_work = _classified_work(0)
    provisional_work = _classified_work(1)

    save_classified(seed_id, [verified_work, provisional_work], base=tmp_path)
    add_override(seed_id, verified_work["openalex_id"], relationship="uses-as-tool", base=tmp_path)

    themes.create_theme(
        PARALLEL_NETCDF_WORK, "climate-modeling",
        title="Climate Modeling", summary="Used broadly in climate models.",
        citing_ids=[verified_work["openalex_id"], provisional_work["openalex_id"]],
        base=tmp_path,
    )
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "hpc-io",
        title="HPC I/O", summary="Used in HPC I/O systems.",
        citing_ids=[verified_work["openalex_id"]],
        base=tmp_path,
    )

    data = build_assessment(PARALLEL_NETCDF_WORK, tmp_path)
    by_id = {w["openalex_id"]: w for w in data["works"]}

    assert sorted(by_id[verified_work["openalex_id"]]["themes"]) == ["climate-modeling", "hpc-io"]
    assert by_id[provisional_work["openalex_id"]]["themes"] == ["climate-modeling"]

    theme_by_slug = {t["slug"]: t for t in data["themes"]}
    assert theme_by_slug["climate-modeling"]["counts"]["verified"] == 1
    assert theme_by_slug["climate-modeling"]["counts"]["provisional"] == 1
    assert theme_by_slug["hpc-io"]["counts"]["verified"] == 1
    assert theme_by_slug["hpc-io"]["counts"]["provisional"] == 0


# --- CLI ---------------------------------------------------------------

def test_assess_cli_no_classified_works(tmp_path, capsys):
    _seed_cached(tmp_path)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [], base=tmp_path)

    code, captured = _run_cli(["assess", PARALLEL_NETCDF_WORK["openalex_id"]], tmp_path, capsys)
    assert code == 0
    assert "No provisional works" in captured.out


def test_assess_cli_json_envelope(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work(0)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)

    code, captured = _run_cli(
        ["--json", "assess", PARALLEL_NETCDF_WORK["openalex_id"]], tmp_path, capsys,
    )
    assert code == 0
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["data"]["totals"]["classified"] == 1
    assert data["data"]["triage"] == [work["openalex_id"]]


def test_assess_cli_human_output_shows_triage(tmp_path, capsys):
    _seed_cached(tmp_path)
    work = _classified_work(0, cited_by_count=500)
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], [work], base=tmp_path)

    code, captured = _run_cli(["assess", PARALLEL_NETCDF_WORK["openalex_id"]], tmp_path, capsys)
    assert code == 0
    assert "Triage worklist" in captured.out
    assert work["openalex_id"] in captured.out
    assert "wake fetch-pdf" in captured.out
