# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
# Extended from ref-checker/ref_checker/sources/openalex.py
"""OpenAlex: seed resolution and cited-by paginated traversal."""
from __future__ import annotations

import os
import re
import time
import warnings
from collections.abc import Iterator
from typing import Any

import requests

from ..errors import OpenAlexError, RateLimited
from ..similarity import title_ratio
from ._http import raise_for_rate_limit

SOURCE_NAME = "openalex"

_BASE = "https://api.openalex.org/works"
_WARNED_MAILTO = False


def _mailto() -> str:
    return os.environ.get("OPENALEX_MAILTO", "").strip()


def _user_agent() -> str:
    global _WARNED_MAILTO
    mailto = _mailto()
    if mailto:
        return f"wake/0.1 (mailto:{mailto})"
    if not _WARNED_MAILTO:
        warnings.warn(
            "[wake] OPENALEX_MAILTO is not set. "
            "Set OPENALEX_MAILTO to your email for polite API access.",
            stacklevel=3,
        )
        _WARNED_MAILTO = True
    return "wake/0.1"


def _polite_params(base: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = dict(base or {})
    mailto = _mailto()
    if mailto:
        params["mailto"] = mailto
    return params


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _user_agent()})
    return s


def _normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"^https?://doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.lower() or None


def _normalize_openalex_id(raw: str) -> str:
    """Canonicalize to bare Wxxxxxxxx form."""
    raw = raw.strip()
    raw = re.sub(r"^https?://openalex\.org/", "", raw, flags=re.IGNORECASE)
    return raw


def _reconstruct_abstract(inv_index: dict | None) -> str | None:
    if not inv_index:
        return None
    words: dict[int, str] = {}
    for word, positions in inv_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words[i] for i in sorted(words)) or None


def _summarize_work(work: dict) -> dict[str, Any]:
    """Convert a raw OpenAlex work dict to a normalized summary."""
    loc = work.get("primary_location") or {}
    source = loc.get("source") or {}
    doi = _normalize_doi(work.get("doi"))

    # authors and author_ids are built from the same loop, index-aligned
    # (author_ids[i] is the OpenAlex author ID for authors[i], or "" if
    # that authorship entry had no id) -- needed for author-overlap
    # detection (BACKLOG Theme E: is a citing work by the seed's own team?
    # ID intersection, not name matching, since display names collide).
    authors: list[str] = []
    author_ids: list[str] = []
    for a in work.get("authorships", []):
        author = a.get("author") or {}
        name = author.get("display_name") or ""
        if not name:
            continue
        authors.append(name)
        aid = author.get("id") or ""
        author_ids.append(_normalize_openalex_id(aid) if aid else "")

    openalex_id = work.get("id", "")
    if openalex_id:
        openalex_id = _normalize_openalex_id(openalex_id)

    topics = []
    for t in work.get("topics", [])[:3]:
        field = (t.get("field") or {}).get("display_name")
        if field and field not in topics:
            topics.append(field)

    return {
        "openalex_id": openalex_id,
        "title": work.get("display_name"),
        "authors": authors,
        "author_ids": author_ids,
        "year": work.get("publication_year"),
        "venue": source.get("display_name"),
        "venue_type": source.get("type"),
        "doi": doi,
        "url": loc.get("landing_page_url") or work.get("id"),
        "cited_by_count": work.get("cited_by_count", 0),
        "type": work.get("type"),
        "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
        "topics": topics,
    }


def get_work_by_doi(doi: str) -> dict | None:
    """Fetch a single work by DOI; return normalized summary or None."""
    norm = _normalize_doi(doi)
    if not norm:
        return None
    sess = _session()
    resp = sess.get(f"{_BASE}/doi:{norm}", params=_polite_params(), timeout=30)
    if resp.status_code == 200:
        return _summarize_work(resp.json())
    if resp.status_code in (404, 410):
        return None
    raise_for_rate_limit(resp, SOURCE_NAME)
    resp.raise_for_status()
    return None


