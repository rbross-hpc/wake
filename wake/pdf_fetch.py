# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""PDF acquisition: try a chain of open-access sources, download the first
hit, or return human-actionable links if every source comes up empty.

Standalone, reusable primitive — not just an internal helper for evidence
dossiers (wake evidence, BACKLOG Theme A2). Also usable to streamline the
existing `wake fill-abstract --from-pdf` workflow by skipping the manual
download step when the chain succeeds.

Source chain (config: pdf_fetch.sources, default order):
  1. OSTI            — direct 'fulltext' link, DOE-funded work, no auth wall
  2. Semantic Scholar — openAccessPdf.url (often a repository copy)
  3. Unpaywall        — best_oa_location PDF URL (frequently 403s on
                        publisher sites; still worth attempting)
  4. Springer         — predictable link.springer.com/content/pdf/<DOI>.pdf
                        URL for Springer DOIs (10.1007/...); no API call,
                        just a direct download attempt. Frequently succeeds
                        for older LNCS conference chapters that Unpaywall/
                        OSTI/S2 don't index, and is a no-op (returns None
                        immediately) for non-Springer DOIs.
  5. arXiv            — title-search match, always freely downloadable
  6. CORE.ac.uk       — optional, requires CORE_API_KEY, silently skipped
                        if unset

Mostly API-based (Springer is a direct, predictable URL rather than an
API lookup); no scraping of publisher landing pages, no sci-hub-style
sources. On success, saves to wake-out/<seed>/pdfs/<citing-id>.pdf for
citing works, or wake-out/<seed>/seed.pdf for the seed itself.
"""
from __future__ import annotations

import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

import requests

from . import config
from .seed import work_dir
from .sources import arxiv_fetch, core, osti, semanticscholar, springer, unpaywall


def _cfg() -> dict[str, Any]:
    return config.pdf_fetch_cfg()


def pdfs_dir(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "pdfs"


def pdf_path(seed_id: str, citing_id: str, base: Path | None = None) -> Path:
    return pdfs_dir(seed_id, base) / f"{citing_id}.pdf"


def seed_pdf_path(seed_id: str, base: Path | None = None) -> Path:
    """Path for the seed paper's own PDF, distinct from pdfs/ which is
    exclusively citing-work PDFs."""
    return work_dir(seed_id, base) / "seed.pdf"


def _source_func(name: str) -> Callable[[str], str | None] | None:
    """Look up a URL-finding function by name, at call time (not import
    time) so tests can monkeypatch e.g. wake.pdf_fetch.osti and have it
    take effect."""
    if name == "osti":
        return osti.get_fulltext_pdf_url_by_doi
    if name == "semanticscholar":
        return semanticscholar.get_open_access_pdf_url_by_doi
    if name == "unpaywall":
        return unpaywall.get_oa_pdf_url_by_doi
    if name == "springer":
        return springer.get_fulltext_pdf_url_by_doi
    if name == "arxiv":
        return None  # handled specially below (needs title, not doi)
    if name == "core":
        return core.get_oa_pdf_url_by_doi
    return None


def _looks_like_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def _download(url: str, dest: Path, *, timeout: int, min_bytes: int) -> bool:
    """Download *url* to *dest*. Returns True on success (valid PDF saved),
    False on any failure (HTTP error, non-PDF content, too-small file) —
    never raises, since a failed download for one source should just fall
    through to the next in the chain.
    """
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "wake/0.1 (mailto:pdf-fetch)"},
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException:
        return False

    if resp.status_code != 200:
        return False

    data = resp.content
    if len(data) < min_bytes:
        return False
    if not _looks_like_pdf(data):
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def fallback_links(doi: str | None, title: str | None) -> dict[str, str]:
    """Return human-actionable links to try manually when every automatic
    source fails. Always includes a Google Scholar search by title (if
    available) — per user request, so a human always has that option even
    when the DOI-based sources are exhausted.
    """
    links: dict[str, str] = {}
    if doi:
        links["unpaywall"] = f"https://unpaywall.org/{doi}"
        links["publisher_doi"] = f"https://doi.org/{doi}"
        links["core_search"] = f"https://core.ac.uk/search?q=doi%3A%22{urllib.parse.quote(doi)}%22"
    if title:
        links["google_scholar"] = (
            "https://scholar.google.com/scholar?q=" + urllib.parse.quote(title)
        )
    return links


def _fetch_pdf_to(
    dest: Path,
    *,
    doi: str | None,
    title: str | None,
    log_seed_id: str,
    log_citing_id: str,
    log_seed_title: str | None,
    log_event_success: str,
    log_event_failure: str,
    base: Path | None,
    verbose: bool,
) -> dict[str, Any]:
    """Core download loop shared by fetch_pdf (citing works) and
    fetch_seed_pdf (the seed paper itself). Tries the configured source
    chain and writes the result to *dest*. Returns a result dict.

    *log_citing_id* is the ID used in evidence/log.md entries —
    for citing-work fetches it's the citing work's openalex_id; for seed
    fetches it's the seed's own openalex_id, keeping them distinguishable
    in the log by the event name.
    """
    cfg = _cfg()
    sources = cfg.get("sources", ["osti", "semanticscholar", "unpaywall", "springer", "arxiv", "core"])
    rate_limits = cfg.get("rate_limit_s", {})
    timeout = cfg.get("download_timeout_s", 30)
    min_bytes = cfg.get("min_valid_pdf_bytes", 2048)

    tried: list[str] = []

    for source_name in sources:
        if source_name == "arxiv":
            if not title:
                continue
        elif source_name == "core":
            if not core.is_enabled() or not doi:
                continue
        else:
            func = _source_func(source_name)
            if func is None or not doi:
                continue

        tried.append(source_name)
        try:
            if source_name == "arxiv":
                url = arxiv_fetch.find_pdf_url_by_title(title)
            elif source_name == "core":
                url = core.get_oa_pdf_url_by_doi(doi)
            else:
                url = func(doi)
        except Exception as exc:
            if verbose:
                print(f"[wake]   WARN: {source_name} lookup failed: {exc}", file=sys.stderr)
            url = None
        finally:
            delay = rate_limits.get(source_name, 1.0)
            if delay > 0:
                time.sleep(delay)

        if not url:
            continue

        if verbose:
            print(f"[wake]   Trying {source_name}: {url}", file=sys.stderr)

        if _download(url, dest, timeout=timeout, min_bytes=min_bytes):
            if verbose:
                print(f"[wake] PDF acquired via {source_name} -> {dest}", file=sys.stderr)
            _log_fetch(log_seed_id, log_citing_id, event=log_event_success,
                       detail=f"via {source_name}", seed_title=log_seed_title, base=base)
            return {"ok": True, "path": str(dest), "source": source_name, "url": url}

        if verbose:
            print(f"[wake]   {source_name} URL did not yield a valid PDF, trying next source", file=sys.stderr)

    if verbose:
        print(f"[wake] No PDF acquired automatically (tried: {', '.join(tried) or 'none'}).", file=sys.stderr)

    tried_str = ", ".join(tried) if tried else "none applicable"
    _log_fetch(log_seed_id, log_citing_id, event=log_event_failure,
               detail=f"tried: {tried_str}", seed_title=log_seed_title, base=base)
    return {
        "ok": False,
        "tried": tried,
        "fallback_links": fallback_links(doi, title),
    }


def fetch_pdf(
    seed_id: str,
    citing_id: str,
    *,
    doi: str | None,
    title: str | None = None,
    seed_title: str | None = None,
    base: Path | None = None,
    force: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Try the configured source chain to acquire a PDF for a citing work.

    Returns a result dict:
      {"ok": True, "path": "<local path>", "source": "<source name>"}
    or
      {"ok": False, "tried": [...], "fallback_links": {...}}

    If a PDF is already cached at the destination path and force=False,
    returns immediately without making any network calls.

    Every real attempt (not a cache hit) is logged to evidence/log.md via
    `evidence_wiki.append_log_entry` so `wake missing-pdfs` can later
    reconstruct which sources were tried and whether any succeeded.
    Cache hits are not logged (they are not new attempts).
    """
    dest = pdf_path(seed_id, citing_id, base)

    if not force and dest.exists():
        if verbose:
            print(f"[wake] PDF already cached: {dest}", file=sys.stderr)
        return {"ok": True, "path": str(dest), "source": "cache"}

    return _fetch_pdf_to(
        dest,
        doi=doi,
        title=title,
        log_seed_id=seed_id,
        log_citing_id=citing_id,
        log_seed_title=seed_title,
        log_event_success="pdf_fetched",
        log_event_failure="pdf_fetch_failed",
        base=base,
        verbose=verbose,
    )


