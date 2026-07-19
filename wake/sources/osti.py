# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
# Adapted from ref-checker/ref_checker/sources/osti.py — abstract lookup only.
"""OSTI abstract lookup, used to backfill citing works with no OpenAlex abstract.

OSTI (https://www.osti.gov) is the U.S. Department of Energy's repository of
DOE-funded technical reports, journal articles, conference papers, etc. Its
'description' field frequently contains the paper's abstract for DOE-funded
work (national labs, DOE grants) — coverage that OpenAlex/Crossref often
lack for this literature. Coverage is narrow (DOE-funded only) but precise
and free with no rate-limit friction.
"""
from __future__ import annotations

import os
import re

import requests

from ._http import raise_for_rate_limit

SOURCE_NAME = "osti"

_BASE = "https://www.osti.gov/api/v1/records"


def _user_agent() -> str:
    mailto = os.environ.get("OPENALEX_MAILTO", "")
    if mailto:
        return f"wake/0.1 (mailto:{mailto})"
    return "wake/0.1"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _user_agent()})
    return s


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
    # OSTI descriptions sometimes carry light HTML (e.g. <p> tags).
    text = re.sub(r"<[^>]+>", "", desc).strip()
    return text or None


def get_abstract_by_doi(doi: str) -> str | None:
    """Return the OSTI 'description' field for *doi*, or None if unavailable.

    Returns None (not an exception) for 404/no-match — this is a best-effort
    backfill, not a required lookup. Raises on rate limiting or unexpected
    errors so callers can back off.
    """
    norm = _normalize_doi(doi)
    if not norm:
        return None
    resp = _session().get(_BASE, params={"doi": norm}, timeout=15)
    if resp.status_code == 200:
        records = resp.json()
        if isinstance(records, list) and records:
            return _clean_description(records[0].get("description"))
        return None
    if resp.status_code in (404, 410):
        return None
    raise_for_rate_limit(resp, SOURCE_NAME)
    resp.raise_for_status()
    return None
