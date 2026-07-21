# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Verify that a human-supplied PDF matches a citing work's metadata before
copying it into the packet (BACKLOG deferred item D.1).

When a human hunts down a PDF manually (because wake fetch-pdf failed),
there's no validation that the file they found actually matches the citing
work -- it's easy to drop the wrong file (misclicked download, wrong version)
and have wake evidence cheerfully produce a dossier for the wrong paper.

This module provides the metadata-match check used by `wake evidence
--from-pdf`: extract the first few pages of the PDF and run three
heuristic signals against the citing work's known metadata:

  1. Title fuzzy-match -- SequenceMatcher ratio of the normalized citing
     title against the first ~500 characters of the extracted lead text.
     Threshold: ≥0.55 (looser than dedup's 0.85 -- we're matching a title
     fragment inside noisy multi-column extraction, not two clean title
     strings against each other).

  2. Author surname match -- at least one of the citing work's author
     surnames appears in the lead text (case-insensitive, accent-
     normalized, whole-word).

  3. DOI-in-text -- the citing work's DOI appears literally in the lead
     text (when the work has a DOI; this signal is skipped otherwise).

Decision rule: at least TWO of the three signals must fire, AND at least
one of those two must be the title fuzzy-match or the DOI (author surname
alone is not sufficient -- a common co-author could match a completely
different paper from the same group).

The check runs even when --force is passed -- a human override bypasses
the *copy refusal*, but the check result is always logged so there's an
audit trail of what the mismatch looked like.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any


_TITLE_THRESHOLD = 0.55
_LEAD_TEXT_TITLE_CHARS = 800


def _normalize_for_match(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold()


def _surname(full_name: str) -> str:
    """Return the last whitespace-separated token of a name, normalized."""
    parts = full_name.strip().split()
    return _normalize_for_match(parts[-1]) if parts else ""


def _title_signal(citing_title: str | None, lead_text: str) -> float:
    """SequenceMatcher ratio of the normalized citing title against the
    first LEAD_TEXT_TITLE_CHARS characters of the extracted lead text.
    Returns 0.0 if either input is empty."""
    from .similarity import title_ratio
    if not citing_title or not lead_text:
        return 0.0
    window = lead_text[:_LEAD_TEXT_TITLE_CHARS]
    return title_ratio(citing_title, window)


def _author_signal(authors: list[str], lead_text: str) -> bool:
    """True if at least one author surname appears as a whole word in the
    lead text (case-insensitive, accent-normalized)."""
    if not authors or not lead_text:
        return False
    normalized_text = _normalize_for_match(lead_text)
    for name in authors:
        sn = _surname(name)
        if not sn:
            continue
        if re.search(r"\b" + re.escape(sn) + r"\b", normalized_text):
            return True
    return False


def _doi_signal(doi: str | None, lead_text: str) -> bool:
    """True if the citing work's DOI appears literally in the lead text.
    Skipped (returns False) when doi is None or empty."""
    if not doi or not lead_text:
        return False
    normalized_doi = doi.strip().lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    return normalized_doi in lead_text.lower()


def check_pdf_metadata(
    citing_work: dict[str, Any],
    lead_text: str,
) -> dict[str, Any]:
    """Run the three-signal metadata check against extracted lead text.

    Returns a result dict:
    {
      "ok": bool,              # True if the PDF passes the check
      "title_similarity": float,
      "author_matched": bool,
      "doi_found": bool,
      "strong_signals": int,   # how many signals fired
      "message": str,          # human-readable summary
    }

    The check passes ("ok": True) when at least two signals fire AND at
    least one of {title_fuzzy, doi} fires.
    """
    title_sim = _title_signal(citing_work.get("title"), lead_text)
    author_hit = _author_signal(citing_work.get("authors") or [], lead_text)
    doi_hit = _doi_signal(citing_work.get("doi"), lead_text)

    title_ok = title_sim >= _TITLE_THRESHOLD
    strong_signals = sum([title_ok, author_hit, doi_hit])
    anchor_ok = title_ok or doi_hit

    ok = strong_signals >= 2 and anchor_ok

    signals_str = (
        f"title similarity {title_sim:.2f} ({'ok' if title_ok else 'low'}), "
        f"author match {'yes' if author_hit else 'no'}, "
        f"DOI in text {'yes' if doi_hit else 'no'}"
    )
    if ok:
        message = f"PDF metadata check passed ({signals_str})."
    else:
        reasons = []
        if not anchor_ok:
            reasons.append("neither title similarity nor DOI matched")
        elif strong_signals < 2:
            reasons.append(f"only {strong_signals}/3 signal(s) matched (need 2)")
        message = (
            f"PDF metadata check failed: {'; '.join(reasons)}. "
            f"{signals_str}. "
            "Pass --force to override (check result will still be logged)."
        )

    return {
        "ok": ok,
        "title_similarity": round(title_sim, 3),
        "author_matched": author_hit,
        "doi_found": doi_hit,
        "strong_signals": strong_signals,
        "message": message,
    }
