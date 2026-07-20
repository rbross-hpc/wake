# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""First-class undo for a mistaken verification (BACKLOG Theme J item 11).

This session needed exactly this when an agent misread a bulk go-ahead
and auto-verified 13 works without real human sign-off behind them --
recovery was a manual `overrides.jsonl` backup-and-restore rather than a
real command. `wake unverify` closes that gap.

Same trust model as `wake exclude`/`wake dedup` throughout: this module
never decides that a verification was a mistake, it only reverses one a
human has already flagged as such. Unverifying is a separate, explicit
action with its own reason -- never an implicit side effect of any other
command.

Reversing a verification means:
  - removing the citing work's entry from `overrides.jsonl` entirely
    (report.remove_override) -- there's no "unverified" override shape to
    append, the only way a work stops being verified is to have no
    override on file at all
  - if an evidence dossier exists for the work, patching it back from
    `verified` to `pending-human-review` (evidence_wiki.mark_pending),
    undoing any relationship correction the reverted verification made
  - writing a `verification_reverted` line to `evidence/log.md`, matching
    the ad hoc format used during this session's manual recovery
  - rebuilding `evidence/index.md` so the work moves back from Verified
    to Pending Review

After unverifying, the work is back to whatever it was before: a
`background-mention`-tier provisional guess if no evidence dossier ever
existed, or a `pending-human-review` proposed finding if one does --
either way, no longer usable in a theme/narrative section requiring
verification, and `wake bake` no longer marks it `[VERIFIED via ...]`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import now_iso


def unverify_work(
    seed_work: dict[str, Any],
    citing_id: str,
    *,
    reason: str = "",
    base: Path | None = None,
) -> dict[str, Any]:
    """Reverse a mistaken verification for one citing work.

    Raises ValueError if *citing_id* was never verified in the first
    place (nothing to undo).
    """
    from .evidence_wiki import append_log_entry, mark_pending, rebuild_index
    from .report import remove_override

    seed_id = seed_work["openalex_id"]

    removed = remove_override(seed_id, citing_id, base=base)
    if not removed:
        raise ValueError(f"{citing_id!r} is not currently verified -- nothing to undo.")

    had_dossier = mark_pending(seed_id, citing_id, reason=reason, base=base)

    detail = (
        "the prior verified_by_human entry for this work was recorded without the "
        "human actually reviewing/accepting the finding -- reverted to "
        "pending-human-review" if not reason else reason
    )
    append_log_entry(
        seed_id, event="verification_reverted", citing_id=citing_id,
        detail=detail, seed_title=seed_work.get("title"), base=base,
    )
    if had_dossier:
        rebuild_index(seed_id, seed_title=seed_work.get("title"), base=base)

    return {
        "ok": True,
        "citing_id": citing_id,
        "reason": reason,
        "had_dossier": had_dossier,
        "reverted_at": now_iso(),
    }


def unverify_batch(
    seed_work: dict[str, Any],
    *,
    since: str | None = None,
    last: int | None = None,
    reason: str = "",
    base: Path | None = None,
) -> dict[str, Any]:
    """Batch-recovery variant for exactly the failure mode this command
    exists for: an agent auto-verifies a run of works it shouldn't have.

    Exactly one of *since* (an ISO-8601 timestamp -- unverify every
    override recorded at or after this time) or *last* (an integer --
    unverify the N most-recently-recorded overrides) must be given.

    Raises ValueError if neither or both of *since*/*last* are given, or
    if *last* is not a positive integer.
    """
    from .report import load_overrides

    if (since is None) == (last is None):
        raise ValueError("Exactly one of --since or --last must be given.")
    if last is not None and last <= 0:
        raise ValueError("--last must be a positive integer.")

    seed_id = seed_work["openalex_id"]
    overrides = load_overrides(seed_id, base)
    entries = sorted(overrides.values(), key=lambda e: e.get("overridden_at", ""))

    if since is not None:
        targets = [e for e in entries if e.get("overridden_at", "") >= since]
    else:
        targets = entries[-last:]

    results = [
        unverify_work(seed_work, e["citing_id"], reason=reason, base=base)
        for e in targets
    ]
    return {"ok": True, "count": len(results), "reverted": results}
