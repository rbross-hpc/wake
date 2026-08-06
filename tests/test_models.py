# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.models -- verifies the new Pydantic domain models
against the *real* dict shapes wake's existing functions actually
produce, not just the models' own internal consistency. This is the
safety net for the "explicit domain models" phase of the structural
hardening effort (PLAN.md "Phase 3", BACKLOG.md Theme L): every model
below is round-tripped against a real `classify_one`/`build_dossier`/
`create_theme`/`create_outline`/`create_section`/`add_override` call
(LLM/network mocked, same fixtures/patterns as the modules' own test
files), so a future shape drift in either direction gets caught here.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from wake import evidence, narrative, themes
from wake.classify import classify_one, save_classified
from wake.models import (
    EVIDENCE_DOSSIER_VERSION,
    SCHEMA_VERSION,
    ArtifactReference,
    ClassificationResult,
    EvidenceDossier,
    EvidenceDossierWrite,
    NarrativeOutline,
    NarrativeSection,
    Override,
    Theme,
    Work,
    migrate_dossier,
)
from wake.report import add_override, load_overrides
from wake.vocabulary import CANONICAL_RELATIONSHIPS

from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS

_FIXTURE = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"


def _copy_fixture_pdf(tmp_path: Path) -> Path:
    dest = tmp_path / "pdfs" / "citing.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_FIXTURE, dest)
    return dest


# --- module-level invariants ------------------------------------------

def test_canonical_relationships_is_single_source():
    """Both models.py and classify.py now import CANONICAL_RELATIONSHIPS
    from wake.vocabulary -- confirm the single source matches what
    classify.py exposes (structural identity, not a copied tuple)."""
    from wake.classify import CANONICAL_RELATIONSHIPS as CLS_CR
    from wake.models import CANONICAL_RELATIONSHIPS as MDL_CR
    assert MDL_CR is CLS_CR
    assert MDL_CR == CANONICAL_RELATIONSHIPS


