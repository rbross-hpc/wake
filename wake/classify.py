# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""LLM-classify each citing work's relationship to the seed paper.

Relationship classes (ordered by default strength, strongest first --
also noting the nearest CiTO (Citation Typing Ontology) property, where
one exists, since this taxonomy was deliberately aligned toward CiTO's
naming in v0.4.21):
  applies-to-domain – applies the seed's method to a new domain/problem
                      (a special case of uses-method-from, kept distinct
                      because domain transfer is its own useful signal).
                      Nearest CiTO: cito:usesMethodIn.
  uses-method-from  – uses the seed's method, algorithm, or software tool,
                      whether applied as-is or incorporated as a
                      component/dependency of a new system. Nearest CiTO:
                      cito:usesMethodIn (exact).
  uses-data-from    – uses the seed's dataset/data. Nearest CiTO:
                      cito:usesDataFrom (exact).
  extends           – directly extends/modifies the seed's OWN method,
                      framework, or theory (contrast with uses-method-from,
                      which uses it unchanged). Nearest CiTO: cito:extends
                      (exact).
  benchmarks        – compares against the seed as a baseline/benchmark.
                      Nearest CiTO: cito:citesAsPotentialSolution (weak --
                      CiTO has no dedicated "baseline comparison"
                      property).
  related           – complementary work/infrastructure in the same
                      ecosystem, an affirmative "these are related"
                      judgment, without a direct usage/extension
                      dependency. Nearest CiTO: cito:citesAsRelated.
  cites             – the fallback: cites the seed, but no more specific
                      relationship is determinable from the text
                      (including unclear/indirect/merely contextual
                      mentions). Nearest CiTO: cito:cites (exact) -- CiTO's
                      own root "cites, unspecified" property.

This exact set of seven labels is fixed in code (CANONICAL_RELATIONSHIPS
below) because the LLM prompts in this module and in evidence.py spell
each one out as prose the model must copy verbatim -- the label set can't
be extended purely through config without also rewriting those prompts.
What IS configurable is how much each label counts for when ranking
citing works (see relationship_strength() below and
`classify.relationship_strength` in config.yaml) -- e.g. an analysis
where tooling adoption matters more than domain reach can weight
`uses-method-from` above `applies-to-domain` without re-running any
classification: edit config.yaml, then re-run `wake bake` (no LLM calls,
no re-classification -- ranking is always recomputed from the stored
relationship label, never from a persisted score).

