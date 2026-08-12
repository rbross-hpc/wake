# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Abstract (and DOI) backfill for citing works, tried lazily — only for
works actually selected for classification, never eagerly for the full
citing set.

Two independent enrichments, both best-effort (a miss or a source-level
error is never fatal — we just fall through to the next source, or leave
the work as-is and let classify.py fall back to title+venue-only
classification):

  - **Abstract backfill.** By default this only fires for works OpenAlex
    left abstract-less, trying each configured source in order (default:
    Primo, then OSTI, then Semantic Scholar) until one hits. If
    `abstract_backfill.primo.prefer_over_openalex` is set *and* Primo is
    configured (see sources/primo.py), Primo is instead tried for every
    work regardless of whether OpenAlex already supplied an abstract —
    Primo's aggregated publisher abstracts are frequently more complete
    than OpenAlex's reconstructed-from-inverted-index ones. In that
    "prefer" case, a Primo miss simply keeps whatever abstract OpenAlex
    already had; it does not fall through to OSTI/Semantic Scholar (those
    remain gap-fillers for genuinely abstract-less works, not a
    "better than OpenAlex" cascade).
  - **DOI backfill.** When a work has no DOI at all (some pre-2010 or
    non-journal citing works), Primo can often recover one via a
    title-similarity-guarded search — see sources/primo.py's
    `get_doi_by_title`. Recorded as `doi_source: primo` on the work.
    Only attempted if Primo is configured; a no-op otherwise.

Primo is tried first by default (see config.yaml's abstract_backfill
block) because it tolerates a much higher request rate in practice than
OSTI/Semantic Scholar, but it is entirely opt-in: with no Primo endpoint
configured (the default for every wake install other than one that has
set WAKE_PRIMO_BASE_URL or the config's primo.base_url), every Primo call
in this module is a fast, silent no-op and behavior is unchanged from
before Primo support existed.
"""
from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any

from . import config
from .sources import osti, primo, semanticscholar

DEFAULT_SOURCES = ["primo", "osti", "semanticscholar"]


def _cfg() -> dict[str, Any]:
    return config.load().get("abstract_backfill", {})


def _primo_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg.get("primo", {}) or {}


def _source_func(name: str) -> Callable[[str], str | None] | None:
    """Look up a backfill source function by name at call time (not at
    import time), so tests can monkeypatch e.g. wake.backfill.osti and have
    it take effect.
    """
    if name == "primo":
        return primo.get_abstract_by_doi
    if name == "osti":
        return osti.get_abstract_by_doi
    if name == "semanticscholar":
        return semanticscholar.get_abstract_by_doi
    return None


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def _attempt(
    func: Callable[[str], str | None],
    arg: str,
    source_name: str,
    rate_limits: dict[str, float],
    verbose: bool,
    *,
    label: str,
) -> str | None:
    """Call *func(arg)*, sleeping the configured per-source delay
    afterward regardless of outcome (courtesy rate-limiting), and
    swallowing any exception (best-effort — a source-level failure just
    means this source didn't pan out, not that backfill as a whole
    failed)."""
    try:
        value = func(arg)
    except Exception as exc:
        if verbose:
            print(
                f"[wake]   WARN: {source_name} {label} backfill failed for {arg}: {exc}",
                file=sys.stderr,
            )
        value = None
    finally:
        delay = rate_limits.get(source_name, 1.0)
        if delay > 0:
            time.sleep(delay)
    return value


def backfill_one(work: dict[str, Any], *, verbose: bool = False) -> dict[str, Any]:
    """Attempt to fill in a missing DOI and/or abstract for a single
    citing work. Returns a new dict with whatever was recovered merged in
    (`abstract`/`abstract_source`, `doi`/`doi_source`) — the original
    *work* is returned unmodified if nothing was recovered or attempted.

    See module docstring for the full DOI-backfill / abstract-backfill /
    "prefer Primo over OpenAlex" decision tree.
    """
    cfg = _cfg()
    sources = cfg.get("sources", DEFAULT_SOURCES)
    rate_limits = cfg.get("rate_limit_s", {})
    prefer_primo = bool(_primo_cfg(cfg).get("prefer_over_openalex", False))

    result = work
    doi = work.get("doi")
    title = work.get("title")
    has_abstract = bool(work.get("abstract"))

    # --- DOI backfill (independent of abstract state; only for works
    # OpenAlex/Crossref never assigned a DOI to in the first place) ---
    if not doi and title and primo.is_enabled():
        found_doi = _attempt(
            primo.get_doi_by_title, title, "primo", rate_limits, verbose, label="DOI"
        )
        if found_doi:
            if verbose:
                print(
                    f"[wake]   Backfilled DOI for {work.get('openalex_id')} via primo",
                    file=sys.stderr,
                )
            result = {**result, "doi": found_doi, "doi_source": "primo"}
            doi = found_doi

    # --- Abstract backfill ---
    if has_abstract:
        if not (prefer_primo and primo.is_enabled() and doi):
            return result
        # "Prefer Primo" mode: try Primo only, even though OpenAlex already
        # supplied an abstract. A miss here keeps the existing (OpenAlex)
        # abstract rather than falling through to OSTI/Semantic Scholar,
        # which exist to fill genuine gaps, not to second-guess OpenAlex.
        primo_abstract = _attempt(
            primo.get_abstract_by_doi, doi, "primo", rate_limits, verbose, label="abstract"
        )
        if primo_abstract:
            if verbose:
                print(
                    f"[wake]   Preferred Primo abstract for {work.get('openalex_id')} "
                    "over OpenAlex's",
                    file=sys.stderr,
                )
            return {**result, "abstract": primo_abstract, "abstract_source": "primo"}
        return result

    if not doi:
        return result

    # No abstract at all yet: cascade through the full configured chain.
    for source_name in sources:
        if source_name == "primo" and not primo.is_enabled():
            continue
        func = _source_func(source_name)
        if func is None:
            continue
        abstract = _attempt(func, doi, source_name, rate_limits, verbose, label="abstract")
        if abstract:
            if verbose:
                print(
                    f"[wake]   Backfilled abstract for {work.get('openalex_id')} via {source_name}",
                    file=sys.stderr,
                )
            return {**result, "abstract": abstract, "abstract_source": source_name}

    return result


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

    Deliberately does not route works that already have an abstract
    through backfill_one, even in "prefer Primo" mode — callers wanting
    that (e.g. classify.py, which calls backfill_one directly per work)
    should call backfill_one themselves. This function's contract is
    specifically "fill genuine gaps," matching its callers (gaps.py).
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
