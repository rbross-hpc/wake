# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Author-overlap detection (BACKLOG Theme E).

Answers a question distinct from the relationship classes themselves:
*is this citing work by the seed's own team, or an independent third
party?* `extends` already captures "directly extends the seed's method"
regardless of authorship -- this module adds an orthogonal tag on top:

  extends + author_overlap: true  -> the original team's own follow-on paper
  extends + author_overlap: false -> an independent third-party extension

Pure, deterministic, no LLM call -- computed from OpenAlex author IDs
already preserved on both the seed and citing work dicts by
sources/openalex.py::_summarize_work(). ID-set intersection, not name
matching, since display names collide across authors (and OpenAlex
sometimes formats the same author's name inconsistently across papers).
"""
from __future__ import annotations

from typing import Any


def _author_id_set(work: dict[str, Any]) -> set[str]:
    return {aid for aid in work.get("author_ids", []) or [] if aid}


def compute_overlap(seed_work: dict[str, Any], citing_work: dict[str, Any]) -> dict[str, Any]:
    """Return {"author_overlap": bool, "overlapping_authors": [name, ...]}.

    overlapping_authors lists the citing work's own author names (in its
    original author order) for every author ID it shares with the seed
    work. Empty/missing author_ids on either side never counts as an
    overlap (two works both lacking author IDs are not "the same team").
    """
    seed_ids = _author_id_set(seed_work)
    if not seed_ids:
        return {"author_overlap": False, "overlapping_authors": []}

    citing_authors = citing_work.get("authors", []) or []
    citing_ids = citing_work.get("author_ids", []) or []

    overlapping_authors: list[str] = []
    for name, aid in zip(citing_authors, citing_ids):
        if aid and aid in seed_ids and name not in overlapping_authors:
            overlapping_authors.append(name)

    return {
        "author_overlap": bool(overlapping_authors),
        "overlapping_authors": overlapping_authors,
    }
