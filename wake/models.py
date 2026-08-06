# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Explicit domain models for wake's core artifacts.

This module is the first step of the "Structural Hardening" effort (see
PLAN.md, "Phase 3 -- Structural Hardening" and BACKLOG.md Theme L): wake's
domain data has always been passed around as ``dict[str, Any]``, validated
ad hoc at each read site, with legacy/multi-facet shape differences
reconciled by scattered ``_normalize_*`` functions across classify.py,
evidence.py, themes.py, narrative.py, report.py, and evidence_wiki.py.

These Pydantic models exist to give that data a name and a schema without
changing wake's on-disk format: every model's ``.to_json_dict()`` produces
(and every model's ``model_validate()`` accepts) the *exact* dict shape
already read/written by the modules above, verified against real fixtures
in tests/test_models.py. Nothing in this module talks to the filesystem or
to an LLM -- it is a pure, dependency-free (aside from pydantic) schema
layer that other modules can adopt incrementally.

``SCHEMA_VERSION`` is a new field this module introduces on every model:
none of wake's existing persisted JSON carries an explicit schema version
today (see the assessment that prompted this effort) -- versioning has
been entirely implicit, via each LLM stage's own ``prompt_version``/
``model`` pair plus ``.state.json``'s ``tool_version``. Every model here
defaults ``schema_version`` to 1 and accepts a missing key on read (an
old, pre-model artifact silently reads as schema_version 1) so adopting
this layer is non-breaking for every existing wake-out/ packet.
"""
from __future__ import annotations

import re
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SCHEMA_VERSION = 1

# The fixed, canonical set of relationship labels. Duplicated from
# classify.py (rather than imported) to keep this module import-free of
# the rest of wake -- classify.py/evidence.py/themes.py/narrative.py will
# import *from* models.py, not the reverse. classify.py's own
# CANONICAL_RELATIONSHIPS remains the source of truth for prompt text and
# is asserted identical to this tuple in tests/test_models.py.
CANONICAL_RELATIONSHIPS = (
    "extends",
    "builds-on",
    "uses-as-tool",
    "benchmarks",
    "applies-to-domain",
    "related-infrastructure",
    "background-mention",
)

RelationshipLabel = Literal[
    "extends",
    "builds-on",
    "uses-as-tool",
    "benchmarks",
    "applies-to-domain",
    "related-infrastructure",
    "background-mention",
]

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
