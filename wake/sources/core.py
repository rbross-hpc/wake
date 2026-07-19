# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""CORE.ac.uk aggregated open-access PDF lookup.

CORE (https://core.ac.uk) aggregates repository-hosted open-access copies
across a huge number of institutional and subject repositories — broader
than Unpaywall/Semantic Scholar for some literature, but requires a free
API key (https://core.ac.uk/services/api). Optional: silently skipped
(returns None) if CORE_API_KEY is unset, same pattern as
SEMANTICSCHOLAR_API_KEY — never a hard requirement for wake.

Note: this module has not been live-tested against the real CORE API in
this environment (no API key was available). The request shape follows
CORE API v3's documented search-by-DOI convention; verify against a real
key before relying on it in production, and adjust if the API has since
changed.
"""
from __future__ import annotations

import os
import re

import requests

from ._http import raise_for_rate_limit

SOURCE_NAME = "core"

_BASE = "https://api.core.ac.uk/v3/search/works"


def _api_key() -> str:
    return os.environ.get("CORE_API_KEY", "").strip()


def is_enabled() -> bool:
    return bool(_api_key())


def _normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.lower() or None


def get_oa_pdf_url_by_doi(doi: str) -> str | None:
    """Return a CORE-hosted or CORE-indexed OA PDF URL for *doi*, or None.

    Returns None immediately (no request made) if CORE_API_KEY is unset —
    this source is opt-in. Returns None (not an exception) for no-match.
    Raises on rate limiting or unexpected errors so callers can back off.
    """
    api_key = _api_key()
    if not api_key:
        return None
    norm = _normalize_doi(doi)
    if not norm:
        return None

    resp = requests.get(
        _BASE,
        params={"q": f'doi:"{norm}"'},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )
    if resp.status_code == 200:
        data = resp.json()
        results = data.get("results", []) if isinstance(data, dict) else []
        for result in results:
            url = result.get("downloadUrl")
            if not url:
                fulltext_urls = result.get("sourceFulltextUrls") or []
                url = fulltext_urls[0] if fulltext_urls else None
            if url:
                return url
        return None
    if resp.status_code in (404, 410):
        return None
    raise_for_rate_limit(resp, SOURCE_NAME)
    if resp.status_code in (401, 403):
        raise requests.HTTPError(
            "401/403 from CORE — check CORE_API_KEY validity"
        )
    resp.raise_for_status()
    return None