def get_work_by_openalex_id(openalex_id: str) -> dict | None:
    """Fetch a single work by OpenAlex ID (W-prefixed or full URL)."""
    bare = _normalize_openalex_id(openalex_id)
    sess = _session()
    resp = sess.get(f"{_BASE}/{bare}", params=_polite_params(), timeout=30)
    if resp.status_code == 200:
        return _summarize_work(resp.json())
    if resp.status_code in (404, 410):
        return None
    raise_for_rate_limit(resp, SOURCE_NAME)
    resp.raise_for_status()
    return None


def get_work_by_arxiv_id(arxiv_id: str) -> dict | None:
    """Fetch a work by arXiv ID (converts to DOI)."""
    bare = re.sub(r"v\d+$", "", arxiv_id.strip())
    return get_work_by_doi(f"10.48550/arXiv.{bare}")


def search_work_by_title(title: str, min_ratio: float = 0.85) -> dict | None:
    """Search OpenAlex by title; return best match above min_ratio or None."""
    params = _polite_params({"search": title, "per-page": 5})
    sess = _session()
    resp = sess.get(_BASE, params=params, timeout=30)
    if resp.status_code != 200:
        if resp.status_code == 404:
            return None
        raise_for_rate_limit(resp, SOURCE_NAME)
        resp.raise_for_status()
        return None
    results = resp.json().get("results", [])
    if not results:
        return None
    cands = [(title_ratio(title, w.get("display_name")), w) for w in results]
    best_sim, best_work = max(cands, key=lambda x: x[0])
    if best_sim < min_ratio:
        return None
    return _summarize_work(best_work)


def iter_citing_works(
    openalex_id: str,
    *,
    per_page: int = 200,
    rate_limit_s: float = 1.0,
    min_year: int | None = None,
) -> Iterator[dict]:
    """Yield normalized summaries of all works citing *openalex_id*.

    Uses OpenAlex cursor pagination (filter=cites:<id>).
    Respects *rate_limit_s* between pages.
    Raises :class:`OpenAlexError` on unexpected API errors.
    """
    bare = _normalize_openalex_id(openalex_id)
    sess = _session()
    cursor = "*"
    page_num = 0

    while cursor:
        params = _polite_params({
            "filter": f"cites:{bare}",
            "per-page": per_page,
            "cursor": cursor,
            "select": (
                "id,display_name,doi,publication_year,cited_by_count,"
                "primary_location,authorships,abstract_inverted_index,"
                "type,topics"
            ),
        })
        if min_year is not None:
            params["filter"] += f",publication_year:>{min_year - 1}"

        try:
            resp = sess.get(_BASE, params=params, timeout=60)
        except requests.RequestException as exc:
            raise OpenAlexError(f"Request failed: {exc}") from exc

        if resp.status_code == 429:
            raise_for_rate_limit(resp, SOURCE_NAME)

        if resp.status_code != 200:
            raise OpenAlexError(
                f"OpenAlex returned {resp.status_code} for cites:{bare} (page {page_num + 1})"
            )

        data = resp.json()
        results = data.get("results", [])
        meta = data.get("meta", {})

        for work in results:
            yield _summarize_work(work)

        cursor = meta.get("next_cursor")
        page_num += 1

        if cursor:
            time.sleep(rate_limit_s)


def count_citing_works(openalex_id: str) -> int:
    """Return the total number of citing works without fetching them all."""
    bare = _normalize_openalex_id(openalex_id)
    sess = _session()
    params = _polite_params({
        "filter": f"cites:{bare}",
        "per-page": 1,
        "select": "id",
    })
    resp = sess.get(_BASE, params=params, timeout=30)
    if resp.status_code != 200:
        raise_for_rate_limit(resp, SOURCE_NAME)
        resp.raise_for_status()
    return resp.json().get("meta", {}).get("count", 0)
