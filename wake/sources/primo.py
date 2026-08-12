# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Ex Libris Primo discovery-layer lookup, used to backfill citing works'
abstracts and missing DOIs.

Primo aggregates publisher metadata (Elsevier, Springer, IEEE, ACM, ...)
behind a single institutional discovery endpoint. Its public
(unauthenticated) REST API returns full bibliographic records — including
abstracts — for records the library's Primo Central Index has harvested,
which frequently covers publishers OpenAlex's own abstract reconstruction
misses entirely. It tolerates a much higher request rate than OSTI/Semantic
Scholar in practice (no throttling observed at low double-digit req/s), so
it is tried first in the abstract-backfill chain (see backfill.py) when
configured.

This module deliberately does **not** ship a default endpoint. Primo is an
*institutional* service — the endpoint below is specific to whichever
library the caller has access to (e.g. Argonne's `anl.primo.exlibrisgroup.com`)
and must never be hard-coded, or every wake install would silently query
one institution's system. Every function here is a safe no-op (returns
None) unless a base URL is supplied via config or environment — see
`_endpoint()`.

Configuration (all optional; unset = feature inactive):
  Environment variables (checked first, so a real endpoint never needs to
  live in a committed config file):
    WAKE_PRIMO_BASE_URL  -- e.g. "https://anl.primo.exlibrisgroup.com"
    WAKE_PRIMO_VID       -- e.g. "01ANL_INST:01ANL"
    WAKE_PRIMO_INST      -- e.g. "01ANL_INST"
    WAKE_PRIMO_SCOPE     -- e.g. "MyInst_and_CI" (default if unset)
  config.yaml `abstract_backfill.primo` block (see config.yaml's commented
  example) as a fallback for any of the above not set via environment.

