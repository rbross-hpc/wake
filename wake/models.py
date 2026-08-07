# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Explicit domain models for wake's core artifacts.

Phase 6 (v0.4.6) extended this module with genuine dossier versioning:
``EVIDENCE_DOSSIER_VERSION``, ``migrate_dossier()``, and
``EvidenceDossierWrite`` turn the advisory schema layer into real persistent
format management for dossiers.  See PLAN.md v0.4.6 for the full account.

``SCHEMA_VERSION`` (= 1) is the baseline version all other artifact families
default to.  ``EVIDENCE_DOSSIER_VERSION`` (= 2) is the current on-disk
version for newly written dossiers; old packets with no ``schema_version``
key are treated as v0 and migrated forward through ``migrate_dossier()``.
Nothing in this module talks to the filesystem or to an LLM.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from wake.vocabulary import CANONICAL_RELATIONSHIPS, RelationshipLabel  # noqa: F401

SCHEMA_VERSION = 1

EVIDENCE_DOSSIER_VERSION = 2

VerificationStatus = Literal["provisional", "pending-human-review", "verified"]
VerificationSource = Literal["human-judgment", "evidence-dossier"]
ThemeStatus = Literal["draft", "confirmed"]
SectionStatus = Literal["draft", "confirmed"]
SectionKind = Literal["theme", "free"]

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_slug(value: str) -> str:
    if not _SLUG_RE.match(value):
        raise ValueError(
            f"Invalid slug {value!r}: must be lowercase alphanumeric "
            "segments separated by single hyphens (e.g. 'earth-system-modeling')."
        )
    return value


_M = TypeVar("_M", bound="WakeModel")


