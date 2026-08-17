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
    PRIMO_BASE_URL  -- e.g. "https://anl.primo.exlibrisgroup.com"
    PRIMO_VID       -- e.g. "01ANL_INST:01ANL"
    PRIMO_INST      -- e.g. "01ANL_INST"
    PRIMO_SCOPE     -- e.g. "MyInst_and_CI" (default if unset)
  config.yaml `abstract_backfill.primo` block (see config.yaml's commented
  example) as a fallback for any of the above not set via environment.

PDF acquisition: `get_oa_pdf_url_by_doi`/`get_oa_pdf_url_by_title` expose
Primo's `linktopdf`, but only when the record's own `display.oa` field
says `free_for_read` -- Primo's full-text link only ever resolves for
records that are already open access (verified against Argonne's live
Primo instance: every paywalled IEEE/Elsevier/ACM record returned only
`linktorsrc`, a publisher abstract-page link, never a PDF). This makes
Primo's PDF value a fallback, not a primary source -- see pdf_fetch.py,
which tries OpenAlex's own best_oa_location.pdf_url first (already in
hand from `wake citing`, zero extra API calls, and dominant in practice:
every work with a Primo PDF hit in the OSTI-hosted seed case observed
during design was the *same* underlying file OpenAlex/OSTI already
pointed at) before falling to Primo late in the chain, only for the
smaller long-tail of OA copies the earlier sources miss.
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
    base_url = os.environ.get("PRIMO_BASE_URL") or cfg.get("base_url")
    if not base_url:
        return None
    vid = os.environ.get("PRIMO_VID") or cfg.get("vid")
    inst = os.environ.get("PRIMO_INST") or cfg.get("inst")
    scope = os.environ.get("PRIMO_SCOPE") or cfg.get("scope") or _DEFAULT_SCOPE
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


_LINK_URL_RE = re.compile(r"\$\$U([^$]+)")


def _is_free_for_read(disp: dict[str, Any]) -> bool:
    oa = disp.get("oa")
    if isinstance(oa, list):
        return "free_for_read" in oa
    return oa == "free_for_read"


def _extract_pdf_url(pnx: dict[str, Any]) -> str | None:
    """Pull the raw URL out of a PNX links.linktopdf entry, e.g.
    "$$Uhttps://www.osti.gov/servlets/purl/754505$$EPDF$$Gosti$$Hfree_for_read$$Pomit_proxy_true"
    -> "https://www.osti.gov/servlets/purl/754505". Only returns a URL
    when the record's own `display.oa` marks it free_for_read -- Primo
    exposes linktopdf for open-access records only, but we double-check
    here rather than trusting linktopdf's mere presence (see module
    docstring)."""
    disp = pnx.get("display", {})
    if not _is_free_for_read(disp):
        return None
    links = pnx.get("links", {})
    linktopdf = links.get("linktopdf")
    if not isinstance(linktopdf, list) or not linktopdf:
        return None
    m = _LINK_URL_RE.search(linktopdf[0])
    return m.group(1) if m else None


def _record_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    pnx = doc.get("pnx", {})
    disp = pnx.get("display", {})
    addata = pnx.get("addata", {})
    doi_list = addata.get("doi")
    return {
        "title": _first_field(disp, "title"),
        "abstract": _clean_description(_first_field(disp, "description")),
        "doi": doi_list[0] if isinstance(doi_list, list) and doi_list else None,
        "oa_pdf_url": _extract_pdf_url(pnx),
    }


def get_metadata_by_doi(doi: str) -> dict[str, Any] | None:
    """Return {"title", "abstract", "doi", "oa_pdf_url"} for *doi*, or None
    if unavailable (no endpoint configured, no hit, or non-fatal lookup
    failure). oa_pdf_url is None unless the record is free_for_read."""
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


def get_record_by_title(title: str) -> dict[str, Any] | None:
    """Fallback lookup for DOI-less works: search by title, accept the
    best-matching hit only if it clears the configured title-similarity
    threshold (guards against a generic title returning an unrelated
    top result -- see module tests). Returns
    {"title", "abstract", "doi", "oa_pdf_url"}, or None on no endpoint,
    no hit, or no sufficiently-similar hit.

    Single-query entry point for get_abstract_by_title/get_doi_by_title/
    get_oa_pdf_url_by_title below -- a caller wanting more than one of
    those fields for the same title (see backfill.py's DOI+abstract+PDF
    recovery) should call this directly instead, to avoid one Primo
    round-trip per field.
    """
    if not title:
        return None
    docs = _query(title, field="title", limit=5)
    if not docs:
        return None
    return _best_title_match(docs, title, _title_similarity_threshold())


def get_abstract_by_title(title: str) -> str | None:
    """Fallback lookup for DOI-less works: see get_record_by_title."""
    record = get_record_by_title(title)
    return record.get("abstract") if record else None


def get_doi_by_title(title: str) -> str | None:
    """Fallback DOI recovery for DOI-less works: see get_record_by_title."""
    record = get_record_by_title(title)
    return record.get("doi") if record else None


def get_oa_pdf_url_by_doi(doi: str) -> str | None:
    """Return Primo's OA PDF URL for *doi*, or None.

    Only ever non-None for a record Primo itself marks free_for_read --
    see _extract_pdf_url. This is a fallback source in pdf_fetch.py's
    chain, not a primary one: OpenAlex's own best_oa_location.pdf_url
    (captured at citing-time, zero extra API calls) is tried first and,
    in practice, frequently resolves to the exact same underlying file.
    """
    record = get_metadata_by_doi(doi)
    if not record:
        return None
    return record.get("oa_pdf_url")


def get_oa_pdf_url_by_title(title: str) -> str | None:
    """Fallback OA-PDF-URL lookup for DOI-less works: see
    get_record_by_title."""
    record = get_record_by_title(title)
    return record.get("oa_pdf_url") if record else None