No PDF acquisition here by design: Primo's `linktopdf` only ever appears
for already-open-access records, which OpenAlex/OSTI/arXiv/Unpaywall
already surface — see PLAN.md/BACKLOG.md for the (deferred) idea of
harvesting OpenAlex's own best_oa_location.pdf_url instead, which would be
a strictly earlier and non-redundant opportunity.
"""
from __future__ import annotations

import os
import re
from typing import Any

import requests

from .. import config
from ..similarity import title_ratio
from ._http import raise_for_rate_limit

SOURCE_NAME = "primo"

_DEFAULT_SCOPE = "MyInst_and_CI"
_DEFAULT_TAB = "Everything"
_DEFAULT_TITLE_SIMILARITY_THRESHOLD = 0.85


def _cfg() -> dict[str, Any]:
    return config.load().get("abstract_backfill", {}).get("primo", {}) or {}


def _endpoint() -> dict[str, str] | None:
    """Resolve the Primo endpoint from environment first, then config.

    Returns None (feature inactive) if no base_url is available from
    either source -- the safe default for every wake install that hasn't
    explicitly configured an institutional Primo endpoint.
    """
    cfg = _cfg()
    base_url = os.environ.get("WAKE_PRIMO_BASE_URL") or cfg.get("base_url")
    if not base_url:
        return None
    vid = os.environ.get("WAKE_PRIMO_VID") or cfg.get("vid")
    inst = os.environ.get("WAKE_PRIMO_INST") or cfg.get("inst")
    scope = os.environ.get("WAKE_PRIMO_SCOPE") or cfg.get("scope") or _DEFAULT_SCOPE
    if not vid or not inst:
        return None
    return {
        "base_url": base_url.rstrip("/"),
        "vid": vid,
        "inst": inst,
        "scope": scope,
    }


def is_enabled() -> bool:
    return _endpoint() is not None


def _title_similarity_threshold() -> float:
    return float(_cfg().get("title_similarity_threshold", _DEFAULT_TITLE_SIMILARITY_THRESHOLD))


def _user_agent() -> str:
    mailto = os.environ.get("OPENALEX_MAILTO", "")
    if mailto:
        return f"wake/0.1 (mailto:{mailto})"
    return "wake/0.1"


def _normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.lower() or None


def _clean_description(desc: str | None) -> str | None:
    if not desc:
        return None
    # Primo abstracts occasionally carry light HTML/entity artifacts from
    # the source publisher record.
    text = re.sub(r"<[^>]+>", "", desc).strip()
    return text or None


def _query(q: str, *, field: str = "any", limit: int = 3) -> list[dict[str, Any]]:
    """Issue a raw PNX search and return the list of doc records (may be
    empty). Raises RateLimited on 429; returns [] for any other
    non-200/no-endpoint case (best-effort, never a required lookup)."""
    endpoint = _endpoint()
    if endpoint is None:
        return []

    url = f"{endpoint['base_url']}/primaws/rest/pub/pnxs"
    params = {
        "blendFacetsSeparately": "false",
        "getMore": "0",
        "inst": endpoint["inst"],
        "lang": "en",
        "limit": str(limit),
        "mode": "advanced",
        "offset": "0",
        "pcAvailability": "true",
        "q": f"{field},contains,{q}",
        "scope": endpoint["scope"],
        "skipDelivery": "Y",
        "sort": "rank",
        "tab": _DEFAULT_TAB,
        "vid": endpoint["vid"],
    }
    resp = requests.get(
        url,
        params=params,
        headers={"User-Agent": _user_agent()},
        timeout=20,
    )
    if resp.status_code == 200:
        try:
            data = resp.json()
        except ValueError:
            return []
        return data.get("docs", []) or []
    if resp.status_code in (404, 410):
        return []
    raise_for_rate_limit(resp, SOURCE_NAME)
    resp.raise_for_status()
    return []


def _first_field(disp: dict[str, Any], key: str) -> str | None:
    val = disp.get(key)
    if isinstance(val, list) and val:
        return val[0]
    return None


def _record_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    pnx = doc.get("pnx", {})
    disp = pnx.get("display", {})
    addata = pnx.get("addata", {})
    doi_list = addata.get("doi")
    return {
        "title": _first_field(disp, "title"),
        "abstract": _clean_description(_first_field(disp, "description")),
        "doi": doi_list[0] if isinstance(doi_list, list) and doi_list else None,
    }


def get_metadata_by_doi(doi: str) -> dict[str, Any] | None:
    """Return {"title", "abstract", "doi"} for *doi*, or None if unavailable
    (no endpoint configured, no hit, or non-fatal lookup failure)."""
    norm = _normalize_doi(doi)
    if not norm:
        return None
    docs = _query(norm, field="any", limit=1)
    if not docs:
        return None
    return _record_from_doc(docs[0])


def get_abstract_by_doi(doi: str) -> str | None:
    """Return the Primo-aggregated abstract for *doi*, or None.

    Same best-effort contract as sources/osti.py::get_abstract_by_doi:
    None (not an exception) for no-endpoint/no-match; raises on rate
    limiting or unexpected transport errors so callers can back off.
    """
    record = get_metadata_by_doi(doi)
    if not record:
        return None
    return record.get("abstract")


def _best_title_match(
    docs: list[dict[str, Any]], ref_title: str, threshold: float
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_ratio = 0.0
    for doc in docs:
        record = _record_from_doc(doc)
        ratio = title_ratio(ref_title, record.get("title"))
        if ratio > best_ratio:
            best_ratio = ratio
            best = record
    if best is not None and best_ratio >= threshold:
        return best
    return None


def get_abstract_by_title(title: str) -> str | None:
    """Fallback lookup for DOI-less works: search by title, accept the
    best-matching hit only if it clears the configured title-similarity
    threshold (guards against a generic title returning an unrelated
    top result -- see module tests). Returns None on no endpoint, no
    hit, or no sufficiently-similar hit.
    """
    if not title:
        return None
    docs = _query(title, field="title", limit=5)
    if not docs:
        return None
    match = _best_title_match(docs, title, _title_similarity_threshold())
    if not match:
        return None
    return match.get("abstract")


def get_doi_by_title(title: str) -> str | None:
    """Fallback DOI recovery for DOI-less works: same title-similarity
    guard as get_abstract_by_title. Returns None on no endpoint, no hit,
    no sufficiently-similar hit, or a hit with no DOI of its own.
    """
    if not title:
        return None
    docs = _query(title, field="title", limit=5)
    if not docs:
        return None
    match = _best_title_match(docs, title, _title_similarity_threshold())
    if not match:
        return None
    return match.get("doi")
