# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""LLM-classify each citing work's relationship to the seed paper.

Relationship classes (ordered by strength, strongest first):
  extends          – directly extends the method/framework of the seed
  builds-on        – builds a new system/algorithm on top of the seed
  uses-as-tool     – uses the seed's software/tool/dataset as-is
  benchmarks       – compares against the seed as a baseline/benchmark
  applies-to-domain – applies the seed's approach to a new domain/problem
  background-mention – cites as background/related work without direct use

Each classification is written atomically as a sidecar JSON file, so the
pipeline is safely resumable after Ctrl-C.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from . import config
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
    "background-mention",
]

RELATIONSHIP_STRENGTH: dict[str, int] = {
    "extends": 6,
    "builds-on": 5,
    "uses-as-tool": 4,
    "benchmarks": 3,
    "applies-to-domain": 2,
    "background-mention": 1,
}

_SYSTEM = """\
You are a bibliometric analyst classifying how a citing paper uses a seed paper.

Relationship classes (choose exactly one):
- extends: The citing paper directly extends the method, framework, or theory of the seed.
- builds-on: The citing paper builds a new system, algorithm, or tool that depends on the seed.
- uses-as-tool: The citing paper uses the seed's software, tool, or dataset as-is without modification.
- benchmarks: The citing paper benchmarks against or compares performance with the seed.
- applies-to-domain: The citing paper applies the seed's approach to a new domain or problem.
- background-mention: The citing paper cites the seed only as background or related work.

Respond ONLY with valid JSON matching this schema:
{
  "relationship": "<one of the classes above>",
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
    result = chat_json(_SYSTEM, user_msg, model_role="classify")

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


def classify_all(
    seed_work: dict[str, Any],
    citing_works: list[dict[str, Any]],
    *,
    base: Path | None = None,
    force: bool = False,
    verbose: bool = True,
    inter_call_delay: float = 0.5,
) -> list[dict[str, Any]]:
    """Classify all citing works; write atomic sidecars; return full classified list.

    Resumable: already-classified works are loaded from sidecars.
    Each item in the returned list is the citing work dict merged with
    the classification result.
    """
    seed_id = seed_work["openalex_id"]
    pv = _prompt_version()
    model = _model()

    classified: list[dict[str, Any]] = []
    done = 0
    skipped = 0
    errors = 0
    total = len(citing_works)

    for i, cw in enumerate(citing_works):
        citing_id = cw.get("openalex_id", f"unknown-{i}")

        cached = None if force else _load_sidecar(seed_id, citing_id, base)
        if cached and cached.get("prompt_version") == pv and cached.get("model") == model:
            classified.append({**cw, **cached})
            skipped += 1
            continue

        try:
            result = classify_one(seed_work, cw)
        except Exception as exc:
            if verbose:
                print(f"[wake]   WARN: classify failed for {citing_id}: {exc}", file=sys.stderr)
            result = {
                "relationship": "background-mention",
                "confidence": 0.0,
                "justification": f"Classification failed: {exc}",
                "has_abstract": bool(cw.get("abstract")),
                "strength": 1,
                "error": str(exc),
            }
            errors += 1

        sidecar = {
            **result,
            "prompt_version": pv,
            "model": model,
            "classified_at": now_iso(),
        }
        _write_sidecar(seed_id, citing_id, sidecar, base)
        classified.append({**cw, **sidecar})
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
        print(
            f"[wake] Classification done: {done + skipped:,} total "
            f"({done} new, {skipped} cached, {errors} errors)",
            file=sys.stderr,
        )

    return classified


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