A citing work's relationship to the seed is sometimes genuinely more than
one story -- e.g. a paper that uses the seed's tool as-is AND applies it
to a new domain is both "uses-method-from" and "applies-to-domain", and
picking only one loses signal. classify-3 (see _SYSTEM_CLASSIFY_3) asks
for a short, confidence-ordered list of facets ("relationships": [...])
instead of one label; classify-2 and classify-4 keep the original
single-label behavior. All three write the same sidecar shape either
way: a top-level "relationships" facets list plus legacy
"relationship"/"confidence"/"justification" scalars set from the top
(most-confident) facet, so every existing consumer (themes, narrative,
report metrics) keeps working unchanged regardless of which prompt
version produced the sidecar. Opting into classify-3 is a local config
edit (`classify.prompt_version: "classify-3"`), not a default --
switching prompt versions invalidates every existing sidecar's cache
(see classify_all's prompt_version check), so it's deliberately not
flipped by an upgrade alone.

classify-4 (the packaged default as of this pass, see _SYSTEM_CLASSIFY_4)
is classify-2's direct successor, not classify-3's: same single-label
schema, but the prompt is given the seed paper's own `wake describe`
contribution paragraph (grounded in the seed's own PDF text, not just its
abstract -- see describe.py) plus the citing work's `topics` -- so the
model knows what the seed actually contributes instead of
pattern-matching on its title alone. The seed description is REQUIRED
for classify-4 (classify_all fails fast, before any LLM calls, if the
seed has none) -- earlier revisions of classify-4 sent the seed's
abstract unconditionally plus the description as an optional extra line,
but the description is generated from the abstract plus a PDF excerpt
and therefore strictly dominates it as context, so sending both was
redundant and a missing description silently downgraded the whole run
with no signal to the operator. See PLAN.md's "classify-4
description-only + required" section for the investigation that
motivated this change.

Each classification is written atomically as a sidecar JSON file, so the
pipeline is safely resumable after Ctrl-C.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from . import backfill as backfill_mod
from . import config
from . import cost as cost_mod
from .citing import sort_works
from .gaps import apply_manual_abstracts, load_manual_abstracts
from .io import atomic_write_json, now_iso, read_json
from .llm.openai_client import chat_json
from .models import (
    CLASSIFICATION_VERSION,
    CLASSIFIED_FILE_VERSION,
    ClassificationResultWrite,
    ClassifiedFileWrite,
    migrate_classification_result,
    migrate_classified,
)
from .seed import work_dir
from .state import mark_stage_complete
from .vocabulary import CANONICAL_RELATIONSHIPS

_STAGE = "classify"

# Default strengths, used when config.yaml has no
# classify.relationship_strength override (or a local wake.config.yaml
# predates this feature and doesn't set one). Not ordered by
# CANONICAL_RELATIONSHIPS' strongest-first order above -- see the module
# docstring's `applies-to-domain` note: domain transfer is weighted
# highest by design here, not by strongest-first document order.
_DEFAULT_RELATIONSHIP_STRENGTH: dict[str, int] = {
    "applies-to-domain": 7,
    "uses-method-from": 6,
    "uses-data-from": 6,
    "extends": 5,
    "benchmarks": 3,
    "related": 2,
    "cites": 1,
}


def _closest_match(label: str, candidates: tuple[str, ...]) -> str | None:
    """Return the candidate label within edit distance 2 of *label*, or
    None -- a cheap typo hint for config validation error messages (e.g.
    'uses_method_from' -> suggest 'uses-method-from'). Not a general
    spellchecker; just enough to catch the common hyphen/underscore/
    dropped-letter slip."""
    best = None
    best_dist = 3
    for cand in candidates:
        dist = _edit_distance(label, cand)
        if dist < best_dist:
            best = cand
            best_dist = dist
    return best


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def _validate_relationship_strength(strength_map: dict[str, Any]) -> dict[str, int]:
    """Validate a `classify.relationship_strength` config mapping against
    CANONICAL_RELATIONSHIPS. Enforces (see BACKLOG.md/PLAN.md discussion):
      A. no unknown labels (the prompts can't emit a label config invents)
      B. no missing labels (every canonical label needs a strength to rank by)
      C. every strength is a positive number (zero/negative would silently
         hide or invert a whole relationship class in every ranking)
    Raises ValueError naming every problem at once, not just the first.
    """
    canonical = set(CANONICAL_RELATIONSHIPS)
    given = set(strength_map.keys())

    errors: list[str] = []

    unknown = given - canonical
    for label in sorted(unknown):
        hint = _closest_match(label, CANONICAL_RELATIONSHIPS)
        suggestion = f" (did you mean {hint!r}?)" if hint else ""
        errors.append(f"unknown relationship label {label!r} in classify.relationship_strength{suggestion}")

    missing = canonical - given
    if missing:
        errors.append(
            f"classify.relationship_strength is missing required label(s): {sorted(missing)}"
        )

    for label in sorted(given & canonical):
        value = strength_map[label]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            errors.append(
                f"classify.relationship_strength[{label!r}] = {value!r} must be a positive number"
            )

    if errors:
        raise ValueError(
            "Invalid classify.relationship_strength in config:\n  " + "\n  ".join(errors)
        )

    return {label: strength_map[label] for label in CANONICAL_RELATIONSHIPS}


def relationship_strength() -> dict[str, int]:
    """The active label -> strength mapping: `classify.relationship_strength`
    from config if present (validated against CANONICAL_RELATIONSHIPS),
    else the hardcoded default. This is the single source of truth
    report.relationship_score() reads -- editing config.yaml's
    classify.relationship_strength and re-running `wake bake` reranks the
    impact brief with no LLM calls and no re-classification, because
    ranking is always recomputed from the stored relationship label,
    never from a persisted score.

    Re-validates against config on every call rather than caching --
    validation is a handful of dict lookups over 7 known labels, cheap
    enough that a config.reload() (e.g. after `wake config init` or in
    tests) is always picked up immediately with no stale-cache risk."""
    cfg = config.classify_cfg().get("relationship_strength")
    if not cfg:
        return dict(_DEFAULT_RELATIONSHIP_STRENGTH)
    return _validate_relationship_strength(cfg)


# Fixed label set -- never config-driven, see module docstring. Kept as a
# plain module-level list for existing import sites
# (`from .classify import RELATIONSHIPS`).
RELATIONSHIPS = list(CANONICAL_RELATIONSHIPS)

# A citing work's relationship to the seed is sometimes genuinely more
# than one story (see MULTI-FACET note below) -- these bound how far that
# can go: at most this many facets are ever kept (LLM output is truncated
# to the top-MAX_FACETS by confidence if it returns more), and any facet
# below MIN_FACET_CONFIDENCE is dropped rather than kept as noise. Both
# are belt-and-suspenders backstops for what the classify-3/evidence-2
# prompts already ask for -- "one facet by default, two only when both
# are independently well-supported, three only in the exceptional case" --
# not something expected to bind often in practice.
MAX_FACETS = 3
MIN_FACET_CONFIDENCE = 0.5

_SYSTEM_CLASSIFY_2 = """\
You are a bibliometric analyst classifying how a citing paper uses a seed paper.

You MUST choose exactly one of these seven relationship class strings —
copy one verbatim into the "relationship" field, do not invent a new label:
- "extends": The citing paper directly extends or modifies the seed's OWN
  method, framework, or theory. Contrast with "uses-method-from": extends
  changes the seed's method itself, uses-method-from uses it unchanged.
- "uses-method-from": The citing paper uses the seed's method, algorithm,
  or software tool — either applying it as-is, or incorporating it as a
  component/dependency of a new system the citing paper builds. Either
  way, the seed's method is used unchanged, not modified.
- "uses-data-from": The citing paper uses the seed's dataset or data.
- "applies-to-domain": The citing paper applies the seed's method to a
  new domain or problem — a special case of "uses-method-from" where the
  key story is the domain transfer itself, not just the reuse.
- "benchmarks": The citing paper benchmarks against or compares performance with the seed.
- "related": The citing paper is complementary work or infrastructure in
  the same ecosystem (e.g. another library solving an adjacent problem in
  the same domain) — an affirmative "these are related" judgment, but
  without directly depending on, extending, or benchmarking the seed.
- "cites": The citing paper cites the seed but no more specific
  relationship can be determined from the text — the fallback for
  unclear, indirect, or merely contextual mentions, and for cases that
  don't fit any of the other six.

If none of the first six clearly apply, use "cites" — never invent an
eighth category or a variation on these names.

Respond with ONLY a single JSON object, no markdown fence, matching this schema:
{
  "relationship": "<one of the seven exact strings above>",
  "confidence": <float 0.0-1.0>,
  "justification": "<one sentence explaining the classification>"
}
If the abstract is missing, base your decision on title and venue; set confidence <= 0.5.\
"""

# classify-3: multi-facet successor to classify-2, above. A citing paper's
# relationship to the seed is sometimes genuinely more than one story --
# e.g. a paper that both uses the seed's tool as-is AND applies it to a
# new domain is telling two independent stories, and reducing that to one
# label loses signal (see the PnetCDF/flood-modeling case that motivated
# this: uses-method-from + applies-to-domain, both well-supported by
# distinct passages). This prompt asks for a short, confidence-ordered
# list of facets instead of a single label. MAX_FACETS/MIN_FACET_CONFIDENCE
# above enforce the same discipline in code as a backstop.
_SYSTEM_CLASSIFY_3 = """\
You are a bibliometric analyst classifying how a citing paper uses a seed paper.

Choose from these seven relationship class strings — copy verbatim into
the "label" field, do not invent a new one:
- "extends": The citing paper directly extends or modifies the seed's OWN
  method, framework, or theory. Contrast with "uses-method-from": extends
  changes the seed's method itself, uses-method-from uses it unchanged.
- "uses-method-from": The citing paper uses the seed's method, algorithm,
  or software tool — either applying it as-is, or incorporating it as a
  component/dependency of a new system the citing paper builds. Either
  way, the seed's method is used unchanged, not modified.
- "uses-data-from": The citing paper uses the seed's dataset or data.
- "applies-to-domain": The citing paper applies the seed's method to a
  new domain or problem — a special case of "uses-method-from" where the
  key story is the domain transfer itself, not just the reuse.
- "benchmarks": The citing paper benchmarks against or compares performance with the seed.
- "related": The citing paper is complementary work or infrastructure in
  the same ecosystem (e.g. another library solving an adjacent problem in
  the same domain) — an affirmative "these are related" judgment, but
  without directly depending on, extending, or benchmarking the seed.
- "cites": The citing paper cites the seed but no more specific
  relationship can be determined from the text — the fallback for
  unclear, indirect, or merely contextual mentions, and for cases that
  don't fit any of the other six.

Most citing papers have exactly ONE clear relationship to the seed. Some
genuinely have TWO — for example, a paper that both uses the seed's tool
as-is ("uses-method-from") AND applies it to a new domain
("applies-to-domain") is telling two independent stories. Very rarely
does a paper have THREE.

Return one facet by default. Return two only when both are independently
well-supported (each has its own justification and would be a defensible
standalone reading on its own — not the same story described two ways).
Return three only in the exceptional case where the paper genuinely does
three distinct things. Do not hedge: e.g. a paper that clearly "extends"
the seed should NOT also list "uses-method-from" just because extending
requires using the method first — that is one story, not two.

Every facet you return must have confidence >= 0.5. If a possible second
or third reading is weaker than that, leave it out.

Respond with ONLY a single JSON object, no markdown fence, matching this schema:
{
  "relationships": [
    {
      "label": "<one of the seven exact strings above>",
      "confidence": <float 0.5-1.0>,
      "justification": "<one sentence explaining this specific facet>"
    }
  ]
}
List the facets most-confident first. If the abstract is missing, base
your decision on title and venue; set confidence <= 0.5 for every facet
in that case (i.e., in practice, return exactly one low-confidence facet).\
"""

# classify-4: single-facet successor to classify-2 (NOT classify-3 --
# see PLAN.md's "Investigation findings": classify-3's multi-facet
# schema has never been the packaged default and this change
# deliberately doesn't flip that on as a side effect of fixing input
# starvation). classify-2 only ever sees the seed's title/year plus the
# citing work's title/year/venue/abstract -- it doesn't even know what
# the seed paper actually contributes. classify-4 gives the model the
# seed's `wake describe` contribution paragraph (see describe.py --
# grounded in the seed's own PDF text, not just its abstract) plus the
# citing work's `topics`. The seed description is REQUIRED: classify_all
# fails fast, before any LLM calls, if the seed has none (see PLAN.md's
# "classify-4 description-only + required" -- an earlier revision of
# this prompt sent the seed abstract unconditionally plus the
# description as an optional extra, but the description is generated
# from the abstract plus a PDF excerpt and so strictly dominates it;
# silently degrading to abstract-only when the description was missing
# masked a real seed-enrichment bug rather than surfacing it).
# Deliberately excludes author_overlap (kept a post-hoc tag, never a
# classification input -- see PLAN.md). Same seven-label taxonomy and
# JSON response shape as classify-2; only the system/user prompts
# differ.
_SYSTEM_CLASSIFY_4 = """\
You are a bibliometric analyst classifying how a citing paper uses a seed paper.

You will be given a description of the seed paper's contribution
(grounded in the paper's own full text) so you understand what the seed
paper actually is, not just its title -- use that context to distinguish
"uses-method-from" (the citing paper uses the seed's method/tool
unchanged), "related" (same ecosystem, no direct dependency), and "cites"
(no specific relationship determinable) with more precision than title
alone allows.

You MUST choose exactly one of these seven relationship class strings —
copy one verbatim into the "relationship" field, do not invent a new label:
- "extends": The citing paper directly extends or modifies the seed's OWN
  method, framework, or theory. Contrast with "uses-method-from": extends
  changes the seed's method itself, uses-method-from uses it unchanged.
- "uses-method-from": The citing paper uses the seed's method, algorithm,
  or software tool — either applying it as-is, or incorporating it as a
  component/dependency of a new system the citing paper builds. Either
  way, the seed's method is used unchanged, not modified.
- "uses-data-from": The citing paper uses the seed's dataset or data.
- "applies-to-domain": The citing paper applies the seed's method to a
  new domain or problem — a special case of "uses-method-from" where the
  key story is the domain transfer itself, not just the reuse.
- "benchmarks": The citing paper benchmarks against or compares performance with the seed.
- "related": The citing paper is complementary work or infrastructure in
  the same ecosystem (e.g. another library solving an adjacent problem in
  the same domain) — an affirmative "these are related" judgment, but
  without directly depending on, extending, or benchmarking the seed.
- "cites": The citing paper cites the seed but no more specific
  relationship can be determined from the text — the fallback for
  unclear, indirect, or merely contextual mentions, and for cases that
  don't fit any of the other six.

If none of the first six clearly apply, use "cites" — never invent an
eighth category or a variation on these names.

Respond with ONLY a single JSON object, no markdown fence, matching this schema:
{
  "relationship": "<one of the seven exact strings above>",
  "confidence": <float 0.0-1.0>,
  "justification": "<one sentence explaining the classification>"
}
If the citing work's abstract is missing, base your decision on its title,
venue, and topics; set confidence <= 0.5.\
"""

_SYSTEM_BY_VERSION: dict[str, str] = {
    "classify-2": _SYSTEM_CLASSIFY_2,
    "classify-3": _SYSTEM_CLASSIFY_3,
    "classify-4": _SYSTEM_CLASSIFY_4,
}


def _system_prompt(prompt_version: str) -> str:
    """The literal system prompt for *prompt_version* -- see
    _SYSTEM_BY_VERSION. Falls back to the classify-2 (legacy, single-label)
    prompt for an unrecognized version string, matching classify_one's
    handling of an unrecognized *label* (never crash on unexpected
    config; degrade to the well-understood default)."""
    return _SYSTEM_BY_VERSION.get(prompt_version, _SYSTEM_CLASSIFY_2)


def _parse_relationships_response(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize an LLM response from either _SYSTEM_CLASSIFY_2 (single
    "relationship"/"confidence"/"justification" scalars) or
    _SYSTEM_CLASSIFY_3 ("relationships" list) into a canonical facets
    list: valid labels only, confidence >= MIN_FACET_CONFIDENCE, sorted
    confidence-descending, capped at MAX_FACETS. Always returns at least
    one facet -- falls back to a single `cites` facet if
    parsing/filtering leaves nothing usable (garbled response, or every
    facet failed validation)."""
    raw_facets = result.get("relationships")
    if not isinstance(raw_facets, list) or not raw_facets:
        raw_facets = [{
            "label": result.get("relationship", "cites"),
            "confidence": result.get("confidence", 0.5),
            "justification": result.get("justification", ""),
        }]

    facets: list[dict[str, Any]] = []
    for f in raw_facets:
        if not isinstance(f, dict):
            continue
        label = f.get("label")
        if label not in CANONICAL_RELATIONSHIPS:
            continue
        try:
            confidence = float(f.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        if confidence < MIN_FACET_CONFIDENCE:
            continue
        facets.append({
            "label": label,
            "confidence": confidence,
            "justification": (f.get("justification") or "").strip(),
        })

    facets.sort(key=lambda f: f["confidence"], reverse=True)
    facets = facets[:MAX_FACETS]

    if not facets:
        facets = [{"label": "cites", "confidence": 0.5, "justification": ""}]

    return facets


def _normalize_relationships(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Read-compat: return *payload*'s "relationships" facets list if
    present, else synthesize a one-element list from its legacy
    "relationship"/"confidence"/"justification" scalars. Used by every
    reader (classify, evidence, report, evidence_wiki) that needs to
    treat an old, pre-multi-facet sidecar the same as a new one.

    This is a render/build-time view-deriver, not a `migrate_*()`
    schema-migration step -- it runs on a sub-block that may not even
    be persisted yet (a freshly-produced classify result), and folding
    it into `migrate_classification_result` would force a `relationships`
    key onto entries that structurally don't have one (see
    `ClassifiedFile`'s docstring). See
    `docs/design/normalize-audit.md` for the full determination."""
    facets = payload.get("relationships")
    if isinstance(facets, list) and facets:
        return facets
    return [{
        "label": payload.get("relationship", "cites"),
        "confidence": payload.get("confidence", 0.5),
        "justification": payload.get("justification", ""),
    }]


_USER_TEMPLATE = """\
Seed paper: "{seed_title}" ({seed_year})

Citing paper:
  Title: {title}
  Year: {year}
  Venue: {venue}
  Abstract: {abstract}

Classify the relationship.\
"""

# classify-4's user template, paired with _SYSTEM_CLASSIFY_4 above. Uses
# the seed's `wake describe` contribution paragraph (REQUIRED -- see
# classify_all's fail-fast check; there is deliberately no "(not
# available)" fallback here, unlike the citing work's own abstract
# below) plus the citing work's topics -- see PLAN.md's "classify-4
# description-only + required" for the rationale. No seed-abstract line:
# the description is generated from the abstract plus a PDF excerpt (see
# describe.py) and therefore strictly dominates it as seed-side context,
# so sending both was redundant.
_USER_TEMPLATE_4 = """\
Seed paper: "{seed_title}" ({seed_year})
Seed contribution: {seed_description}

Citing paper:
  Title: {title}
  Year: {year}
  Venue: {venue}
  Topics: {topics}
  Abstract: {abstract}

Classify the relationship.\
"""

# Defensive cap on the seed description injected into classify-4's user
# message -- describe.py's contribution paragraph is normally a few
# sentences, but bounding it here prevents an unusually long or malformed
# description from blowing up per-call token cost.
_SEED_DESCRIPTION_MAX_CHARS = 1500


def _build_classify4_user_msg(
    seed_work: dict[str, Any], citing_work: dict[str, Any]
) -> str:
    """Build classify-4's user message. Callers MUST ensure
    seed_work has a non-empty "description" before calling this --
    classify_all's own fail-fast check (raised near the top of that
    function, before any LLM calls) is the actual enforcement point;
    the assertion here is a belt-and-suspenders backstop, not the
    primary guard."""
    seed_description = (seed_work.get("description") or "").strip()
    assert seed_description, (
        "classify-4 requires a seed description; classify_all should have "
        "failed fast before calling _build_classify4_user_msg with none"
    )
    topics = ", ".join(citing_work.get("topics") or []) or "(none)"
    return _USER_TEMPLATE_4.format(
        seed_title=seed_work.get("title") or "Unknown",
        seed_year=seed_work.get("year") or "Unknown",
        seed_description=seed_description[:_SEED_DESCRIPTION_MAX_CHARS],
        title=citing_work.get("title") or "Unknown",
        year=citing_work.get("year") or "Unknown",
        venue=citing_work.get("venue") or "Unknown",
        topics=topics,
        abstract=citing_work.get("abstract") or "(not available)",
    )


def _prompt_version() -> str:
    return config.classify_cfg().get("prompt_version", "classify-2")


def _model() -> str:
    return config.models().get("classify", "Claude Sonnet 4.6")


def _sidecar_dir(openalex_id: str, base: Path | None = None) -> Path:
    return work_dir(openalex_id, base) / "classify"


def _legacy_sidecar_dir(openalex_id: str, base: Path | None = None) -> Path:
    """Pre-rename dotfile location. Kept only for one release's worth of
    read-compat with packets built before the rename (a working directory
    the human is explicitly expected to inspect shouldn't hide its
    per-work classification sidecars behind a dotfile convention meant
    for user-home/config directories); see
    `_migrate_legacy_sidecar_dir_if_needed`."""
    return work_dir(openalex_id, base) / ".classify"


def _migrate_legacy_sidecar_dir_if_needed(seed_id: str, base: Path | None = None) -> None:
    """Rename `.classify/` -> `classify/` in place the first time this
    seed's sidecars are written to after the rename. No-op if the
    new-named directory already exists (never overwrites/merges) or if
    there's nothing to migrate."""
    new_dir = _sidecar_dir(seed_id, base)
    old_dir = _legacy_sidecar_dir(seed_id, base)
    if old_dir.exists() and not new_dir.exists():
        old_dir.rename(new_dir)


def _sidecar_path(seed_id: str, citing_id: str, base: Path | None = None) -> Path:
    return _sidecar_dir(seed_id, base) / f"{citing_id}.json"


def _legacy_sidecar_path(seed_id: str, citing_id: str, base: Path | None = None) -> Path:
    return _legacy_sidecar_dir(seed_id, base) / f"{citing_id}.json"


def _load_sidecar(seed_id: str, citing_id: str, base: Path | None = None) -> dict | None:
    """Reads the current `classify/` location; falls back to the
    pre-rename `.classify/` dotfile if the new directory doesn't exist
    yet (a packet built before the rename that hasn't had a fresh
    `wake classify` call to trigger migration). Read-only compat --
    migration happens in `_write_sidecar`, the write path, not here."""
    p = _sidecar_path(seed_id, citing_id, base)
    if not p.exists():
        p = _legacy_sidecar_path(seed_id, citing_id, base)
        if not p.exists():
            return None
    try:
        return migrate_classification_result(read_json(p))
    except (json.JSONDecodeError, OSError):
        return None


def _write_sidecar(seed_id: str, citing_id: str, result: dict, base: Path | None = None) -> None:
    result = {**result, "schema_version": CLASSIFICATION_VERSION}
    validated = ClassificationResultWrite.validate_or_raise(
        result, context=f"classification sidecar {citing_id!r}"
    )
    result = validated.to_json_dict()
    _migrate_legacy_sidecar_dir_if_needed(seed_id, base)
    p = _sidecar_path(seed_id, citing_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, result)


def classify_one(
    seed_work: dict[str, Any],
    citing_work: dict[str, Any],
    *,
    seed_id: str | None = None,
    base: Path | None = None,
    record_cost: bool = True,
) -> dict[str, Any]:
    """Classify a single citing work's relationship to the seed.

    Returns both the new multi-facet "relationships" list (see
    _parse_relationships_response) and, for read-compat with every
    existing consumer (themes, narrative, report metrics, CLI display),
    legacy "relationship"/"confidence"/"justification" scalars populated
    from the top (most-confident) facet.
    """
    prompt_version = _prompt_version()
    if prompt_version == "classify-4":
        user_msg = _build_classify4_user_msg(seed_work, citing_work)
    else:
        user_msg = _USER_TEMPLATE.format(
            seed_title=seed_work.get("title") or "Unknown",
            seed_year=seed_work.get("year") or "Unknown",
            title=citing_work.get("title") or "Unknown",
            year=citing_work.get("year") or "Unknown",
            venue=citing_work.get("venue") or "Unknown",
            abstract=citing_work.get("abstract") or "(not available)",
        )

    cost_sink = None
    if record_cost and seed_id is not None:
        def cost_sink(model: str, system: str, user: str, response_text: str) -> None:
            cost_mod.record_call(
                seed_id, stage="classify", model=model,
                system=system, user=user, response_text=response_text, base=base,
            )

    system_prompt = _system_prompt(prompt_version)
    result = chat_json(system_prompt, user_msg, model_role="classify", cost_sink=cost_sink)

    facets = _parse_relationships_response(result)
    top = facets[0]

    from .author_overlap import compute_overlap
    overlap = compute_overlap(seed_work, citing_work)

    return {
        "relationship": top["label"],
        "confidence": top["confidence"],
        "justification": top["justification"],
        "relationships": facets,
        "has_abstract": bool(citing_work.get("abstract")),
        # No "strength" field here, deliberately: strength is a derived
        # score (see relationship_strength()/report.relationship_score()),
        # recomputed at ranking time from the relationship label and the
        # current config -- not persisted, so editing
        # classify.relationship_strength in wake.config.yaml and
        # re-running `wake bake` reranks the impact brief without
        # re-classifying anything.
        # Always "provisional": classify_one only ever sees title/abstract/
        # venue, never the citing paper's actual text. This is a weak,
        # unverified guess — not a finding. It can only be promoted to
        # "verified" via wake evidence (full-text reading) + a human
        # sign-off through wake override. See report.add_override() and
        # BACKLOG.md's provisional -> proposed -> verified lifecycle.
        "verification_status": "provisional",
        # Orthogonal to relationship (BACKLOG Theme E): is this the seed's
        # own team publishing a follow-on, or an independent third party?
        # Not a new relationship label -- "extends" + author_overlap=True
        # is a different story than "extends" + author_overlap=False, but
        # both are still "extends".
        **overlap,
    }


def _title_only_shortcircuit_enabled() -> bool:
    return bool(config.classify_cfg().get("title_only_shortcircuit", True))


def _title_only_relationship() -> str:
    return config.classify_cfg().get("title_only_relationship", "cites")


def _title_only_shortcircuit_result(
    seed_work: dict[str, Any], citing_work: dict[str, Any]
) -> dict[str, Any]:
    """Deterministic classification for a citing work that still has no
    abstract after backfill -- no LLM call. See PLAN.md's "title-only
    short-circuit": on the PVFS packet, 89% of title/venue-only works
    were LLM-classified as "cites" anyway, mostly reproducing the
    prompt's own fallback instruction ("if abstract missing, base
    decision on title and venue; set confidence <= 0.5") rather than
    adding signal. Tagged low_signal=True so report.py can distinguish
    this from a work the LLM actually judged to be "cites".
    """
    label = _title_only_relationship()

    from .author_overlap import compute_overlap
    overlap = compute_overlap(seed_work, citing_work)

    justification = "No abstract available after backfill; title/venue-only — not classified by LLM."
    return {
        "relationship": label,
        "confidence": 0.0,
        "justification": justification,
        "relationships": [{"label": label, "confidence": 0.0, "justification": justification}],
        "has_abstract": False,
        "verification_status": "provisional",
        "low_signal": True,
        **overlap,
    }


def select_for_classification(
    citing_works: list[dict[str, Any]],
    *,
    ids: list[str] | None = None,
    limit: int | None = None,
    sort: str = "cited-by",
) -> list[dict[str, Any]]:
    """Select which citing works to (re)classify, in the given order.

    - ids: restrict to exactly these OpenAlex IDs (order follows *sort*
      applied to the matching subset).
    - limit: cap the number of works after sorting.
    - sort: 'cited-by' (default, most-influential-first), 'recent', 'oldest',
      or 'random'.
    """
    pool = citing_works
    if ids:
        id_set = set(ids)
        pool = [w for w in pool if w.get("openalex_id") in id_set]
    pool = sort_works(pool, sort)
    if limit is not None:
        pool = pool[:limit]
    return pool


def classify_all(
    seed_work: dict[str, Any],
    citing_works: list[dict[str, Any]],
    *,
    base: Path | None = None,
    force: bool = False,
    verbose: bool = True,
    inter_call_delay: float = 0.5,
    ids: list[str] | None = None,
    limit: int | None = None,
    sort: str = "cited-by",
    dry_run: bool = False,
    record_cost: bool = True,
) -> list[dict[str, Any]]:
    """Classify a selection of citing works; write atomic sidecars.

    Resumable: already-classified works are loaded from sidecars.
    Returns the full input list of citing works, with classification fields
    merged in wherever available (unselected/unclassified works are returned
    unmodified — callers should check for the 'relationship' key).

    If dry_run=True, no LLM calls are made; the function reports what would
    happen (new vs. already-cached) without writing anything.

    Raises ValueError immediately (before any LLM calls, any cache
    lookups, or any backfill attempts) if the active prompt_version is
    "classify-4" and *seed_work* has no description -- see PLAN.md's
    "classify-4 description-only + required". One upfront failure
    instead of every one of potentially hundreds of citing works failing
    identically.
    """
    seed_id = seed_work["openalex_id"]
    pv = _prompt_version()
    model = _model()

    if pv == "classify-4" and not (seed_work.get("description") or "").strip():
        raise ValueError(
            "classify-4 requires a seed description. Run "
            f"'wake describe {seed_id}' first, then re-run classify."
        )

    manual_abstracts = load_manual_abstracts(seed_id, base)
    if manual_abstracts:
        citing_works = apply_manual_abstracts(citing_works, manual_abstracts)

    selected = select_for_classification(citing_works, ids=ids, limit=limit, sort=sort)

    # Seed by_id with any *previously* classified data for every citing work
    # (not just the current selection) so a scoped run (--ids/--limit) never
    # regresses classifications done in an earlier run.
    by_id: dict[str, dict[str, Any]] = {}
    for w in citing_works:
        wid = w.get("openalex_id")
        if not wid:
            continue
        prior = _load_sidecar(seed_id, wid, base)
        if prior and prior.get("prompt_version") == pv and prior.get("model") == model:
            by_id[wid] = {**w, **prior}
        else:
            by_id[wid] = dict(w)

    done = 0
    skipped = 0
    errors = 0
    to_call = 0
    title_only = 0
    total = len(selected)
    shortcircuit_enabled = _title_only_shortcircuit_enabled()

    for i, cw in enumerate(selected):
        citing_id = cw.get("openalex_id", f"unknown-{i}")

        cached = None if force else _load_sidecar(seed_id, citing_id, base)
        if cached and cached.get("prompt_version") == pv and cached.get("model") == model:
            by_id[citing_id] = {**cw, **cached}
            skipped += 1
            continue

        to_call += 1
        if dry_run:
            continue

        cw = backfill_mod.backfill_one(cw, verbose=verbose)

        if shortcircuit_enabled and not cw.get("abstract"):
            result = _title_only_shortcircuit_result(seed_work, cw)
            sidecar = {
                **result,
                "prompt_version": pv,
                "model": model,
                "classified_at": now_iso(),
            }
            _write_sidecar(seed_id, citing_id, sidecar, base)
            by_id[citing_id] = {**cw, **sidecar}
            done += 1
            title_only += 1

            if verbose and (done + skipped) % 50 == 0:
                print(
                    f"[wake]   classified {done + skipped:,}/{total:,} "
                    f"(new={done}, cached={skipped}, errors={errors})",
                    file=sys.stderr,
                )

            if inter_call_delay > 0:
                time.sleep(inter_call_delay)
            continue

        try:
            result = classify_one(seed_work, cw, seed_id=seed_id, base=base, record_cost=record_cost)
        except Exception as exc:
            if verbose:
                print(f"[wake]   WARN: classify failed for {citing_id}: {exc}", file=sys.stderr)
            errors += 1
            # Do not cache a fake classification for a failed call: leaving
            # no sidecar (and no 'relationship' key) means this work is
            # correctly treated as unclassified — excluded from
            # relationship-based metrics/coverage, and retried on the next
            # run rather than silently and permanently mislabeled.
            by_id[citing_id] = {
                **cw,
                "error": str(exc),
                "error_at": now_iso(),
            }
            continue

        sidecar = {
            **result,
            "prompt_version": pv,
            "model": model,
            "classified_at": now_iso(),
        }
        _write_sidecar(seed_id, citing_id, sidecar, base)
        by_id[citing_id] = {**cw, **sidecar}
        done += 1

        if verbose and (done + skipped) % 50 == 0:
            print(
                f"[wake]   classified {done + skipped:,}/{total:,} "
                f"(new={done}, cached={skipped}, errors={errors})",
                file=sys.stderr,
            )

        if inter_call_delay > 0:
            time.sleep(inter_call_delay)

    if verbose:
        if dry_run:
            print(
                f"[wake] Dry run: {to_call:,} would be classified, "
                f"{skipped:,} already cached (of {total:,} selected).",
                file=sys.stderr,
            )
        else:
            title_only_note = f", {title_only} title-only short-circuited" if title_only else ""
            print(
                f"[wake] Classification done: {done + skipped:,} total "
                f"({done} new, {skipped} cached, {errors} errors{title_only_note})",
                file=sys.stderr,
            )

    # Preserve original ordering of citing_works.
    return [by_id[wid] if (wid := w.get("openalex_id")) in by_id else w for w in citing_works]


def save_classified(
    seed_id: str,
    classified: list[dict[str, Any]],
    base: Path | None = None,
) -> Path:
    """Write classified.json and mark the stage complete."""
    wd = work_dir(seed_id, base)
    path = wd / "classified.json"
    stamped_works = [
        {**w, "schema_version": CLASSIFICATION_VERSION} if "relationship" in w else w
        for w in classified
    ]
    payload = {
        "schema_version": CLASSIFIED_FILE_VERSION,
        "seed_openalex_id": seed_id,
        "classified_at": now_iso(),
        "count": len(classified),
        "works": stamped_works,
    }
    validated = ClassifiedFileWrite.validate_or_raise(payload, context=f"classified.json for {seed_id!r}")
    payload = validated.to_json_dict()
    atomic_write_json(path, payload)
    mark_stage_complete(
        wd, _STAGE,
        seed_id=seed_id,
        prompt_version=_prompt_version(),
        model=_model(),
        extra={"count": len(classified)},
    )
    return path


def load_classified(seed_id: str, base: Path | None = None) -> list[dict] | None:
    p = work_dir(seed_id, base) / "classified.json"
    if not p.exists():
        return None
    migrated = migrate_classified(read_json(p))
    return migrated["works"]
