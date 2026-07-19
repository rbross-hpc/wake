# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
# Adapted from ref-checker/ref_checker/sources/arxiv.py — PDF lookup only.
"""arXiv title search, for finding a freely-downloadable PDF when a citing
work has an arXiv preprint.

arXiv PDFs are always freely downloadable with no bot-blocking or auth
wall, making this a reliable link in wake's PDF acquisition chain whenever
a match exists — but coverage is limited to works that have (or started
as) an arXiv preprint.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests

from ..similarity import title_ratio
from ._http import raise_for_rate_limit

SOURCE_NAME = "arxiv"

_BASE = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}
_USER_AGENT = "wake/0.1"

_MIN_TITLE_SIMILARITY = 0.90


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _USER_AGENT})
    return s


def _extract_arxiv_id(entry_id: str) -> str | None:
    m = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", entry_id)
    if not m:
        return None
    return re.sub(r"v\d+$", "", m.group(1))


def find_pdf_url_by_title(title: str, min_similarity: float = _MIN_TITLE_SIMILARITY) -> str | None:
    """Search arXiv for a preprint matching *title*; return its PDF URL if
    the best match's title similarity meets *min_similarity*, else None.

    Returns None (not an exception) for no-match or below-threshold
    similarity — this is a best-effort lookup, not a required one. Raises
    on rate limiting or unexpected errors so callers can back off.
    """
    title = (title or "").strip()
    if not title:
        return None

    resp = _session().get(
        _BASE,
        params={"search_query": f'ti:"{title}"', "max_results": 5},
        timeout=30,
    )
    raise_for_rate_limit(resp, SOURCE_NAME)
    resp.raise_for_status()

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return None

    entries = root.findall("atom:entry", _NS)
    if not entries:
        return None

    best_sim = 0.0
    best_id: str | None = None
    for entry in entries:
        entry_title = (entry.findtext("atom:title", "", _NS) or "").strip().replace("\n", " ")
        entry_id = entry.findtext("atom:id", "", _NS) or ""
        sim = title_ratio(title, entry_title)
        if sim > best_sim:
            best_sim = sim
            best_id = _extract_arxiv_id(entry_id)

    if best_id is None or best_sim < min_similarity:
        return None

    return f"https://arxiv.org/pdf/{best_id}"
