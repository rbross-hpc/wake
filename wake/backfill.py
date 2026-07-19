# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Lazy abstract backfill for citing works missing an OpenAlex abstract.

Tried in config order (default: OSTI, then Semantic Scholar) only for works
actually selected for classification — never eagerly for the full citing
set. Each source is best-effort: a miss or a source-level error is not
fatal, we just fall through to the next source (or give up and let
classify.py fall back to title+venue-only classification).
"""
from __future__ import annotations

import sys
import time
from typing import Any, Callable

from . import config
from .sources import osti, semanticscholar


def _cfg() -> dict[str, Any]:
    return config.load().get("abstract_backfill", {})


def _source_func(name: str) -> Callable[[str], str | None] | None:
    """Look up a backfill source function by name at call time (not at
    import time), so tests can monkeypatch e.g. wake.backfill.osti and have
    it take effect.
    """
    if name == "osti":
        return osti.get_abstract_by_doi
    if name == "semanticscholar":
        return semanticscholar.get_abstract_by_doi
    return None


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def backfill_one(work: dict[str, Any], *, verbose: bool = False) -> dict[str, Any]:
    """Attempt to fill in a missing abstract for a single citing work.

    Returns a new dict: if an abstract is found, it's merged in along with
    an 'abstract_source' field recording which source supplied it (never
    'openalex' — that's the default, no-backfill-needed case). If nothing
    is found (or the work already has an abstract, or no DOI), the work is
    returned unmodified.
    """
    if work.get("abstract") or not work.get("doi"):
        return work

    cfg = _cfg()
    sources = cfg.get("sources", ["osti", "semanticscholar"])
    rate_limits = cfg.get("rate_limit_s", {})
    doi = work["doi"]

    for source_name in sources:
        func = _source_func(source_name)
        if func is None:
            continue
        try:
            abstract = func(doi)
        except Exception as exc:
            if verbose:
                print(f"[wake]   WARN: {source_name} backfill failed for {doi}: {exc}", file=sys.stderr)
            abstract = None
        finally:
            delay = rate_limits.get(source_name, 1.0)
            if delay > 0:
                time.sleep(delay)

        if abstract:
            if verbose:
                print(f"[wake]   Backfilled abstract for {work.get('openalex_id')} via {source_name}", file=sys.stderr)
            return {**work, "abstract": abstract, "abstract_source": source_name}

    return work


def backfill_missing(
    works: list[dict[str, Any]],
    *,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Backfill abstracts for every work in *works* missing one.

    Intended to be called on the (typically small) selection about to be
    classified, not the full citing set — this is what keeps it lazy and
    fast, since only a minority of works lack an abstract and only that
    minority incurs the extra network round-trips.
    """
    if not is_enabled():
        return works
    result = []
    n_attempted = 0
    n_recovered = 0
    for w in works:
        if w.get("abstract") or not w.get("doi"):
            result.append(w)
            continue
        n_attempted += 1
        filled = backfill_one(w, verbose=verbose)
        if filled.get("abstract"):
            n_recovered += 1
        result.append(filled)

    if verbose and n_attempted:
        print(
            f"[wake] Abstract backfill: recovered {n_recovered}/{n_attempted} "
            f"missing abstracts.",
            file=sys.stderr,
        )

    return result
