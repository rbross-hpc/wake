# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Abstract (and DOI) backfill for citing works, tried lazily — only for
works actually selected for classification, never eagerly for the full
citing set.

Three independent enrichments, all best-effort (a miss or a source-level
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
  - **OA PDF URL capture (primo_pdf_url).** Whenever Primo is consulted
    for a work anyway (DOI backfill, abstract cascade/gap-fill, or
    "prefer Primo" mode) and Primo's record carries its own OA PDF link
    (see sources/primo.py's OA gate), it's captured onto the work as
    `primo_pdf_url` at the same time -- no extra Primo call beyond the
    one already being made for the abstract/DOI. This is deliberately
    separate from OpenAlex's own `oa_pdf_url` (captured earlier, at
    `wake citing` time, in sources/openalex.py) rather than merged into
    one field -- see pdf_fetch.py, which tries both, OpenAlex's first.
    A work that's never abstract-less and never DOI-less under the
    default (non-"prefer") config simply never has Primo consulted, so
    it won't have a primo_pdf_url from this path either -- consistent
    with how abstract_source already behaves; a live Primo lookup still
    happens in pdf_fetch.py itself for such works, if reached.

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
from typing import Any, TypeVar

from . import config
from .sources import osti, primo, semanticscholar

_T = TypeVar("_T")

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
    func: Callable[[str], _T | None],
    arg: str,
    source_name: str,
    rate_limits: dict[str, float],
    verbose: bool,
    *,
    label: str,
) -> _T | None:
    """Call *func(arg)*, sleeping the configured per-source delay
    afterward regardless of outcome (courtesy rate-limiting), and
    swallowing any exception (best-effort — a source-level failure just
    means this source didn't pan out, not that backfill as a whole
    failed). Generic over the return type since callers pass both
    str-returning lookups (osti.get_abstract_by_doi) and dict-returning
    ones (primo.get_metadata_by_doi/get_record_by_title)."""
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


def _with_primo_pdf_url(
    result: dict[str, Any], record: dict[str, Any] | None, *, verbose: bool, openalex_id: Any
) -> dict[str, Any]:
    """Merge in primo_pdf_url from a Primo record dict (as returned by
    get_metadata_by_doi/get_record_by_title), if present. No-op if
    *record* is None or carries no OA PDF link -- capturing this is a
    side effect of a Primo call already being made for the DOI/abstract,
    never an extra one."""
    if not record:
        return result
    url = record.get("oa_pdf_url")
    if not url:
        return result
    if verbose:
        print(f"[wake]   Captured Primo OA PDF URL for {openalex_id}", file=sys.stderr)
    return {**result, "primo_pdf_url": url}


def backfill_one(work: dict[str, Any], *, verbose: bool = False) -> dict[str, Any]:
    """Attempt to fill in a missing DOI, abstract, and/or OA PDF URL for a
    single citing work. Returns a new dict with whatever was recovered
    merged in (`abstract`/`abstract_source`, `doi`/`doi_source`,
    `primo_pdf_url`) — the original *work* is returned unmodified if
    nothing was recovered or attempted.

    See module docstring for the full DOI-backfill / abstract-backfill /
    "prefer Primo over OpenAlex" / OA-PDF-URL-capture decision tree.
    """
    cfg = _cfg()
    sources = cfg.get("sources", DEFAULT_SOURCES)
    rate_limits = cfg.get("rate_limit_s", {})
    prefer_primo = bool(_primo_cfg(cfg).get("prefer_over_openalex", False))
    openalex_id = work.get("openalex_id")

    result = work
    doi = work.get("doi")
    title = work.get("title")
    has_abstract = bool(work.get("abstract"))
    # Carries a Primo record fetched incidentally along the way (DOI
    # backfill's title lookup), so the abstract-backfill cascade below
    # can reuse its abstract instead of re-querying Primo for the same
    # work a second time.
    doi_backfill_record: dict[str, Any] | None = None

    # --- DOI backfill (independent of abstract state; only for works
    # OpenAlex/Crossref never assigned a DOI to in the first place).
    # Uses get_record_by_title (not get_doi_by_title) so an abstract
    # and/or PDF URL Primo happens to have for this record are captured
    # in the same call. ---
    if not doi and title and primo.is_enabled():
        doi_backfill_record = _attempt(
            primo.get_record_by_title, title, "primo", rate_limits, verbose, label="DOI"
        )
        if doi_backfill_record and doi_backfill_record.get("doi"):
            if verbose:
                print(f"[wake]   Backfilled DOI for {openalex_id} via primo", file=sys.stderr)
            result = {**result, "doi": doi_backfill_record["doi"], "doi_source": "primo"}
            doi = doi_backfill_record["doi"]
        result = _with_primo_pdf_url(
            result, doi_backfill_record, verbose=verbose, openalex_id=openalex_id
        )

    # --- Abstract backfill ---
    if has_abstract:
        if not (prefer_primo and primo.is_enabled() and doi):
            return result
        # "Prefer Primo" mode: try Primo only, even though OpenAlex already
        # supplied an abstract. A miss here keeps the existing (OpenAlex)
        # abstract rather than falling through to OSTI/Semantic Scholar,
        # which exist to fill genuine gaps, not to second-guess OpenAlex.
        # Uses get_metadata_by_doi (not get_abstract_by_doi) so a PDF URL
        # is captured in the same call.
        record = doi_backfill_record or _attempt(
            primo.get_metadata_by_doi, doi, "primo", rate_limits, verbose, label="abstract"
        )
        result = _with_primo_pdf_url(result, record, verbose=verbose, openalex_id=openalex_id)
        primo_abstract = record.get("abstract") if record else None
        if primo_abstract:
            if verbose:
                print(
                    f"[wake]   Preferred Primo abstract for {openalex_id} over OpenAlex's",
                    file=sys.stderr,
                )
            return {**result, "abstract": primo_abstract, "abstract_source": "primo"}
        return result

    if not doi:
        return result

    # No abstract at all yet: cascade through the full configured chain.
    # If DOI backfill already fetched a Primo record above (same DOI),
    # reuse its abstract/PDF URL instead of calling Primo again.
    for source_name in sources:
        if source_name == "primo":
            if not primo.is_enabled():
                continue
            # Special-cased (like pdf_fetch.py's arxiv/core) to use the
            # combined-record lookup so an OA PDF URL is captured in the
            # same call as the abstract, rather than a second Primo
            # round-trip via the generic get_abstract_by_doi wrapper.
            record = doi_backfill_record or _attempt(
                primo.get_metadata_by_doi, doi, "primo", rate_limits, verbose, label="abstract"
            )
            result = _with_primo_pdf_url(result, record, verbose=verbose, openalex_id=openalex_id)
            abstract = record.get("abstract") if record else None
        else:
            func = _source_func(source_name)
            if func is None:
                continue
            abstract = _attempt(func, doi, source_name, rate_limits, verbose, label="abstract")
        if abstract:
            if verbose:
                print(
                    f"[wake]   Backfilled abstract for {openalex_id} via {source_name}",
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
