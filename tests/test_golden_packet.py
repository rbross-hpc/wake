# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Golden-packet acceptance tests for the Dorier Mofka packet (W4414299303).

This module is the primary acceptance test for wake's schema and migration
layer, driven by the second-look assessment (20260806-wake-assessment-2.md).
It operates over a real, complete wake-out/ packet produced by a live
end-to-end run of the pipeline; see
tests/fixtures/golden-packet/README.md for provenance and contents.

What it validates
-----------------
1. Every canonical artifact loads and validates against the current Pydantic
   models (Work, ClassificationResult, EvidenceDossier, Theme, NarrativeOutline,
   NarrativeSection, Override) -- a schema-drift canary.

2. **Phase-6 acceptance test (dossier versioning):** load_dossier() returns
   schema_version=2 with relative pdf_path/extracted_text_path on the real
   dossiers -- verifies that migrate_dossier() and EvidenceDossierWrite work
   correctly end-to-end on genuinely produced artifacts, not just synthetic
   test dicts.

3. rebuild_seed() regenerates every derived .md and index from the canonical
   JSON, with no network or LLM calls -- verifies that the packet survives a
   full re-render cycle.

4. No evidence or status is lost across a rebuild: dossier/override/theme/
   section counts are preserved.

5. Deterministic double-rebuild: running rebuild_seed() twice produces the
   same set of derived files (structural stability, not byte-identical
   because timestamps may differ).

6. migrate_dossier() upgrades an artificially stripped (no schema_version)
   copy of a real dossier JSON to EVIDENCE_DOSSIER_VERSION -- verifies the
   migration chain against real field shapes, not only synthetic dicts.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from wake.build import rebuild_seed
from wake.evidence import load_dossier
from wake.models import (
    EVIDENCE_DOSSIER_VERSION,
    ClassificationResult,
    EvidenceDossier,
    NarrativeOutline,
    NarrativeSection,
    Override,
    Theme,
    Work,
    migrate_dossier,
)
from wake.report import load_overrides

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "golden-packet"
_PACKET_ROOT = _FIXTURE_ROOT / "wake-out" / "W4414299303"
_SEED_ID = "W4414299303"

_SEED_JSON = _PACKET_ROOT / "seed.json"
_CITING_JSON = _PACKET_ROOT / "citing.json"
_CLASSIFIED_JSON = _PACKET_ROOT / "classified.json"
_OVERRIDES_JSONL = _PACKET_ROOT / "overrides.jsonl"
_EVIDENCE_DIR = _PACKET_ROOT / "evidence"
_THEMES_DIR = _PACKET_ROOT / "evidence" / "themes"
_NARRATIVE_DIR = _PACKET_ROOT / "narrative"

_DOSSIER_IDS = ["W4416004498", "W7167027240"]
_VERIFIED_IDS = ["W4416004498", "W7167027240"]
_THEME_SLUGS = ["provenance-capture", "resilient-workflows"]
_SECTION_SLUGS = ["introduction", "provenance", "resilient-workflows"]


def _copy_packet(tmp_path: Path) -> Path:
    """Copy the read-only fixture into tmp_path for tests that mutate it."""
    dest = tmp_path / "wake-out" / _SEED_ID
    shutil.copytree(_PACKET_ROOT, dest)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. All canonical artifacts load and validate
# ---------------------------------------------------------------------------

def test_seed_json_validates_as_work():
    raw = json.loads(_SEED_JSON.read_text())
    work = Work.model_validate(raw)
    assert work.openalex_id == _SEED_ID
    assert work.title and "Mofka" in work.title or "persistent" in work.title.lower()
    assert work.year == 2025
    assert work.doi == "10.3389/fhpcp.2025.1638203"
    assert work.description is not None


def test_all_citing_works_validate_as_work():
    raw = json.loads(_CITING_JSON.read_text())
    works = raw if isinstance(raw, list) else raw.get("works", [])
    assert len(works) == 4
    for w in works:
        parsed = Work.model_validate(w)
        assert parsed.openalex_id.startswith("W")