def test_models_module_only_imports_vocabulary_from_wake():
    """Enforces the design constraint: models.py may import from
    wake.vocabulary (the dependency-free vocabulary module) but from no
    other wake.* module."""
    import ast
    _ALLOWED = {"wake.vocabulary"}
    src = Path(__file__).parent.parent / "wake" / "models.py"
    tree = ast.parse(src.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("wake"):
            if node.module not in _ALLOWED:
                pytest.fail(f"models.py imports from {node.module!r} -- only wake.vocabulary is allowed")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("wake.") and alias.name not in _ALLOWED:
                    pytest.fail(f"models.py imports {alias.name!r} -- only wake.vocabulary is allowed")


# --- Work ----------------------------------------------------------------

def test_work_validates_real_openalex_summary_shape():
    work = Work.model_validate(PARALLEL_NETCDF_WORK)
    assert work.openalex_id == PARALLEL_NETCDF_WORK["openalex_id"]
    assert work.schema_version == SCHEMA_VERSION


def test_work_accepts_missing_optional_fields():
    minimal = {"openalex_id": "W123"}
    work = Work.model_validate(minimal)
    assert work.title is None
    assert work.authors == []
    assert work.cited_by_count == 0


def test_work_round_trips_through_json_dict():
    work = Work.model_validate(PARALLEL_NETCDF_WORK)
    dumped = work.to_json_dict()
    # Every original key wake actually reads elsewhere must survive.
    for key in ("openalex_id", "title", "authors", "cited_by_count"):
        assert dumped[key] == PARALLEL_NETCDF_WORK[key]
    # Round-trips cleanly.
    assert Work.model_validate(dumped).openalex_id == work.openalex_id


def test_work_tolerates_extra_enrichment_fields():
    """seed.py/describe.py/backfill.py/seed_pdf.py all bolt fields onto a
    Work dict after creation -- the model must not reject those."""
    enriched = {
        **PARALLEL_NETCDF_WORK,
        "resolved_at": "2026-01-01T00:00:00",
        "description": "A contribution paragraph.",
        "described_at": "2026-01-01T00:01:00",
        "abstract_source": "osti",
        "seed_pdf": {"path": "/x/seed.pdf", "source": "osti", "fetched_at": "2026-01-01T00:02:00"},
    }
    work = Work.model_validate(enriched)
    assert work.description == "A contribution paragraph."
    assert work.seed_pdf["source"] == "osti"


# --- ClassificationResult -------------------------------------------------

def _fake_chat_json(system, user, model_role="classify", model=None, temperature=0, cost_sink=None):
    return {"relationship": "uses-as-tool", "confidence": 0.8, "justification": "fake"}


def test_classification_result_validates_real_classify_one_output():
    with patch("wake.classify.chat_json", side_effect=_fake_chat_json):
        result = classify_one(PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS[0], record_cost=False)

    parsed = ClassificationResult.model_validate(result)
    assert parsed.relationship == "uses-as-tool"
    assert parsed.verification_status == "provisional"
    assert len(parsed.relationships) >= 1
    assert "strength" not in result  # still true of the raw dict; model doesn't add it either
    assert "strength" not in parsed.to_json_dict()


def test_classification_result_validates_real_sidecar_shape(tmp_path):
    """save_classified's sidecar adds prompt_version/model/classified_at
    on top of classify_one's own fields -- must still validate."""
    with patch("wake.classify.chat_json", side_effect=_fake_chat_json):
        result = classify_one(PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS[0], record_cost=False)
    sidecar = {**result, "prompt_version": "classify-2", "model": "Claude Sonnet 4.6", "classified_at": "2026-01-01T00:00:00"}
    parsed = ClassificationResult.model_validate(sidecar)
    assert parsed.prompt_version == "classify-2"


def test_classification_result_rejects_empty_relationships():
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate({
            "relationship": "extends", "confidence": 0.9, "justification": "x",
            "relationships": [],
        })


def test_classification_result_rejects_unknown_label():
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate({
            "relationship": "not-a-real-label", "confidence": 0.9, "justification": "x",
            "relationships": [{"label": "not-a-real-label", "confidence": 0.9, "justification": "x"}],
        })


# --- EvidenceDossier -------------------------------------------------------

def _fake_verification_response():
    return {
        "relationship": "extends",
        "confidence": 0.9,
        "justification": "The full text clearly shows a direct extension.",
        "agrees_with_provisional": False,
        "quotes": [{"page": 2, "text": "We directly extend the seed's method here.", "note": "x"}],
    }


def _build_dossier(tmp_path):
    dest = _copy_fixture_pdf(tmp_path)
    classified_work = {
        **SAMPLE_CITING_WORKS[0],
        "relationship": "uses-as-tool",
        "confidence": 0.4,
        "justification": "Likely uses PnetCDF for I/O.",
        "has_abstract": True,
        "verification_status": "provisional",
    }
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(dest), "source": "osti",
    }), patch("wake.evidence.chat_json", return_value=_fake_verification_response()):
        return evidence.build_dossier(PARALLEL_NETCDF_WORK, classified_work, base=tmp_path, verbose=False)


def test_evidence_dossier_validates_real_build_dossier_json_sidecar(tmp_path):
    result = _build_dossier(tmp_path)
    assert result["ok"] is True

    sidecar_path = Path(result["dossier_json_path"])
    sidecar = json.loads(sidecar_path.read_text())
    parsed = EvidenceDossier.model_validate(sidecar)

    assert parsed.seed_openalex_id == PARALLEL_NETCDF_WORK["openalex_id"]
    assert parsed.verification_status == "pending-human-review"
    assert parsed.human_verification is None
    assert parsed.schema_version == EVIDENCE_DOSSIER_VERSION
    assert sidecar["schema_version"] == EVIDENCE_DOSSIER_VERSION