def fetch_seed_pdf(
    seed_work: dict,
    *,
    base: Path | None = None,
    force: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Try the configured source chain to acquire the seed paper's own PDF.

    Same chain as fetch_pdf for citing works. Stores at
    wake-out/<seed>/seed.pdf (distinct from pdfs/ which is citing works
    only). Returns the same result shape as fetch_pdf.

    Log events use seed_pdf_fetched / seed_pdf_fetch_failed so they are
    distinguishable from citing-work fetch events in evidence/log.md.
    """
    seed_id = seed_work["openalex_id"]
    dest = seed_pdf_path(seed_id, base)

    if not force and dest.exists():
        if verbose:
            print(f"[wake] Seed PDF already cached: {dest}", file=sys.stderr)
        return {"ok": True, "path": str(dest), "source": "cache"}

    return _fetch_pdf_to(
        dest,
        doi=seed_work.get("doi"),
        title=seed_work.get("title"),
        log_seed_id=seed_id,
        log_citing_id=seed_id,
        log_seed_title=seed_work.get("title"),
        log_event_success="seed_pdf_fetched",
        log_event_failure="seed_pdf_fetch_failed",
        base=base,
        verbose=verbose,
    )


def _log_fetch(
    seed_id: str,
    citing_id: str,
    *,
    event: str,
    detail: str,
    seed_title: str | None,
    base: Path | None,
) -> None:
    try:
        from .evidence_wiki import append_log_entry
        append_log_entry(
            seed_id, event=event, citing_id=citing_id,
            detail=detail, seed_title=seed_title, base=base,
        )
    except Exception:
        pass