def test_all_classify_sidecars_validate_as_classification_result():
    """The golden packet predates the v0.4.21 CiTO-alignment taxonomy
    refactor (its "background-mention"/"builds-on" labels were retired
    and renamed -- see vocabulary.py's RETIRED_RELATIONSHIPS), so raw
    sidecars are migrated forward before validating against the current
    RelationshipLabel Literal, mirroring the schema_version migration
    tests below."""
    from wake.models import migrate_classification_result

    for p in sorted((_PACKET_ROOT / "classify").glob("*.json")):
        raw = json.loads(p.read_text())
        migrated = migrate_classification_result(raw)
        result = ClassificationResult.model_validate(migrated)
        assert result.relationship in (
            "extends", "uses-method-from", "uses-data-from", "applies-to-domain",
            "benchmarks", "related", "cites",
        )


def test_classified_json_works_validate():
    from wake.models import migrate_classification_result

    raw = json.loads(_CLASSIFIED_JSON.read_text())
    works = raw if isinstance(raw, list) else raw.get("works", [])
    assert len(works) == 4
    for w in works:
        ClassificationResult.model_validate(migrate_classification_result(w))


def test_classify_sidecars_and_classified_json_are_unversioned_pre_phase_11(tmp_path):
    """The golden packet's classify sidecars and classified.json were
    generated before Phase 11 (classification versioning) existed -- no
    schema_version anywhere.  Phase-11 acceptance test: _load_sidecar()
    and load_classified() must migrate on read, mirroring the Phase-6/9/10
    acceptance tests."""
    from wake.classify import _load_sidecar, load_classified
    from wake.models import CLASSIFICATION_VERSION

    for p in sorted((_PACKET_ROOT / "classify").glob("*.json")):
        raw = json.loads(p.read_text())
        assert "schema_version" not in raw

    raw_aggregate = json.loads(_CLASSIFIED_JSON.read_text())
    for w in raw_aggregate["works"]:
        assert "schema_version" not in w

    _copy_packet(tmp_path)
    for citing_id in ("W4414909013", "W4416004498", "W4416004574", "W7167027240"):
        loaded = _load_sidecar(_SEED_ID, citing_id, base=tmp_path)
        assert loaded is not None
        assert loaded["schema_version"] == CLASSIFICATION_VERSION

    loaded_works = load_classified(_SEED_ID, base=tmp_path)
    assert loaded_works is not None
    assert len(loaded_works) == 4
    for w in loaded_works:
        assert w["schema_version"] == CLASSIFICATION_VERSION


def test_all_dossier_jsons_validate_as_evidence_dossier():
    dossier_paths = list(_EVIDENCE_DIR.glob("*.json"))
    assert len(dossier_paths) == len(_DOSSIER_IDS)
    for p in dossier_paths:
        raw = json.loads(p.read_text())
        parsed = EvidenceDossier.model_validate(raw)
        assert parsed.seed_openalex_id == _SEED_ID


def test_all_theme_jsons_validate_as_theme():
    for slug in _THEME_SLUGS:
        raw = json.loads((_THEMES_DIR / f"{slug}.json").read_text())
        parsed = Theme.model_validate(raw)
        assert parsed.slug == slug
        assert parsed.seed_openalex_id == _SEED_ID


def test_theme_jsons_are_unversioned_pre_phase_9_and_migrate_on_read(tmp_path):
    """The golden packet's themes were generated before Phase 9 (theme
    versioning) existed -- they have no schema_version on disk.  This is
    the Phase-9 acceptance test: load_theme() must migrate them to
    THEME_VERSION on read, exactly mirroring the Phase-6 dossier check."""
    from wake.models import THEME_VERSION
    from wake.themes import load_theme

    for slug in _THEME_SLUGS:
        raw = json.loads((_THEMES_DIR / f"{slug}.json").read_text())
        assert "schema_version" not in raw, (
            f"{slug}: fixture expected to be pre-Phase-9 (unversioned); "
            "update this test if the fixture is regenerated post-Phase-9"
        )

    _copy_packet(tmp_path)
    for slug in _THEME_SLUGS:
        result = load_theme(_SEED_ID, slug, base=tmp_path)
        assert result is not None
        assert result["schema_version"] == THEME_VERSION


def test_all_section_jsons_validate_as_narrative_section():
    for slug in _SECTION_SLUGS:
        raw = json.loads((_NARRATIVE_DIR / "sections" / f"{slug}.json").read_text())
        parsed = NarrativeSection.model_validate(raw)
        assert parsed.slug == slug