def test_evidence_dossier_validates_after_human_verification(tmp_path):
    result = _build_dossier(tmp_path)
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]

    add_override(
        seed_id, citing_id, relationship="extends", justification="Confirmed by a human.",
        base=tmp_path, verification_source="evidence-dossier",
    )

    sidecar_path = Path(result["dossier_json_path"])
    sidecar = json.loads(sidecar_path.read_text())
    parsed = EvidenceDossier.model_validate(sidecar)
    assert parsed.verification_status == "verified"
    assert parsed.human_verification is not None
    assert "verified_at" in parsed.human_verification


# --- migrate_dossier / EvidenceDossierWrite (Phase 6) ---------------------

_MINIMAL_DOSSIER_V0: dict = {
    "seed_openalex_id": "W1",
    "citing_openalex_id": "W2",
    "generated_at": "2025-01-01T00:00:00",
    "prompt_version": "v1",
    "model": "gpt-4o",
    "pdf_path": "/absolute/path/to/citing.pdf",
    "extracted_text_path": "/absolute/path/to/citing.pdf.json",
    "provisional": {"relationship": "extends", "confidence": 0.5, "justification": "x", "quotes": []},
    "proposed": {"relationship": "extends", "confidence": 0.9, "justification": "y"},
}


def test_migrate_dossier_v0_no_sidecar_dir():
    raw = dict(_MINIMAL_DOSSIER_V0)
    migrated = migrate_dossier(raw)
    assert migrated["schema_version"] == EVIDENCE_DOSSIER_VERSION
    assert migrated["pdf_path"] == "/absolute/path/to/citing.pdf"


def test_migrate_dossier_v0_with_sidecar_dir(tmp_path):
    sidecar_dir = tmp_path / "evidence"
    sidecar_dir.mkdir()
    raw = dict(_MINIMAL_DOSSIER_V0)
    migrated = migrate_dossier(raw, sidecar_dir=sidecar_dir)
    assert migrated["schema_version"] == EVIDENCE_DOSSIER_VERSION
    assert not Path(migrated["pdf_path"]).is_absolute()
    assert not Path(migrated["extracted_text_path"]).is_absolute()


def test_migrate_dossier_already_current():
    raw = {**_MINIMAL_DOSSIER_V0, "schema_version": EVIDENCE_DOSSIER_VERSION, "pdf_path": "../pdfs/W2.pdf", "extracted_text_path": "../pdfs/W2.pdf.json"}
    migrated = migrate_dossier(raw)
    assert migrated["schema_version"] == EVIDENCE_DOSSIER_VERSION
    assert migrated["pdf_path"] == "../pdfs/W2.pdf"


def test_migrate_dossier_idempotent(tmp_path):
    sidecar_dir = tmp_path / "evidence"
    sidecar_dir.mkdir()
    raw = dict(_MINIMAL_DOSSIER_V0)
    once = migrate_dossier(raw, sidecar_dir=sidecar_dir)
    twice = migrate_dossier(once, sidecar_dir=sidecar_dir)
    assert once == twice


def test_old_unversioned_dossier_round_trips_through_load_dossier(tmp_path):
    import json as _json

    from wake.evidence import load_dossier
    seed_id = "W1"
    citing_id = "W2"
    sidecar_dir = tmp_path / "wake-out" / seed_id / "evidence"
    sidecar_dir.mkdir(parents=True)
    sidecar_path = sidecar_dir / f"{citing_id}.json"
    sidecar_path.write_text(_json.dumps(_MINIMAL_DOSSIER_V0))
    result = load_dossier(seed_id, citing_id, base=tmp_path)
    assert result is not None
    assert result["schema_version"] == EVIDENCE_DOSSIER_VERSION
    assert not Path(result["pdf_path"]).is_absolute()


def test_new_dossier_persists_schema_version_on_disk(tmp_path):
    import json as _json
    result = _build_dossier(tmp_path)
    assert result["ok"] is True
    sidecar = _json.loads(Path(result["dossier_json_path"]).read_text())
    assert sidecar.get("schema_version") == EVIDENCE_DOSSIER_VERSION


