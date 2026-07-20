# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Duplicate citing-work detection and human-confirmed merging.

Three duplicate shapes seen or expected in a citing set: a preprint and
its later-published version (2 caught by hand mid-session via fuzzy
title matching before this module existed), a workshop paper and its
expanded journal version, and the same paper independently
double-published (e.g. re-indexed under two OpenAlex IDs). Left
unmerged, each inflates reach metrics (double-counted in "how many
distinct works cite this"), can end up in two different themes as if
they were independent evidence, and can be cited twice from a
narrative as if two sources agreed rather than one.

Same trust model as `wake theme`/`wake override` throughout: this
module never merges anything on its own. `dedup_candidates()` is a
pure, deterministic heuristic scan (title similarity + author-ID
overlap + a preprint/venue signal) that *surfaces* likely pairs for a
human to look at, one at a time -- never auto-applied. Only
`confirm_duplicate()`, run by the agent after explicit human sign-off,
persists a decision, and only for that specific pair.

Once confirmed, a duplicate ID is treated as unusable everywhere else
in the packet -- the same way an excluded work would be: `wake bake`
folds it out of reach metrics (kept once, under the canonical ID),
`wake theme create` refuses to cite it (pointing at the canonical
instead), and `wake narrative` reference validation refuses it too.
`reject_candidate()` records the opposite decision (a human looked at
the pair and judged them genuinely distinct works) so the same
false-positive pair isn't resurfaced by a later `dedup_candidates()`
call.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import atomic_write_text, now_iso
from .seed import work_dir
from .similarity import title_ratio

_PREPRINT_TYPES = {"preprint"}
_TITLE_SIMILARITY_THRESHOLD = 0.85


def duplicates_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "duplicates.jsonl"


def load_duplicates(seed_id: str, base: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load confirmed duplicate decisions, keyed by `duplicate_id`.

    Later entries for the same duplicate_id win (append-only log; last
    write wins) -- same convention as `report.load_overrides`.
    """
    p = duplicates_path(seed_id, base)
    if not p.exists():
        return {}
    entries: dict[str, dict[str, Any]] = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            did = entry.get("duplicate_id")
            if did:
                entries[did] = entry
    return entries


def canonical_id_for(citing_id: str, duplicates: dict[str, dict[str, Any]]) -> str:
    """Resolve *citing_id* to its canonical ID if it's a confirmed
    duplicate of something else, else return it unchanged. Duplicates
    are never chained (a duplicate's canonical is never itself another
    duplicate) -- `confirm_duplicate()` enforces this at write time."""
    entry = duplicates.get(citing_id)
    return entry["canonical_id"] if entry else citing_id


def _reviewed_pairs(seed_id: str, base: Path | None = None) -> set[frozenset[str]]:
    """Every pair already decided one way or the other (confirmed
    duplicate, or explicitly rejected as not-a-duplicate) -- excluded
    from future `dedup_candidates()` scans so a resolved question is
    never re-asked."""
    pairs: set[frozenset[str]] = set()
    dup_path = duplicates_path(seed_id, base)
    if dup_path.exists():
        with open(dup_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                a, b = entry.get("duplicate_id"), entry.get("canonical_id")
                if a and b:
                    pairs.add(frozenset((a, b)))

    rejected_path = _rejected_path(seed_id, base)
    if rejected_path.exists():
        with open(rejected_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                a, b = entry.get("id_a"), entry.get("id_b")
                if a and b:
                    pairs.add(frozenset((a, b)))
    return pairs


def _rejected_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "dedup_rejected.jsonl"


def _has_preprint_signal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True if exactly one side looks like a preprint/workshop version of
    the other: one is OpenAlex `type: preprint`, or one has no
    venue/venue_type at all while the other has a real journal/conference
    venue -- a common signature for an unindexed preprint or workshop
    paper next to its later, properly-venued publication."""
    a_preprint = a.get("type") in _PREPRINT_TYPES or (not a.get("venue") and b.get("venue"))
    b_preprint = b.get("type") in _PREPRINT_TYPES or (not b.get("venue") and a.get("venue"))
    return a_preprint != b_preprint  # exactly one side, not both/neither


def _author_id_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_ids = {aid for aid in a.get("author_ids", []) or [] if aid}
    b_ids = {aid for aid in b.get("author_ids", []) or [] if aid}
    if not a_ids or not b_ids:
        return False
    return bool(a_ids & b_ids)


def dedup_candidates(
    seed_id: str, *, base: Path | None = None, min_title_similarity: float = _TITLE_SIMILARITY_THRESHOLD,
) -> list[dict[str, Any]]:
    """Scan this seed's classified citing works for likely-duplicate
    pairs: high title similarity (Unicode-normalized SequenceMatcher
    ratio, same metric `wake/similarity.py` uses elsewhere) plus at
    least one shared OpenAlex author ID, always required together --
    title similarity alone is not enough (two distinct papers can share
    a generic title; two workshop papers by the same group commonly do
    not share exact wording). A preprint/venue signal on one side is
    reported (`likely_kind`) but not required, so a same-title,
    same-author double-publication with two full journal venues is
    still caught, just labeled differently.

    Pure read, no LLM call, deterministic -- same trust model as
    `author_overlap.py`. Never merges anything; a human reviews each
    candidate one at a time and the agent calls `confirm_duplicate()`
    or `reject_candidate()` on their behalf.

    Pairs already decided (confirmed duplicate or explicitly rejected)
    are excluded -- a resolved question is never re-surfaced.

    Returns candidates sorted by similarity, highest first. Each entry:
    {citing_id_a, citing_id_b, title_similarity, likely_kind, overlapping_authors}.
    """
    from .classify import load_classified

    classified = load_classified(seed_id, base) or []
    reviewed = _reviewed_pairs(seed_id, base)

    candidates: list[dict[str, Any]] = []
    n = len(classified)
    for i in range(n):
        a = classified[i]
        aid = a.get("openalex_id")
        if not aid:
            continue
        for j in range(i + 1, n):
            b = classified[j]
            bid = b.get("openalex_id")
            if not bid or frozenset((aid, bid)) in reviewed:
                continue

            sim = title_ratio(a.get("title"), b.get("title"))
            if sim < min_title_similarity:
                continue
            if not _author_id_overlap(a, b):
                continue

            preprint_signal = _has_preprint_signal(a, b)
            likely_kind = "preprint-vs-published" if preprint_signal else "possible-double-publication"

            a_ids = {aid_ for aid_ in a.get("author_ids", []) or [] if aid_}
            b_ids = {aid_ for aid_ in b.get("author_ids", []) or [] if aid_}
            overlapping_ids = a_ids & b_ids
            overlapping_authors = [
                name for name, oid in zip(a.get("authors", []) or [], a.get("author_ids", []) or [])
                if oid in overlapping_ids
            ]

            candidates.append({
                "citing_id_a": aid,
                "title_a": a.get("title"),
                "year_a": a.get("year"),
                "type_a": a.get("type"),
                "venue_a": a.get("venue"),
                "citing_id_b": bid,
                "title_b": b.get("title"),
                "year_b": b.get("year"),
                "type_b": b.get("type"),
                "venue_b": b.get("venue"),
                "title_similarity": round(sim, 3),
                "likely_kind": likely_kind,
                "overlapping_authors": overlapping_authors,
            })

    candidates.sort(key=lambda c: c["title_similarity"], reverse=True)
    return candidates


def confirm_duplicate(
    seed_id: str,
    duplicate_id: str,
    canonical_id: str,
    *,
    reason: str = "",
    base: Path | None = None,
) -> dict[str, Any]:
    """Record a human-confirmed duplicate decision: *duplicate_id* is the
    same work as *canonical_id* and should be treated as unusable
    everywhere else in the packet from now on -- `wake bake` excludes it
    from reach metrics (the work is still counted, once, under
    *canonical_id*), `wake theme create` refuses to cite it directly,
    and `wake narrative` reference validation refuses it too, all
    pointing back at *canonical_id* instead.

    Run by the agent on the human's behalf after explicit sign-off --
    never a bulk operation, one pair at a time, same "human confirms one
    at a time" rule used everywhere else in this codebase.

    Raises ValueError if duplicate_id == canonical_id, or if
    canonical_id is itself already recorded as someone else's duplicate
    (duplicates are never chained -- point every reference straight at
    the real canonical work).
    """
    if duplicate_id == canonical_id:
        raise ValueError("duplicate_id and canonical_id must be different works.")

    existing = load_duplicates(seed_id, base)
    if canonical_id in existing:
        raise ValueError(
            f"{canonical_id!r} is itself already recorded as a duplicate of "
            f"{existing[canonical_id]['canonical_id']!r} -- point this decision at that "
            "work instead so duplicates never chain."
        )

    entry = {
        "duplicate_id": duplicate_id,
        "canonical_id": canonical_id,
        "reason": reason,
        "confirmed_at": now_iso(),
    }
    p = duplicates_path(seed_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    return {"ok": True, "duplicates_path": str(p), **entry}


def reject_candidate(
    seed_id: str,
    id_a: str,
    id_b: str,
    *,
    reason: str = "",
    base: Path | None = None,
) -> dict[str, Any]:
    """Record that a human looked at a `dedup_candidates()` pair and
    judged them genuinely distinct works, not a duplicate -- so the same
    pair isn't resurfaced by a later scan. No downstream effect beyond
    that; both works remain fully usable."""
    if id_a == id_b:
        raise ValueError("id_a and id_b must be different works.")

    entry = {"id_a": id_a, "id_b": id_b, "reason": reason, "rejected_at": now_iso()}
    p = _rejected_path(seed_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    return {"ok": True, "rejected_path": str(p), **entry}
