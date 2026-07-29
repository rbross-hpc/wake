# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""LLM-classify each citing work's relationship to the seed paper.

Relationship classes (ordered by strength, strongest first):
  extends              – directly extends the method/framework of the seed
  builds-on            – builds a new system/algorithm on top of the seed
  uses-as-tool         – uses the seed's software/tool/dataset as-is
  benchmarks           – compares against the seed as a baseline/benchmark
  applies-to-domain    – applies the seed's approach to a new domain/problem
  related-infrastructure – complementary tooling in the same ecosystem/stack
                           (e.g. another I/O library operating alongside the
                           seed), without a direct usage/extension dependency
  background-mention   – cites as background/related work without direct use

This exact set of seven labels is fixed in code (CANONICAL_RELATIONSHIPS
below) because the LLM prompts in this module and in evidence.py spell
each one out as prose the model must copy verbatim -- the label set can't
be extended purely through config without also rewriting those prompts.
What IS configurable is how much each label counts for when ranking
citing works (see relationship_strength() below and
`classify.relationship_strength` in config.yaml) -- e.g. an analysis
where domain reach matters more than tooling adoption can weight
`applies-to-domain` above `uses-as-tool` without re-running any
classification: edit config.yaml, then re-run `wake bake` (no LLM calls,
no re-classification -- ranking is always recomputed from the stored
relationship label, never from a persisted score).