def test_evidence_dossier_write_rejects_unknown_field():
    good = {**_MINIMAL_DOSSIER_V0, "schema_version": 2, "pdf_path": "../p.pdf", "extracted_text_path": "../p.pdf.json"}
    with pytest.raises(ValueError, match="schema"):
        EvidenceDossierWrite.validate_or_raise({**good, "typo_field": "oops"}, context="test")


def test_evidence_dossier_read_model_accepts_unknown_field():
    raw = {**_MINIMAL_DOSSIER_V0, "future_field": "ok"}
    parsed = EvidenceDossier.model_validate(raw)
    assert parsed.seed_openalex_id == "W1"


# --- Theme -----------------------------------------------------------------

def _classified_work(idx: int, **overrides) -> dict:
    return {
        **SAMPLE_CITING_WORKS[idx],
        "relationship": "uses-as-tool",
        "confidence": 0.4,
        "justification": "Likely uses PnetCDF for I/O.",
        "has_abstract": True,
        "verification_status": "provisional",
        **overrides,
    }


def test_theme_validates_real_create_theme_json_sidecar(tmp_path):
    works = [_classified_work(0), _classified_work(1)]
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    save_classified(seed_id, works, base=tmp_path)

    themes.create_theme(
        PARALLEL_NETCDF_WORK, "earth-system", title="Earth System Use", summary="Summary.",
        citing_ids=[w["openalex_id"] for w in works], base=tmp_path,
    )

    json_path = themes.theme_json_path(seed_id, "earth-system", tmp_path)
    sidecar = json.loads(json_path.read_text())
    parsed = Theme.model_validate(sidecar)
    assert parsed.slug == "earth-system"
    assert parsed.theme_status == "draft"
    assert len(parsed.citing_works) == 2
    assert set(parsed.needs_evidence) == {w["openalex_id"] for w in works}


def test_theme_rejects_invalid_slug():
    with pytest.raises(ValidationError):
        Theme.model_validate({
            "seed_openalex_id": "W1", "slug": "Not A Slug!", "title": "T", "summary": "S",
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        })


# --- NarrativeOutline / NarrativeSection -----------------------------------

def test_narrative_outline_validates_real_create_outline_json(tmp_path):
    works = [_classified_work(0)]
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    save_classified(seed_id, works, base=tmp_path)
    themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[works[0]["openalex_id"]], base=tmp_path,
    )
    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[
            {"slug": "intro", "title": "Introduction", "kind": "free"},
            {"slug": "impact", "title": "Impact", "kind": "theme", "theme_slugs": ["t1"]},
        ],
        base=tmp_path,
    )

    json_path = narrative.outline_json_path(seed_id, tmp_path)
    sidecar = json.loads(json_path.read_text())
    parsed = NarrativeOutline.model_validate(sidecar)
    assert len(parsed.components) == 2
    assert parsed.components[1].kind == "theme"
    assert parsed.components[1].theme_slugs == ["t1"]


