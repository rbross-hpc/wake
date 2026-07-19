# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Fetch and cache all citing works for a seed paper."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import config
from .io import atomic_write_json, now_iso, read_json
from .seed import work_dir
from .sources.openalex import count_citing_works, iter_citing_works
from .state import is_stage_current, mark_stage_complete

_STAGE = "citing"
_VERSION = "citing-1"


def citing_path(openalex_id: str, base: Path | None = None) -> Path:
    return work_dir(openalex_id, base) / "citing.json"


def load_citing(openalex_id: str, base: Path | None = None) -> list[dict] | None:
    p = citing_path(openalex_id, base)
    if not p.exists():
        return None
    data = read_json(p)
    return data.get("works") if isinstance(data, dict) else data


def fetch_and_cache(
    openalex_id: str,
    *,
    base: Path | None = None,
    force: bool = False,
    min_year: int | None = None,
    verbose: bool = True,
) -> list[dict[str, Any]]:
    """Fetch all citing works from OpenAlex and cache to citing.json.

    Returns the list of normalized work dicts.
    Skips the network call if already cached (unless force=True).
    """
    oa_cfg = config.openalex_cfg()
    rate_limit_s = oa_cfg.get("rate_limit_s", 1.0)
    per_page = oa_cfg.get("per_page", 200)

    wd = work_dir(openalex_id, base)
    wd.mkdir(parents=True, exist_ok=True)

    extra_key: dict[str, Any] = {"citing_version": _VERSION}
    if min_year is not None:
        extra_key["min_year"] = min_year

    if not force and is_stage_current(wd, _STAGE, seed_id=openalex_id, extra_key=extra_key):
        cached = load_citing(openalex_id, base)
        if cached is not None:
            if verbose:
                print(f"[wake] Citing works: loaded {len(cached):,} from cache.", file=sys.stderr)
            return cached

    if verbose:
        total = count_citing_works(openalex_id)
        print(f"[wake] Fetching {total:,} citing works for {openalex_id}...", file=sys.stderr)

    works: list[dict] = []
    try:
        for i, work in enumerate(iter_citing_works(
            openalex_id,
            per_page=per_page,
            rate_limit_s=rate_limit_s,
            min_year=min_year,
        )):
            works.append(work)
            if verbose and (i + 1) % 200 == 0:
                print(f"[wake]   ... fetched {i + 1:,} citing works", file=sys.stderr)
    except KeyboardInterrupt:
        if verbose:
            print(f"\n[wake] Interrupted after {len(works):,} citing works. Partial results NOT cached.", file=sys.stderr)
        raise

    payload: dict[str, Any] = {
        "seed_openalex_id": openalex_id,
        "fetched_at": now_iso(),
        "min_year": min_year,
        "count": len(works),
        "works": works,
    }
    atomic_write_json(citing_path(openalex_id, base), payload)
    mark_stage_complete(
        wd, _STAGE,
        seed_id=openalex_id,
        extra={**extra_key, "count": len(works)},
    )

    if verbose:
        print(f"[wake] Cached {len(works):,} citing works → {citing_path(openalex_id, base)}", file=sys.stderr)

    return works


_SORT_KEYS = {
    "cited-by": lambda w: -(w.get("cited_by_count") or 0),
    "recent": lambda w: -(w.get("year") or 0),
    "oldest": lambda w: (w.get("year") or 0),
}


def sort_works(works: list[dict], sort: str = "cited-by") -> list[dict]:
    """Sort works by the given key. 'random' shuffles deterministically-seeded
    per-call (not reproducible across calls; use for exploratory sampling only).
    """
    if sort == "random":
        import random
        shuffled = list(works)
        random.shuffle(shuffled)
        return shuffled
    key = _SORT_KEYS.get(sort, _SORT_KEYS["cited-by"])
    return sorted(works, key=key)


def filter_works(
    works: list[dict],
    *,
    min_year: int | None = None,
    limit: int | None = None,
    sort: str | None = None,
) -> list[dict]:
    """Apply post-hoc filters (and optional sort) to a list of works."""
    result = works
    if min_year is not None:
        result = [w for w in result if (w.get("year") or 0) >= min_year]
    if sort is not None:
        result = sort_works(result, sort)
    if limit is not None:
        result = result[:limit]
    return result


def sample_works(
    works: list[dict],
    *,
    n: int = 10,
    sort: str = "cited-by",
) -> list[dict]:
    """Pick a representative slice of *n* works for human review.

    This is the explore-first primitive: before spending on classification,
    the agent shows the human a sample (by default the most-cited-first,
    since those are usually the most consequential citing works).
    """
    sorted_works = sort_works(works, sort)
    return sorted_works[:n]