A citing work's relationship to the seed is sometimes genuinely more than
one story -- e.g. a paper that uses the seed's tool as-is AND applies it
to a new domain is both "uses-as-tool" and "applies-to-domain", and
picking only one loses signal. classify-3 (see _SYSTEM_CLASSIFY_3) asks
for a short, confidence-ordered list of facets ("relationships": [...])
instead of one label; classify-2 (the default, see `prompt_version` in
config.yaml) keeps the original single-label behavior. Both write the
same sidecar shape either way: a top-level "relationships" facets list
plus legacy "relationship"/"confidence"/"justification" scalars set from
the top (most-confident) facet, so every existing consumer (themes,
narrative, report metrics) keeps working unchanged regardless of which
prompt version produced the sidecar. Opting into classify-3 is a local
config edit (`classify.prompt_version: "classify-3"`), not a default --
switching prompt versions invalidates every existing sidecar's cache
(see classify_all's prompt_version check), so it's deliberately not
flipped by an upgrade alone.

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
from . import config, cost as cost_mod
from .citing import sort_works
from .errors import RateLimited
from .gaps import apply_manual_abstracts, load_manual_abstracts
from .io import atomic_write_json, now_iso, read_json
from .llm.openai_client import chat_json
from .seed import work_dir
from .state import is_stage_current, mark_stage_complete

_STAGE = "classify"

# The fixed, canonical set of relationship labels -- see module docstring
# for why this list itself is not configurable (only the strengths are).
CANONICAL_RELATIONSHIPS = (
    "extends",
    "builds-on",
    "uses-as-tool",
    "benchmarks",
    "applies-to-domain",
    "related-infrastructure",
    "background-mention",
)

# Default strengths, used when config.yaml has no
# classify.relationship_strength override (or a local wake.config.yaml
# predates this feature and doesn't set one). Ordered strongest-first,
# matching CANONICAL_RELATIONSHIPS.
_DEFAULT_RELATIONSHIP_STRENGTH: dict[str, int] = {
    "extends": 7,
    "builds-on": 6,
    "uses-as-tool": 5,
    "benchmarks": 4,
    "applies-to-domain": 3,
    "related-infrastructure": 2,
    "background-mention": 1,
}


def _closest_match(label: str, candidates: tuple[str, ...]) -> str | None:
    """Return the candidate label within edit distance 2 of *label*, or
    None -- a cheap typo hint for config validation error messages (e.g.
    'uses_as_tool' -> suggest 'uses-as-tool'). Not a general spellchecker;
    just enough to catch the common hyphen/underscore/dropped-letter slip."""
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
- "extends": The citing paper directly extends the method, framework, or theory of the seed.
- "builds-on": The citing paper builds a new system, algorithm, or tool that depends on the seed.
- "uses-as-tool": The citing paper uses the seed's software, tool, or dataset as-is without modification.
- "benchmarks": The citing paper benchmarks against or compares performance with the seed.
- "applies-to-domain": The citing paper applies the seed's approach to a new domain or problem.
- "related-infrastructure": The citing paper is complementary tooling in the same
  technical ecosystem or stack (e.g. another library solving an adjacent problem
  in the same domain) but does not directly depend on, extend, or benchmark the
  seed — it operates alongside it rather than using it.
- "background-mention": The citing paper cites the seed only as background or
  related work, with no specific technical relationship (including cases where
  the relationship is unclear, indirect, or merely contextual).

If none of the first six clearly apply, use "background-mention" — never
invent an eighth category or a variation on these names.

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
# this: uses-as-tool + applies-to-domain, both well-supported by distinct
# passages). This prompt asks for a short, confidence-ordered list of
# facets instead of a single label. MAX_FACETS/MIN_FACET_CONFIDENCE above
# enforce the same discipline in code as a backstop.
_SYSTEM_CLASSIFY_3 = """\
You are a bibliometric analyst classifying how a citing paper uses a seed paper.

Choose from these seven relationship class strings — copy verbatim into
the "label" field, do not invent a new one:
- "extends": The citing paper directly extends the method, framework, or theory of the seed.
- "builds-on": The citing paper builds a new system, algorithm, or tool that depends on the seed.
- "uses-as-tool": The citing paper uses the seed's software, tool, or dataset as-is without modification.
- "benchmarks": The citing paper benchmarks against or compares performance with the seed.
- "applies-to-domain": The citing paper applies the seed's approach to a new domain or problem.
- "related-infrastructure": The citing paper is complementary tooling in the same
  technical ecosystem or stack (e.g. another library solving an adjacent problem
  in the same domain) but does not directly depend on, extend, or benchmark the
  seed — it operates alongside it rather than using it.
- "background-mention": The citing paper cites the seed only as background or
  related work, with no specific technical relationship (including cases where
  the relationship is unclear, indirect, or merely contextual).

Most citing papers have exactly ONE clear relationship to the seed. Some
genuinely have TWO — for example, a paper that both uses the seed's tool
as-is ("uses-as-tool") AND applies it to a new domain ("applies-to-domain")
is telling two independent stories. Very rarely does a paper have THREE.

Return one facet by default. Return two only when both are independently
well-supported (each has its own justification and would be a defensible
standalone reading on its own — not the same story described two ways).
Return three only in the exceptional case where the paper genuinely does
three distinct things. Do not hedge: e.g. a paper that clearly "extends"
the seed should NOT also list "builds-on" just because extending could be
described as a kind of building-on -- that is one story, not two.

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

_SYSTEM_BY_VERSION: dict[str, str] = {
    "classify-2": _SYSTEM_CLASSIFY_2,
    "classify-3": _SYSTEM_CLASSIFY_3,
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
    one facet -- falls back to a single background-mention facet if
    parsing/filtering leaves nothing usable (garbled response, or every
    facet failed validation)."""
    raw_facets = result.get("relationships")
    if not isinstance(raw_facets, list) or not raw_facets:
        raw_facets = [{
            "label": result.get("relationship", "background-mention"),
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
        facets = [{"label": "background-mention", "confidence": 0.5, "justification": ""}]

    return facets


def _normalize_relationships(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Read-compat: return *payload*'s "relationships" facets list if
    present, else synthesize a one-element list from its legacy
    "relationship"/"confidence"/"justification" scalars. Used by every
    reader (classify, evidence, report, evidence_wiki) that needs to
    treat an old, pre-multi-facet sidecar the same as a new one."""
    facets = payload.get("relationships")
    if isinstance(facets, list) and facets:
        return facets
    return [{
        "label": payload.get("relationship", "background-mention"),
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
        return read_json(p)
    except (json.JSONDecodeError, OSError):
        return None


def _write_sidecar(seed_id: str, citing_id: str, result: dict, base: Path | None = None) -> None:
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

    system_prompt = _system_prompt(_prompt_version())
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
    """
    seed_id = seed_work["openalex_id"]
    pv = _prompt_version()
    model = _model()

    manual_abstracts = load_manual_abstracts(seed_id, base)
    if manual_abstracts:
        citing_works = apply_manual_abstracts(citing_works, manual_abstracts)

    selected = select_for_classification(citing_works, ids=ids, limit=limit, sort=sort)
    selected_ids = {w.get("openalex_id") for w in selected}

    # Seed by_id with any *previously* classified data for every citing work
    # (not just the current selection) so a scoped run (--ids/--limit) never
    # regresses classifications done in an earlier run.
    by_id: dict[str, dict[str, Any]] = {}
    for w in citing_works:
        wid = w.get("openalex_id")
        prior = _load_sidecar(seed_id, wid, base) if wid else None
        if prior and prior.get("prompt_version") == pv and prior.get("model") == model:
            by_id[wid] = {**w, **prior}
        else:
            by_id[wid] = dict(w)

    done = 0
    skipped = 0
    errors = 0
    to_call = 0
    total = len(selected)

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
            print(
                f"[wake] Classification done: {done + skipped:,} total "
                f"({done} new, {skipped} cached, {errors} errors)",
                file=sys.stderr,
            )

    # Preserve original ordering of citing_works.
    return [by_id.get(w.get("openalex_id"), w) for w in citing_works]


def save_classified(
    seed_id: str,
    classified: list[dict[str, Any]],
    base: Path | None = None,
) -> Path:
    """Write classified.json and mark the stage complete."""
    wd = work_dir(seed_id, base)
    path = wd / "classified.json"
    payload = {
        "seed_openalex_id": seed_id,
        "classified_at": now_iso(),
        "count": len(classified),
        "works": classified,
    }
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
    data = read_json(p)
    return data.get("works") if isinstance(data, dict) else data