def test_narrative_section_validates_real_create_section_json(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    narrative.create_outline(
        PARALLEL_NETCDF_WORK,
        components=[{"slug": "intro", "title": "Introduction", "kind": "free"}],
        base=tmp_path,
    )
    narrative.create_section(
        PARALLEL_NETCDF_WORK, "intro", title="Introduction",
        prose="PnetCDF is a widely used I/O library.", base=tmp_path,
    )

    json_path = narrative.section_json_path(seed_id, "intro", tmp_path)
    sidecar = json.loads(json_path.read_text())
    parsed = NarrativeSection.model_validate(sidecar)
    assert parsed.kind == "free"
    assert parsed.section_status == "draft"
    assert "PnetCDF" in parsed.prose


# --- Override ---------------------------------------------------------------

def test_override_validates_real_overrides_jsonl_entry(tmp_path):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = SAMPLE_CITING_WORKS[0]["openalex_id"]
    add_override(
        seed_id, citing_id, relationship="extends", justification="Human-confirmed.",
        base=tmp_path, verification_source="human-judgment",
    )
    overrides = load_overrides(seed_id, tmp_path)
    entry = overrides[citing_id]
    parsed = Override.model_validate(entry)
    assert parsed.relationship == "extends"
    assert parsed.verification_status == "verified"
    assert parsed.confidence == 1.0


def test_override_rejects_unknown_relationship():
    with pytest.raises(ValidationError):
        Override.model_validate({
            "citing_id": "W1", "relationship": "not-a-real-label",
            "verification_source": "human-judgment", "overridden_at": "2026-01-01T00:00:00",
        })


# --- ArtifactReference -------------------------------------------------------

def test_artifact_reference_parses_seed_marker():
    ref = ArtifactReference.parse("SEED")
    assert ref.kind == "seed"
    assert ref.id == "SEED"


def test_artifact_reference_parses_citing_work_marker():
    ref = ArtifactReference.parse("W2156077349")
    assert ref.kind == "citing_work"
    assert ref.id == "W2156077349"


# --- validate_or_raise: the write-site guard contract ----------------------
# classify.py/evidence.py/evidence_wiki.py/themes.py/narrative.py/report.py
# all call <Model>.validate_or_raise(payload, context=...) immediately before
# atomic_write_json/atomic_write_text on every write path for these five
# artifact types (see PLAN.md "Phase 3" for the full list of call sites).
# These tests pin the *public contract* of that guard -- a plain ValueError,
# not pydantic's own ValidationError, carrying the model name and context in
# the message -- so callers never need to import pydantic themselves.

def test_validate_or_raise_raises_plain_value_error_not_pydantic_error():
    with pytest.raises(ValueError) as exc_info:
        ClassificationResult.validate_or_raise({"relationship": "extends"}, context="a test payload")
    assert not isinstance(exc_info.value, ValidationError)
    assert "ClassificationResult" in str(exc_info.value)
    assert "a test payload" in str(exc_info.value)


def test_validate_or_raise_passes_through_a_valid_payload():
    result = ClassificationResult.validate_or_raise({
        "relationship": "extends", "confidence": 0.9, "justification": "x",
        "relationships": [{"label": "extends", "confidence": 0.9, "justification": "x"}],
    })
    assert isinstance(result, ClassificationResult)


def test_classify_write_sidecar_refuses_malformed_payload(tmp_path):
    """The actual write-site guard in classify.py::_write_sidecar --
    not just the model in isolation."""
    from wake.classify import _write_sidecar

    with pytest.raises(ValueError, match="ClassificationResult"):
        _write_sidecar("W1", "W2", {"relationship": "extends"}, base=tmp_path)
    # Nothing was written -- the guard runs before any filesystem I/O.
    assert not (tmp_path / "wake-out").exists()


def test_add_override_refuses_unknown_relationship_label(tmp_path):
    """The actual write-site guard in report.py::add_override."""
    with pytest.raises(ValueError, match="Override"):
        add_override(
            "W1", "W2", relationship="not-a-real-label", base=tmp_path,
            verification_source="human-judgment",
        )
    assert load_overrides("W1", tmp_path) == {}


def test_create_theme_write_guard_is_reachable_but_never_trips_on_valid_input(tmp_path):
    """themes.create_theme always builds a schema-valid payload internally
    (title/summary are free-form strings, so there's no realistic
    malformed-input path through the public API) -- this test documents
    that the guard is present and passes on the real, valid payload
    create_theme actually builds, complementing the stricter
    _write_sidecar/add_override direct-malformed-input tests above."""
    works = [_classified_work(0)]
    save_classified(PARALLEL_NETCDF_WORK["openalex_id"], works, base=tmp_path)
    result = themes.create_theme(
        PARALLEL_NETCDF_WORK, "t1", title="T", summary="S",
        citing_ids=[works[0]["openalex_id"]], base=tmp_path,
    )
    assert result["ok"] is True
