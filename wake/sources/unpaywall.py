# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Unpaywall open-access PDF location lookup.

Unpaywall (https://unpaywall.org) aggregates open-access location metadata
for DOIs across repositories and publishers. It does NOT provide abstracts
(see wake.backfill for that problem — solved via OSTI/Semantic Scholar
instead) — only URLs to where an OA copy might be found. Those URLs
frequently point at publisher "author manuscript" pages that reject
unauthenticated/bot downloads (confirmed: ScienceDirect 403s during
testing), so this is one link in wake's PDF acquisition chain, not a
standalone guarantee.

Requires an email address per Unpaywall's usage policy — reuses
OPENALEX_MAILTO (same polite-pool convention as sources/openalex.py).
"""
from __future__ import annotations

import os
import re

import requests

from ._http import raise_for_rate_limit

SOURCE_NAME = "unpaywall"

_BASE = "https://api.unpaywall.org/v2"


def _mailto() -> str:
    return os.environ.get("OPENALEX_MAILTO", "").strip()


def _normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.lower() or None


def get_oa_pdf_url_by_doi(doi: str) -> str | None:
    """Return Unpaywall's best-OA-location PDF URL for *doi*, or None.

    Returns None (not an exception) for 404/no-match or a missing mailto
    (Unpaywall requires one; we don't fail loudly here since this is one
    link in a best-effort chain — see pdf_fetch.py). Raises on rate
    limiting or unexpected errors so callers can back off.
    """
    norm = _normalize_doi(doi)
    if not norm:
        return None
    mailto = _mailto()
    if not mailto:
        return None
    resp = requests.get(f"{_BASE}/{norm}", params={"email": mailto}, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        loc = data.get("best_oa_location") or {}
        url = loc.get("url_for_pdf") or loc.get("url")
        return url or None
    if resp.status_code in (404, 410):
        return None
    raise_for_rate_limit(resp, SOURCE_NAME)
    resp.raise_for_status()
    return None