class WakeModel(BaseModel):
    """Shared base: tolerant of extra keys (forward/backward compat with
    fields this pass hasn't modeled yet -- see PLAN.md's phased approach),
    and provides a uniform ``to_json_dict()`` for atomic_write_json call
    sites."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    def to_json_dict(self) -> dict[str, Any]:
        """Dict shape suitable for ``io.atomic_write_json`` -- excludes
        unset optional fields (e.g. a not-yet-verified dossier has no
        ``human_verification`` key at all, matching today's dict-based
        behavior) rather than writing them out as null."""
        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def validate_or_raise(cls: type[_M], data: dict[str, Any], *, context: str = "") -> _M:
        """Validate *data* against this model, raising a ``ValueError``
        (not pydantic's own ``ValidationError``) with a wake-flavored
        message on failure -- callers (write-site guards in classify.py/
        evidence.py/themes.py/narrative.py/report.py) can catch a single,
        consistent exception type without importing pydantic themselves.
        """
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            where = f" for {context}" if context else ""
            raise ValueError(
                f"Refusing to write data{where} that doesn't match "
                f"wake.models.{cls.__name__}'s schema: {exc}"
            ) from exc


class Work(WakeModel):
    """A seed or citing work, as summarized from OpenAlex.

    Mirrors sources/openalex.py::_summarize_work()'s output exactly, plus
    the fields later stages append (abstract_source, description, ...).
    Deliberately permissive on most fields (OpenAlex data is frequently
    incomplete) -- only openalex_id is truly required.
    """

    schema_version: int = SCHEMA_VERSION
    openalex_id: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    author_ids: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    venue_type: str | None = None
    doi: str | None = None
    url: str | None = None
    cited_by_count: int = 0
    type: str | None = None
    abstract: str | None = None
    topics: list[str] = Field(default_factory=list)

    # Enrichment fields, added post-creation by other stages -- see
    # seed.py/describe.py/backfill.py/gaps.py/seed_pdf.py.
    abstract_source: str | None = None
    resolved_at: str | None = None
    description: str | None = None
    described_at: str | None = None
    seed_pdf: dict[str, Any] | None = None


class RelationshipFacet(WakeModel):
    """One relationship judgment -- a citing work can carry up to
    MAX_FACETS of these (see classify.py's multi-facet classification).
    """

    label: RelationshipLabel
    confidence: float
    justification: str = ""
    quotes: list[dict[str, Any]] = Field(default_factory=list)
    verified: bool | None = None


class ClassificationResult(WakeModel):
    """classify.py::classify_one()'s return shape. ``relationship``/
    ``confidence``/``justification`` are legacy scalars mirroring the top
    (most-confident) facet, kept for read-compat with every existing
    consumer; ``relationships`` is the canonical multi-facet list.
    """

    schema_version: int = SCHEMA_VERSION
    relationship: RelationshipLabel
    confidence: float
    justification: str = ""
    relationships: list[RelationshipFacet] = Field(default_factory=list)
    has_abstract: bool = False
    verification_status: Literal["provisional"] = "provisional"
    author_overlap: bool = False
    overlapping_authors: list[str] = Field(default_factory=list)

    # Sidecar metadata (present once written by classify_all, absent on
    # the raw classify_one() return value).
    prompt_version: str | None = None
    model: str | None = None
    classified_at: str | None = None

    @field_validator("relationships")
    @classmethod
    def _non_empty_facets(cls, v: list[RelationshipFacet]) -> list[RelationshipFacet]:
        if not v:
            raise ValueError("relationships must contain at least one facet")
        return v


CLASSIFICATION_VERSION = 1


class ClassificationResultWrite(ClassificationResult):
    """Strict write variant of ClassificationResult -- see ThemeWrite/
    EvidenceDossierWrite for the read-permissive/write-strict rationale.
    Used only for the per-work classify/<id>.json sidecar
    (_write_sidecar), which always carries a real classification
    (classify_one()'s return always has "relationship" set); the
    aggregate classified.json's works[] entries are validated more
    loosely by ClassifiedFile below, since that list also legitimately
    contains error/unclassified entries with no "relationship" key at
    all (see classify_all()'s error-handling branch, report.py:327's
    `if w.get("relationship")` filter)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


CLASSIFIED_FILE_VERSION = 1


class ClassifiedFile(WakeModel):
    """classify.py::save_classified()'s classified.json wrapper shape.

    Deliberately permissive on `works` (list[dict[str, Any]], not
    list[ClassificationResult]): a citing work whose classification call
    errored is stored as `{**work, "error": ..., "error_at": ...}` with no
    "relationship" key at all (classify.py's classify_all(), the
    error-handling branch) -- downstream consumers (report.py's bake,
    `[w for w in citing_works if w.get("relationship")]`) deliberately
    treat these as unclassified rather than rejecting them, so this
    wrapper model must accept the same shape.  Each entry that *is* a
    real classification is still schema_version-stamped by
    migrate_classified() below, but not forced through
    ClassificationResult's required-field validation here.
    """

    schema_version: int = CLASSIFIED_FILE_VERSION
    seed_openalex_id: str
    classified_at: str
    count: int
    works: list[dict[str, Any]] = Field(default_factory=list)


class ClassifiedFileWrite(ClassifiedFile):
    """Strict write variant of ClassifiedFile -- rejects unknown
    *wrapper-level* fields (seed_openalex_id/classified_at/count/works);
    does not additionally constrain each works[] entry (see ClassifiedFile
    docstring for why)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def migrate_classification_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate one raw classify/<id>.json sidecar dict forward to
    CLASSIFICATION_VERSION.  Idempotent.  v0 (no key) -> v1: stamp
    schema_version -- no shape change."""
    result = dict(raw)
    if result.get("schema_version", 0) < 1:
        result["schema_version"] = CLASSIFICATION_VERSION
    return result


def migrate_classified(raw: Any) -> dict[str, Any]:
    """Migrate a raw classified.json payload forward to
    CLASSIFIED_FILE_VERSION.

    Idempotent.  Two migration steps, both formalizing normalization that
    classify.py's load_classified() already did implicitly:

    v0 (bare list, the pre-wrapper format) -> v1: wrap as
    ``{"works": raw, "count": len(raw), "schema_version": 1, ...}``.  No
    `seed_openalex_id`/`classified_at` are recoverable from a bare list,
    so those keys are set to "" if not otherwise derivable -- callers
    should treat a migrated-from-v0 wrapper's `seed_openalex_id`/
    `classified_at` as unreliable (this shape hasn't been produced by any
    wake version this migration chain covers targeting real usage; it
    predates schema_version existing at all).

    v1 (wrapper, no schema_version) -> v1 (stamped): add schema_version:
    1 -- no shape change otherwise.

    Each entry in the resulting `works` list that carries a "relationship"
    key (i.e. is a real classification, not an error/unclassified entry)
    also gets schema_version-stamped via migrate_classification_result().
    """
    if isinstance(raw, list):
        migrated_works = [
            migrate_classification_result(w) if isinstance(w, dict) and "relationship" in w else w
            for w in raw
        ]
        return {
            "schema_version": CLASSIFIED_FILE_VERSION,
            "seed_openalex_id": "",
            "classified_at": "",
            "count": len(migrated_works),
            "works": migrated_works,
        }

    result = dict(raw)
    works = result.get("works") or []
    result["works"] = [
        migrate_classification_result(w) if isinstance(w, dict) and "relationship" in w else w
        for w in works
    ]
    if result.get("schema_version", 0) < 1:
        result["schema_version"] = CLASSIFIED_FILE_VERSION
    return result


class EvidenceQuote(WakeModel):
    page: int | None = None
    text: str
    note: str = ""


class EvidenceDossier(WakeModel):
    """evidence.py::build_dossier()'s JSON sidecar shape
    (evidence/<citing_id>.json)."""

    schema_version: int = SCHEMA_VERSION
    seed_openalex_id: str
    citing_openalex_id: str
    citing_title: str | None = None
    citing_authors: list[str] = Field(default_factory=list)
    generated_at: str
    prompt_version: str
    model: str
    pdf_path: str
    pdf_source: str | None = None
    extracted_text_path: str
    citing_cited_by_count: int = 0
    verification_status: Literal["pending-human-review", "verified"] = "pending-human-review"
    provisional: dict[str, Any]
    proposed: dict[str, Any]
    quotes: list[dict[str, Any]] = Field(default_factory=list)
    author_overlap: bool = False
    overlapping_authors: list[str] = Field(default_factory=list)
    human_verification: dict[str, Any] | None = None


class EvidenceDossierWrite(EvidenceDossier):
    """Strict write variant of EvidenceDossier.

    Read paths (``load_dossier``, index rebuilds in evidence_wiki.py) use
    the permissive ``EvidenceDossier`` (``extra="allow"``) so that old or
    forward-versioned JSON is always tolerated.  Write paths use this
    subclass, which sets ``extra="forbid"``, so a misspelled or obsolete
    field in a newly constructed payload is caught at write time rather
    than silently persisted.

    The on-disk shape is identical to ``EvidenceDossier``; only validation
    strictness differs.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def migrate_dossier(
    raw: dict[str, Any],
    *,
    sidecar_dir: Path | None = None,
) -> dict[str, Any]:
    """Migrate a raw dossier dict forward to ``EVIDENCE_DOSSIER_VERSION``.

    Idempotent: calling on an already-current dict is a no-op (returns the
    same dict unchanged if no migration step touches it).

    ``sidecar_dir`` is the directory that contains the dossier's ``.json``
    file.  It is used only for the v1 → v2 path-normalization step; when
    ``None`` (e.g. in unit tests that don't touch the filesystem) that step
    is skipped.

    Migration chain
    ---------------
    v0 (no key)  →  v1  Add ``schema_version: 1``.  No shape change; the
                        read model has always defaulted the missing key to 1,
                        so this only makes the implicit explicit.

    v1            →  v2  Normalize legacy absolute ``pdf_path`` and
                        ``extracted_text_path`` values to paths relative to
                        ``sidecar_dir``.  New dossiers have stored relative
                        paths since the write-order fix in v0.4.3; older
                        packets written before that convention store absolute
                        paths.  ``rerender_dossier_md`` previously did this
                        opportunistically at render time; the migration moves
                        it to read time so any load path benefits, not only
                        rerenders.  Bump ``schema_version`` to 2.
    """
    result = dict(raw)
    version = result.get("schema_version", 0)

    if version < 1:
        result["schema_version"] = 1
        version = 1

    if version < 2:
        if sidecar_dir is not None:
            for field_name in ("pdf_path", "extracted_text_path"):
                value = result.get(field_name)
                if value and Path(value).is_absolute():
                    result[field_name] = os.path.relpath(value, sidecar_dir)
        result["schema_version"] = 2
        version = 2

    return result


class ThemeWork(WakeModel):
    citing_id: str
    status: Literal["verified", "proposed", "provisional", "unclassified"]
    has_dossier: bool = False
    title: str | None = None


class Theme(WakeModel):
    """themes.py::create_theme()'s JSON sidecar shape
    (evidence/themes/<slug>.json)."""

    schema_version: int = SCHEMA_VERSION
    seed_openalex_id: str
    slug: str
    title: str
    summary: str
    theme_status: ThemeStatus = "draft"
    created_at: str
    updated_at: str
    citing_works: list[ThemeWork] = Field(default_factory=list)
    needs_evidence: list[str] = Field(default_factory=list)
    confirmed_at: str | None = None

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, v: str) -> str:
        return _validate_slug(v)


THEME_VERSION = 1


class ThemeWrite(Theme):
    """Strict write variant of Theme -- see EvidenceDossierWrite for the
    read-permissive/write-strict rationale.  Read paths (load_theme, and
    the glob-scan bypass readers in evidence_wiki.py/evidence.py/themes.py/
    report.py that load every theme sidecar for derived counts/backlinks)
    use the permissive Theme (extra="allow"); write paths (create_theme,
    confirm_theme) use this subclass, which sets extra="forbid"."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def migrate_theme(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate a raw theme dict forward to THEME_VERSION.

    Idempotent.  v0 (no key) -> v1: add schema_version: 1 -- no shape
    change; there is no legacy-shape normalization for themes (unlike
    dossiers' absolute/relative path fixup), so this migration only makes
    the implicit default explicit.
    """
    result = dict(raw)
    if result.get("schema_version", 0) < 1:
        result["schema_version"] = THEME_VERSION
    return result


class NarrativeComponent(WakeModel):
    slug: str
    title: str
    kind: SectionKind
    theme_slugs: list[str] = Field(default_factory=list)

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, v: str) -> str:
        return _validate_slug(v)


class NarrativeOutline(WakeModel):
    """narrative.py::create_outline()'s JSON sidecar shape
    (narrative/outline.json)."""

    schema_version: int = SCHEMA_VERSION
    seed_openalex_id: str
    components: list[NarrativeComponent] = Field(default_factory=list)
    created_at: str
    updated_at: str


NARRATIVE_OUTLINE_VERSION = 1


class NarrativeOutlineWrite(NarrativeOutline):
    """Strict write variant of NarrativeOutline -- see ThemeWrite/
    EvidenceDossierWrite for the read-permissive/write-strict rationale.
    Outline has no bypass readers (it's a singleton file, always read via
    load_outline)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def migrate_outline(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate a raw narrative outline dict forward to
    NARRATIVE_OUTLINE_VERSION.  Idempotent.  v0 (no key) -> v1: stamp
    schema_version -- no shape change."""
    result = dict(raw)
    if result.get("schema_version", 0) < 1:
        result["schema_version"] = NARRATIVE_OUTLINE_VERSION
    return result


class NarrativeSection(WakeModel):
    """narrative.py::create_section()'s JSON sidecar shape
    (narrative/sections/<slug>.json)."""

    schema_version: int = SCHEMA_VERSION
    seed_openalex_id: str
    slug: str
    title: str
    kind: SectionKind
    theme_slugs: list[str] = Field(default_factory=list)
    prose: str
    section_status: SectionStatus = "draft"
    created_at: str
    updated_at: str
    confirmed_at: str | None = None

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, v: str) -> str:
        return _validate_slug(v)


NARRATIVE_SECTION_VERSION = 1


class NarrativeSectionWrite(NarrativeSection):
    """Strict write variant of NarrativeSection.  Read paths (load_section,
    and the bulk _load_all_sections() plus the cross-module backlink glob
    scans in evidence.py/themes.py) use the permissive NarrativeSection
    (extra="allow"); write paths (create_section, confirm_section) use
    this subclass, which sets extra="forbid"."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def migrate_section(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate a raw narrative section dict forward to
    NARRATIVE_SECTION_VERSION.  Idempotent.  v0 (no key) -> v1: stamp
    schema_version -- no shape change."""
    result = dict(raw)
    if result.get("schema_version", 0) < 1:
        result["schema_version"] = NARRATIVE_SECTION_VERSION
    return result


class Override(WakeModel):
    """report.py::add_override()'s overrides.jsonl entry shape."""

    schema_version: int = SCHEMA_VERSION
    citing_id: str
    relationship: RelationshipLabel
    justification: str = ""
    confidence: float = 1.0
    human_reviewed: bool = True
    verification_status: Literal["verified"] = "verified"
    verification_source: VerificationSource
    overridden_at: str


OVERRIDE_VERSION = 1


class OverrideWrite(Override):
    """Strict write variant of Override -- see ThemeWrite/
    EvidenceDossierWrite for the read-permissive/write-strict rationale.
    Used only by add_override()'s append; remove_override()'s rewrite
    deliberately preserves every surviving line verbatim (including
    unparseable ones) and must not be routed through this."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def migrate_override(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate one raw overrides.jsonl record forward to OVERRIDE_VERSION.

    Unlike the single-document artifacts (dossiers/themes/narrative/
    classify sidecars), overrides.jsonl is an append-only log with no
    single document to rewrite in place -- load_overrides() calls this
    per-record, in memory, on every parsed line; on-disk lines are never
    rewritten by a read.  Idempotent.  v0 (no key) -> v1: stamp
    schema_version -- no shape change.
    """
    result = dict(raw)
    if result.get("schema_version", 0) < 1:
        result["schema_version"] = OVERRIDE_VERSION
    return result


class ArtifactReference(WakeModel):
    """The ``[ref:ID]`` marker family used in narrative prose (see
    narrative.py's ``_REF_RE``/``_parse_ref_markers``): a reference is
    either the seed paper itself or a specific citing work. Purely a
    structured stand-in for what's persisted today as a raw string ID
    inside a ``[ref:...]`` marker -- rendering (relative links, [Rn]
    renumbering) stays presentation logic, not part of this model.
    """

    kind: Literal["seed", "citing_work"]
    id: str

    @classmethod
    def parse(cls, raw_id: str) -> ArtifactReference:
        if raw_id == "SEED":
            return cls(kind="seed", id=raw_id)
        return cls(kind="citing_work", id=raw_id)
