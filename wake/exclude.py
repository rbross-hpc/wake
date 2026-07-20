# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Explicit, permanent exclusion of a citing work (BACKLOG Theme J item 10).

A citing work judged not actually about the seed -- e.g. a
`background-mention` where the seed appears only in a bibliography, a
poster/conference-abstract that duplicates a full paper's content, or a
work the human simply doesn't want counted -- previously had no way to
be marked "considered and deliberately out of scope" beyond an
`override` to `background-mention`. That leaves the work still fully
usable: nothing stops a later theme or narrative section from citing it,
and nothing stops `wake gaps`/`wake theme queue` from surfacing it again.

`wake exclude` closes that gap with a first-class, explicit state, same
trust model as `wake dedup`/`wake override` throughout -- this module
never decides that a work should be excluded; it only persists a human's
decision, one work at a time, with a required reason.

Once excluded, a citing work is unusable everywhere else in the packet:
`wake bake` drops it from reach metrics, `wake theme create` refuses to
cite it, `wake narrative` reference validation refuses it in a
`[ref:...]` marker, and `wake gaps`/`wake theme queue` stop surfacing
it. Undoing an exclusion is a separate, explicit `unexclude_work()`
call with its own justification -- never implicit, never a side effect
of some other command.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import now_iso
from .seed import work_dir

EXCLUSION_REASONS = [
    "not-about-seed",
    "poster-or-abstract",
    "irrelevant",
    "other",
]


def exclusions_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "exclusions.jsonl"


def load_exclusions(seed_id: str, base: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load exclusion decisions, keyed by citing ID. Later entries for
    the same ID win (append-only log; last write wins) -- same
    convention as `report.load_overrides`/`dedup.load_duplicates`. A
    work present here with `"excluded": false` (written by
    `unexclude_work`) is *not* currently excluded -- callers should
    check the `excluded` flag, not just key presence.
    """
    p = exclusions_path(seed_id, base)
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
            cid = entry.get("citing_id")
            if cid:
                entries[cid] = entry
    return entries


def is_excluded(citing_id: str, exclusions: dict[str, dict[str, Any]]) -> bool:
    entry = exclusions.get(citing_id)
    return bool(entry and entry.get("excluded", True))


def exclude_work(
    seed_id: str,
    citing_id: str,
    *,
    reason: str,
    category: str = "other",
    base: Path | None = None,
) -> dict[str, Any]:
    """Record a human-confirmed exclusion for one citing work. Always
    run by the agent on the human's behalf after explicit sign-off, one
    work at a time -- never a bulk operation, same "human confirms one
    at a time" rule used everywhere else in this codebase.

    *reason* is required and free-text (the specific justification);
    *category* is one of `EXCLUSION_REASONS`, for at-a-glance grouping
    (e.g. when reviewing `exclusions.jsonl` later). Raises ValueError if
    *reason* is empty or *category* isn't recognized.
    """
    if not reason or not reason.strip():
        raise ValueError("reason must not be empty -- an exclusion always needs a stated justification.")
    if category not in EXCLUSION_REASONS:
        raise ValueError(f"category must be one of {EXCLUSION_REASONS}, got {category!r}.")

    entry = {
        "citing_id": citing_id,
        "excluded": True,
        "reason": reason,
        "category": category,
        "excluded_at": now_iso(),
    }
    p = exclusions_path(seed_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    return {"ok": True, "exclusions_path": str(p), **entry}


def unexclude_work(
    seed_id: str,
    citing_id: str,
    *,
    reason: str,
    base: Path | None = None,
) -> dict[str, Any]:
    """Reverse a prior exclusion -- a separate, explicit action with its
    own required justification, never an implicit side effect of some
    other command. Appends an `"excluded": false` entry (last-write-wins
    resolution means this supersedes the prior exclusion for this ID).

    Raises ValueError if *reason* is empty, or if *citing_id* was never
    excluded in the first place (nothing to undo).
    """
    if not reason or not reason.strip():
        raise ValueError("reason must not be empty -- an unexclude always needs a stated justification.")

    existing = load_exclusions(seed_id, base)
    if not is_excluded(citing_id, existing):
        raise ValueError(f"{citing_id!r} is not currently excluded -- nothing to undo.")

    entry = {
        "citing_id": citing_id,
        "excluded": False,
        "reason": reason,
        "excluded_at": now_iso(),
    }
    p = exclusions_path(seed_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    return {"ok": True, "exclusions_path": str(p), **entry}