def test_outline_json_validates_as_narrative_outline():
    raw = json.loads((_NARRATIVE_DIR / "outline.json").read_text())
    parsed = NarrativeOutline.model_validate(raw)
    assert len(parsed.components) == 3


def test_section_and_outline_jsons_are_unversioned_pre_phase_10_and_migrate_on_read(tmp_path):
    """The golden packet's outline and sections were generated before
    Phase 10 (narrative versioning) existed -- no schema_version on disk.
    Phase-10 acceptance test: load_outline()/load_section() must migrate
    them on read, mirroring the Phase-6/Phase-9 acceptance tests."""
    from wake.models import NARRATIVE_OUTLINE_VERSION, NARRATIVE_SECTION_VERSION
    from wake.narrative import load_outline, load_section

    outline_raw = json.loads((_NARRATIVE_DIR / "outline.json").read_text())
    assert "schema_version" not in outline_raw
    for slug in _SECTION_SLUGS:
        section_raw = json.loads((_NARRATIVE_DIR / "sections" / f"{slug}.json").read_text())
        assert "schema_version" not in section_raw

    _copy_packet(tmp_path)
    outline_result = load_outline(_SEED_ID, base=tmp_path)
    assert outline_result is not None
    assert outline_result["schema_version"] == NARRATIVE_OUTLINE_VERSION

    for slug in _SECTION_SLUGS:
        section_result = load_section(_SEED_ID, slug, base=tmp_path)
        assert section_result is not None
        assert section_result["schema_version"] == NARRATIVE_SECTION_VERSION


def test_overrides_jsonl_validates_as_override():
    overrides = load_overrides(_SEED_ID, base=_PACKET_ROOT.parent.parent)
    assert len(overrides) == len(_VERIFIED_IDS)
    for o in overrides.values():
        Override.model_validate(o)
        assert o["verification_status"] == "verified"


def test_overrides_jsonl_is_unversioned_pre_phase_12_and_migrates_on_read():
    """The golden packet's overrides.jsonl was generated before Phase 12
    (override versioning) existed -- no schema_version on any line.
    Phase-12 acceptance test: load_overrides() must migrate each record
    on read, mirroring the Phase-6/9/10/11 acceptance tests.  Unlike the
    single-document families, the on-disk .jsonl is never rewritten by a
    read -- this is verified separately by test_models.py's
    test_load_overrides_migrates_legacy_unversioned_lines_per_record."""
    from wake.models import OVERRIDE_VERSION

    raw_lines = (_PACKET_ROOT / "overrides.jsonl").read_text().splitlines()
    raw_entries = [json.loads(line) for line in raw_lines if line.strip()]
    assert len(raw_entries) == len(_VERIFIED_IDS)
    for entry in raw_entries:
        assert "schema_version" not in entry

    overrides = load_overrides(_SEED_ID, base=_PACKET_ROOT.parent.parent)
    for o in overrides.values():
        assert o["schema_version"] == OVERRIDE_VERSION


# ---------------------------------------------------------------------------
# 2. Phase-6 acceptance test: dossier versioning on real artifacts
# ---------------------------------------------------------------------------

def test_dossier_schema_version_persisted_on_disk():
    """The real dossiers on disk have schema_version=2 -- this fixture
    predates EVIDENCE_DOSSIER_VERSION=3 (the v0.4.21 CiTO-alignment
    taxonomy refactor's relationship-label remap), so it's frozen at the
    version current when it was generated. Verifies that build_dossier's
    write site correctly persisted the validated model *as of that
    version*, and that migrate_dossier() (exercised directly in
    test_migrate_dossier_upgrades_real_stripped_dossier, and via
    load_dossier() in test_load_dossier_returns_current_schema_version)
    carries it forward to the current version on read."""
    for citing_id in _DOSSIER_IDS:
        raw = json.loads((_EVIDENCE_DIR / f"{citing_id}.json").read_text())
        assert raw.get("schema_version") == 2, (
            f"{citing_id}: fixture expected to be frozen at schema_version=2; "
            f"got {raw.get('schema_version')!r} -- update this test if the "
            "fixture is regenerated post-v0.4.21"
        )
        assert raw.get("schema_version") < EVIDENCE_DOSSIER_VERSION


