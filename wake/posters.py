# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Surface likely posters/conference-abstracts for human sign-off
(BACKLOG Theme J item 9).

A `type == "conference-abstract"` work, or a work whose title starts
with `Poster:`/`Abstract:`, is usually a poster reception blurb or a
short abstract for a talk that duplicates a full paper's content
elsewhere in the citing set -- this session's "posters are out" rule
was established ad hoc mid-run, by hand, the same way the two
preprint/published duplicate pairs were caught before `wake dedup`
existed. This module closes that gap the same way: a pure, read-only,
deterministic scan that *surfaces* candidates for a human to look at
one at a time, never a silent auto-drop.

Same trust model as `wake dedup`/`wake exclude` throughout -- this
module never excludes anything itself. `poster_candidates()` only
surfaces; the actual downstream effect (unusable in bake/theme/
narrative/gaps) is `wake exclude`'s, run by the agent on the human's
behalf with `--category poster-or-abstract` once they confirm a
candidate really is a poster/abstract stub worth dropping. If the
human instead decides a flagged candidate should be kept as-is (e.g. a
false positive -- a real paper that happens to be titled "Abstract:
..."), `keep_candidate()` records that so the same candidate isn't
resurfaced by a later scan.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import now_iso
from .seed import work_dir

_TITLE_PREFIXES = ("poster:", "abstract:")
_CONFERENCE_ABSTRACT_TYPE = "conference-abstract"


def _looks_like_poster_or_abstract(work: dict[str, Any]) -> str | None:
    """Return the matched reason string if *work* looks like a poster or
    conference-abstract stub, else None. Two independent signals, either
    is sufficient: OpenAlex's own `type: conference-abstract`, or a
    `Poster:`/`Abstract:` title prefix (checked regardless of type, since
    a mistyped or mis-indexed OpenAlex type shouldn't hide an obvious
    title-prefix case)."""
    title = (work.get("title") or "").strip()
    title_lower = title.lower()
    for prefix in _TITLE_PREFIXES:
        if title_lower.startswith(prefix):
            return f"title starts with {title[:len(prefix)]!r}"
    if work.get("type") == _CONFERENCE_ABSTRACT_TYPE:
        return "type is conference-abstract"
    return None


def _reviewed_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "posters_reviewed.jsonl"


def _kept_ids(seed_id: str, base: Path | None = None) -> set[str]:
    """Citing IDs a human has already looked at and explicitly decided to
    keep -- not resurfaced by a later `poster_candidates()` scan."""
    kept: set[str] = set()
    p = _reviewed_path(seed_id, base)
    if not p.exists():
        return kept
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = entry.get("citing_id")
            if cid and entry.get("decision") == "keep":
                kept.add(cid)
    return kept


def poster_candidates(seed_id: str, *, base: Path | None = None) -> list[dict[str, Any]]:
    """Scan this seed's classified citing works for likely posters or
    conference-abstract stubs. Pure read, no LLM call, deterministic --
    same trust model as `dedup.dedup_candidates()`.

    Already-excluded works (via `wake exclude`, any category) and
    already-reviewed-and-kept works (via `keep_candidate()`) are
    excluded from the results -- a resolved question is never
    re-surfaced.

    Returns candidates sorted by citing_id. Each entry:
    {citing_id, title, year, type, matched_reason}.
    """
    from .classify import load_classified
    from .exclude import is_excluded, load_exclusions

    classified = load_classified(seed_id, base) or []
    exclusions = load_exclusions(seed_id, base)
    kept = _kept_ids(seed_id, base)

    candidates: list[dict[str, Any]] = []
    for work in classified:
        cid = work.get("openalex_id")
        if not cid or cid in kept or is_excluded(cid, exclusions):
            continue
        matched_reason = _looks_like_poster_or_abstract(work)
        if not matched_reason:
            continue
        candidates.append({
            "citing_id": cid,
            "title": work.get("title"),
            "year": work.get("year"),
            "type": work.get("type"),
            "matched_reason": matched_reason,
        })

    candidates.sort(key=lambda c: c["citing_id"])
    return candidates


def keep_candidate(
    seed_id: str,
    citing_id: str,
    *,
    reason: str,
    base: Path | None = None,
) -> dict[str, Any]:
    """Record that a human looked at a `poster_candidates()` entry and
    decided it should be kept as-is (not excluded) -- e.g. a false
    positive, a real paper that happens to be titled "Abstract: ...".
    So the same candidate isn't resurfaced by a later scan.

    No downstream effect beyond that; the work remains fully usable.
    Raises ValueError if *reason* is empty.
    """
    if not reason or not reason.strip():
        raise ValueError("reason must not be empty -- keeping a flagged candidate always needs a stated justification.")

    entry = {"citing_id": citing_id, "decision": "keep", "reason": reason, "reviewed_at": now_iso()}
    p = _reviewed_path(seed_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    return {"ok": True, "reviewed_path": str(p), **entry}
