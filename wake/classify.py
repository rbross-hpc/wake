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
from .io import atomic_write_json, now_iso, read_json
from .llm.openai_client import chat_json
from .seed import work_dir
from .state import is_stage_current, mark_stage_complete

_STAGE = "classify"

RELATIONSHIPS = [
    "extends",
    "builds-on",
    "uses-as-tool",
    "benchmarks",
    "applies-to-domain",
    "related-infrastructure",
    "background-mention",
]

RELATIONSHIP_STRENGTH: dict[str, int] = {
    "extends": 7,
    "builds-on": 6,
    "uses-as-tool": 5,
    "benchmarks": 4,
    "applies-to-domain": 3,
    "related-infrastructure": 2,
    "background-mention": 1,
}

_SYSTEM = """\
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
    return config.classify_cfg().get("prompt_version", "classify-1")


def _model() -> str:
    return config.models().get("classify", "Claude Sonnet 4.7")


def _sidecar_dir(openalex_id: str, base: Path | None = None) -> Path:
    return work_dir(openalex_id, base) / ".classify"


def _sidecar_path(seed_id: str, citing_id: str, base: Path | None = None) -> Path:
    return _sidecar_dir(seed_id, base) / f"{citing_id}.json"


def _load_sidecar(seed_id: str, citing_id: str, base: Path | None = None) -> dict | None:
    p = _sidecar_path(seed_id, citing_id, base)
    if not p.exists():
        return None
    try:
        return read_json(p)
    except (json.JSONDecodeError, OSError):
        return None


def _write_sidecar(seed_id: str, citing_id: str, result: dict, base: Path | None = None) -> None:
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
    """Classify a single citing work's relationship to the seed."""
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

    result = chat_json(_SYSTEM, user_msg, model_role="classify", cost_sink=cost_sink)

    relationship = result.get("relationship", "background-mention")
    if relationship not in RELATIONSHIPS:
        relationship = "background-mention"

    return {
        "relationship": relationship,
        "confidence": float(result.get("confidence", 0.5)),
        "justification": result.get("justification", ""),
        "has_abstract": bool(citing_work.get("abstract")),
        "strength": RELATIONSHIP_STRENGTH.get(relationship, 1),
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