def test_dossier_pdf_paths_are_relative_on_disk():
    """Real dossiers store relative pdf_path/extracted_text_path."""
    for citing_id in _DOSSIER_IDS:
        raw = json.loads((_EVIDENCE_DIR / f"{citing_id}.json").read_text())
        assert not Path(raw["pdf_path"]).is_absolute(), (
            f"{citing_id}: pdf_path should be relative, got {raw['pdf_path']!r}"
        )
        assert not Path(raw["extracted_text_path"]).is_absolute()


def test_load_dossier_returns_current_schema_version(tmp_path):
    """load_dossier() runs migrate_dossier() and returns the current
    EVIDENCE_DOSSIER_VERSION, upgrading the fixture's frozen
    schema_version=2 dossiers forward on read."""
    _copy_packet(tmp_path)
    for citing_id in _DOSSIER_IDS:
        result = load_dossier(_SEED_ID, citing_id, base=tmp_path)
        assert result is not None
        assert result["schema_version"] == EVIDENCE_DOSSIER_VERSION


def test_migrate_dossier_upgrades_real_stripped_dossier():
    """migrate_dossier() applied to a real dossier JSON with schema_version
    stripped out (simulating a pre-Phase-6 packet) returns schema_version=2
    and preserves all real fields."""
    raw = json.loads((_EVIDENCE_DIR / "W7167027240.json").read_text())
    raw.pop("schema_version", None)
    assert "schema_version" not in raw
    migrated = migrate_dossier(raw, sidecar_dir=_EVIDENCE_DIR)
    assert migrated["schema_version"] == EVIDENCE_DOSSIER_VERSION
    assert migrated["seed_openalex_id"] == _SEED_ID
    assert migrated["citing_openalex_id"] == "W7167027240"
    assert not Path(migrated["pdf_path"]).is_absolute()


def test_load_dossier_on_artificially_stripped_packet(tmp_path):
    """load_dossier() on a packet where a real dossier has its schema_version
    stripped out returns schema_version=2 (migration happens at read time)."""
    _copy_packet(tmp_path)
    json_path = tmp_path / "wake-out" / _SEED_ID / "evidence" / "W7167027240.json"
    raw = json.loads(json_path.read_text())
    raw.pop("schema_version", None)
    json_path.write_text(json.dumps(raw))
    assert "schema_version" not in json.loads(json_path.read_text())

    result = load_dossier(_SEED_ID, "W7167027240", base=tmp_path)
    assert result is not None
    assert result["schema_version"] == EVIDENCE_DOSSIER_VERSION


# ---------------------------------------------------------------------------
# 3. rebuild_seed() regenerates all derived files (no network, no LLM)
# ---------------------------------------------------------------------------

def _seed_work() -> dict:
    return json.loads(_SEED_JSON.read_text())


@pytest.mark.slow
def test_rebuild_seed_succeeds_on_real_packet(tmp_path):
    """rebuild_seed() on the real packet completes without error and
    regenerates every artifact type it is responsible for."""
    _copy_packet(tmp_path)
    result = rebuild_seed(_seed_work(), base=tmp_path, verbose=False)
    assert result["ok"] is True
    by_step = {s["step"]: s for s in result["steps"]}
    assert set(by_step["dossiers"]["rebuilt"]) == set(_DOSSIER_IDS)
    assert by_step["evidence_index"]["rebuilt"] is True
    assert set(by_step["themes"]["rebuilt"]) == set(_THEME_SLUGS)
    assert by_step["themes_index"]["rebuilt"] is True
    assert set(by_step["sections"]["rebuilt"]) == set(_SECTION_SLUGS)
    assert by_step["outline"]["rebuilt"] is True
    assert by_step["narrative"]["rebuilt"] is True
    assert by_step["wiki_orientation"]["rebuilt"] is True


# ---------------------------------------------------------------------------
# 4. No evidence or status lost across a rebuild
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_rebuild_preserves_dossier_count(tmp_path):
    _copy_packet(tmp_path)
    rebuild_seed(_seed_work(), base=tmp_path, verbose=False)
    evidence_dir = tmp_path / "wake-out" / _SEED_ID / "evidence"
    dossier_jsons = [p for p in evidence_dir.glob("*.json")]
    assert len(dossier_jsons) == len(_DOSSIER_IDS)


