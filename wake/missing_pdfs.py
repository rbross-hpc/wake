# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Surface classified citing works with no cached PDF and known fetch history
(BACKLOG -- deferred item A).

`wake missing-pdfs <seed>` is a pure read-only report, same trust model as
`wake gaps` and `wake theme queue`. It complements `wake gaps` (which is
about *abstracts*) by surfacing a different gap: classified works that still
need a full PDF for `wake evidence` to read, and for which the automatic
fetch chain was already tried and came up empty.

Three per-work states are reported:
  - never-attempted -- no pdf_fetched or pdf_fetch_failed event in the log
    for this work; `wake fetch-pdf` has never been tried.
  - exhausted -- a pdf_fetch_failed event exists in the log; the automatic
    source chain ran and couldn't find anything.  The detail field carries
    which sources were tried.
  - fetched-but-gone -- a pdf_fetched event exists in the log (the PDF was
    acquired at some point) but the cached file is no longer on disk, e.g.
    it was manually deleted or the work directory was moved.

Only works without a currently-cached PDF are surfaced; works where
pdfs/<citing-id>.pdf exists are silently excluded (they already have what
`wake evidence` needs).  Works that are explicitly excluded (wake exclude),
confirmed duplicates, or already have a completed evidence dossier are also
filtered out -- there's no point chasing a PDF for a work that's excluded or
already verified.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .seed import work_dir

_LOG_LINE_RE = re.compile(
    r"^- (?P<ts>\S+) — (?P<event>\S+) — (?P<ref>\S+?)(?:\s+— (?P<detail>.+))?$"
)

_PDF_EVENTS = {"pdf_fetched", "pdf_fetch_failed"}


def _parse_log_events(seed_id: str, base: Path | None) -> dict[str, dict[str, Any]]:
    """Parse evidence/log.md for pdf_fetched and pdf_fetch_failed events.

    Returns a dict keyed by citing_id; value is the most-recent matching
    event dict: {event, timestamp, detail}.
    """
    from .evidence_wiki import log_path
    p = log_path(seed_id, base)
    if not p.exists():
        return {}

    events: dict[str, dict[str, Any]] = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            m = _LOG_LINE_RE.match(line)
            if not m:
                continue
            event = m.group("event")
            if event not in _PDF_EVENTS:
                continue
            ref = m.group("ref")
            citing_id = ref.lstrip("[").split("]")[0]
            events[citing_id] = {
                "event": event,
                "timestamp": m.group("ts"),
                "detail": m.group("detail") or "",
            }
    return events


def list_missing_pdfs(
    seed_id: str,
    *,
    base: Path | None = None,
    min_cited_by_count: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return classified citing works with no cached PDF, ranked by
    cited_by_count (highest first).

    Each entry: {citing_id, title, year, cited_by_count, doi,
                 fetch_state, last_attempted, sources_tried}.

    fetch_state is one of:
      "never-attempted"  -- wake fetch-pdf has never been run for this work
      "exhausted"        -- tried and all sources failed
      "fetched-but-gone" -- was acquired once but the file is no longer cached

    Filters applied:
      - Works with a cached PDF at pdfs/<citing-id>.pdf are excluded.
      - Works that are excluded (wake exclude), confirmed duplicates, or
        already have a completed evidence dossier are excluded.
      - If min_cited_by_count is given, works below that threshold are excluded.
      - limit caps the result count (applied after ranking).
    """
    from .classify import load_classified
    from .dedup import load_duplicates
    from .evidence import dossier_json_path
    from .exclude import is_excluded, load_exclusions
    from .pdf_fetch import pdf_path as _pdf_path

    classified = load_classified(seed_id, base) or []
    exclusions = load_exclusions(seed_id, base)
    duplicates = load_duplicates(seed_id, base)
    log_events = _parse_log_events(seed_id, base)

    results: list[dict[str, Any]] = []
    for work in classified:
        cid = work.get("openalex_id")
        if not cid:
            continue

        if is_excluded(cid, exclusions):
            continue
        if cid in duplicates:
            continue
        if dossier_json_path(seed_id, cid, base).exists():
            continue

        cached = _pdf_path(seed_id, cid, base).exists()
        if cached:
            continue

        cited_by = work.get("cited_by_count") or 0
        if min_cited_by_count is not None and cited_by < min_cited_by_count:
            continue

        ev = log_events.get(cid)
        if ev is None:
            fetch_state = "never-attempted"
            last_attempted = None
            sources_tried: list[str] = []
        elif ev["event"] == "pdf_fetched":
            fetch_state = "fetched-but-gone"
            last_attempted = ev["timestamp"]
            sources_tried = []
        else:
            fetch_state = "exhausted"
            last_attempted = ev["timestamp"]
            detail = ev["detail"]
            tried_part = detail.removeprefix("tried: ")
            sources_tried = [s.strip() for s in tried_part.split(",") if s.strip() and s.strip() != "none applicable"]

        results.append({
            "citing_id": cid,
            "title": work.get("title"),
            "year": work.get("year"),
            "cited_by_count": cited_by,
            "doi": work.get("doi"),
            "fetch_state": fetch_state,
            "last_attempted": last_attempted,
            "sources_tried": sources_tried,
        })

    results.sort(key=lambda r: -r["cited_by_count"])
    if limit is not None:
        results = results[:limit]
    return results
