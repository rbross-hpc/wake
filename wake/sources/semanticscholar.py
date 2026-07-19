# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
# Adapted from ref-checker/ref_checker/sources/semanticscholar.py — abstract lookup only.
"""Semantic Scholar abstract lookup, used to backfill citing works with no
OpenAlex abstract. Complements OSTI: broader (non-DOE) coverage, but less
precise and more heavily rate-limited without an API key.
"""
from __future__ import annotations

import os
import re

import requests

from ._http import raise_for_rate_limit

SOURCE_NAME = "semanticscholar"

_BASE = "https://api.semanticscholar.org/graph/v1/paper"


def _headers() -> dict[str, str]:
    h: dict[str, str] = {}
    api_key = os.environ.get("SEMANTICSCHOLAR_API_KEY", "")
    if api_key:
        h["x-api-key"] = api_key
    return h


def _normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"^https?://doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.lower() or None


def _get_paper_by_doi(doi: str, fields: str) -> dict | None:
    """Fetch the raw Semantic Scholar paper dict for *doi*, requesting
    *fields*, or None if unavailable. Raises on rate limiting (403/429) or
    unexpected errors so callers can back off.
    """
    norm = _normalize_doi(doi)
    if not norm:
        return None
    resp = requests.get(
        f"{_BASE}/DOI:{norm}",
        params={"fields": fields},
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code == 200:
        entry = resp.json()
        return entry or None
    if resp.status_code in (404, 410):
        return None
    raise_for_rate_limit(resp, SOURCE_NAME)
    if resp.status_code == 403:
        raise requests.HTTPError(
            "403 Forbidden from Semantic Scholar — check SEMANTICSCHOLAR_API_KEY "
            "(auth failure, not rate limit)"
        )
    resp.raise_for_status()
    return None


def get_abstract_by_doi(doi: str) -> str | None:
    """Return the Semantic Scholar abstract for *doi*, or None if unavailable.

    Returns None (not an exception) for 404/no-match — this is a best-effort
    backfill, not a required lookup. Raises on rate limiting (403/429) or
    unexpected errors so callers can back off.
    """
    entry = _get_paper_by_doi(doi, fields="abstract")
    if not entry:
        return None
    abstract = entry.get("abstract")
    return abstract.strip() if abstract else None


def get_open_access_pdf_url_by_doi(doi: str) -> str | None:
    """Return Semantic Scholar's openAccessPdf.url for *doi*, or None.

    This field is populated from Semantic Scholar's own OA discovery
    (distinct from, and often complementary to, Unpaywall's) — frequently
    points at a repository copy (e.g. arXiv) rather than the publisher.
    """
    entry = _get_paper_by_doi(doi, fields="openAccessPdf")
    if not entry:
        return None
    oa_pdf = entry.get("openAccessPdf")
    if isinstance(oa_pdf, dict):
        url = oa_pdf.get("url")
        if url:
            return url
    return None