@pytest.mark.slow
def test_rebuild_preserves_override_count(tmp_path):
    _copy_packet(tmp_path)
    rebuild_seed(_seed_work(), base=tmp_path, verbose=False)
    overrides = load_overrides(_SEED_ID, base=tmp_path)
    assert len(overrides) == len(_VERIFIED_IDS)
    for o in overrides.values():
        assert o["verification_status"] == "verified"


@pytest.mark.slow
def test_rebuild_preserves_theme_count(tmp_path):
    _copy_packet(tmp_path)
    rebuild_seed(_seed_work(), base=tmp_path, verbose=False)
    themes_dir = tmp_path / "wake-out" / _SEED_ID / "evidence" / "themes"
    theme_jsons = [p for p in themes_dir.glob("*.json")]
    assert len(theme_jsons) == len(_THEME_SLUGS)


@pytest.mark.slow
def test_rebuild_preserves_section_count(tmp_path):
    _copy_packet(tmp_path)
    rebuild_seed(_seed_work(), base=tmp_path, verbose=False)
    sections_dir = tmp_path / "wake-out" / _SEED_ID / "narrative" / "sections"
    section_jsons = [p for p in sections_dir.glob("*.json")]
    assert len(section_jsons) == len(_SECTION_SLUGS)


@pytest.mark.slow
def test_rebuild_preserves_dossier_verification_status(tmp_path):
    """Verification status (pending-human-review vs verified) is carried
    through the rebuild via the JSON sidecar -- must not be reset."""
    _copy_packet(tmp_path)
    rebuild_seed(_seed_work(), base=tmp_path, verbose=False)
    for citing_id in _DOSSIER_IDS:
        raw = json.loads(
            (tmp_path / "wake-out" / _SEED_ID / "evidence" / f"{citing_id}.json").read_text()
        )
        assert raw["verification_status"] in ("pending-human-review", "verified")


# ---------------------------------------------------------------------------
# 5. Deterministic double-rebuild (structural stability)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_double_rebuild_produces_same_derived_file_set(tmp_path):
    """Running rebuild_seed() twice produces the same set of .md files.
    Byte-identical output is not required (timestamps differ), but
    structural identity is: the same files exist, none added or removed."""
    _copy_packet(tmp_path)
    rebuild_seed(_seed_work(), base=tmp_path, verbose=False)
    after_first = {
        str(p.relative_to(tmp_path / "wake-out" / _SEED_ID))
        for p in (tmp_path / "wake-out" / _SEED_ID).rglob("*.md")
    }
    rebuild_seed(_seed_work(), base=tmp_path, verbose=False)
    after_second = {
        str(p.relative_to(tmp_path / "wake-out" / _SEED_ID))
        for p in (tmp_path / "wake-out" / _SEED_ID).rglob("*.md")
    }
    assert after_first == after_second


# ---------------------------------------------------------------------------
# 6. Packet structural sanity (non-rebuild)
# ---------------------------------------------------------------------------

def test_evidence_log_md_exists_and_is_non_empty():
    """evidence/log.md is append-only with no JSON backing; it must be
    included in the vendored fixture since it cannot be regenerated."""
    log = _EVIDENCE_DIR / "log.md"
    assert log.exists()
    assert log.stat().st_size > 0


def test_pdf_extraction_caches_exist():
    """pdfs/*.pdf.json extraction caches must be present for the dossiers
    that have them (PDFs were stripped, but .pdf.json files stay)."""
    for citing_id in _DOSSIER_IDS:
        cache = _PACKET_ROOT / "pdfs" / f"{citing_id}.pdf.json"
        assert cache.exists(), f"Missing extraction cache for {citing_id}"
        data = json.loads(cache.read_text())
        pages = data if isinstance(data, list) else data.get("pages", [])
        assert len(pages) > 0, (
            f"Extraction cache for {citing_id} should have a non-empty pages list"
        )


def test_seed_has_description():
    """The describe stage ran; seed.json must carry a non-empty description."""
    raw = json.loads(_SEED_JSON.read_text())
    assert raw.get("description"), "seed.json is missing a description field"
    assert len(raw["description"]) > 50


def test_narrative_md_exists_and_references_seed():
    """narrative.md was stitched; it should reference the seed via [ref:SEED]
    or the narrative prose we authored."""
    narrative_md = _PACKET_ROOT / "narrative.md"
    assert narrative_md.exists()
    content = narrative_md.read_text()
    assert "Mofka" in content
