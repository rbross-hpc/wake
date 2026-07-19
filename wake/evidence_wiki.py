# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""OKF evidence wiki organization layer (BACKLOG Theme D).

Individual evidence dossiers (evidence.py::build_dossier) are the
"concept documents" of an OKF-style knowledge wiki living at
`wake-out/<seed>/evidence/`. This module builds the two reserved OKF
files that organize them:

  index.md — catalog: every dossier, grouped Verified / Pending Review,
             sorted by the same relationship-strength x reach score
             report.py uses for "Strongest Evidence" in the impact brief.
  log.md   — chronological history: every investigation attempt (built,
             rebuilt, failed, or resolved by a human), newest at the
             bottom, append-only.

Both files are derived entirely from the dossier .json sidecars already
written by build_dossier() — there is no separate index/log data store,
so a corrupted or hand-edited index.md can always be regenerated from
scratch via rebuild_index(). Neither file exists until the first real
event (a dossier build, or a human verifying one via `wake override`) —
consistent with impact.md not existing until `wake render` and
.overrides.jsonl not existing until the first override.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .evidence import evidence_dir, dossier_path
from .io import atomic_write_text, now_iso


def index_path(seed_id: str, base: Path | None = None) -> Path:
    return evidence_dir(seed_id, base) / "index.md"


def log_path(seed_id: str, base: Path | None = None) -> Path:
    return evidence_dir(seed_id, base) / "log.md"


def _score(entry: dict[str, Any]) -> float:
    """Same ranking formula as report.py's _score(): relationship
    strength x log(1 + downstream cited_by_count)."""
    from .classify import RELATIONSHIP_STRENGTH

    relationship = entry.get("proposed", {}).get("relationship", "background-mention")
    strength = RELATIONSHIP_STRENGTH.get(relationship, 1)
    downstream = entry.get("citing_cited_by_count", 0) or 0
    return strength * math.log1p(downstream)


def _load_all_dossiers(seed_id: str, base: Path | None = None) -> list[dict[str, Any]]:
    """Load every dossier .json sidecar in evidence/, skipping non-dossier
    files (e.g. a future themes/ subdirectory or the wiki files themselves,
    which have no .json sibling)."""
    d = evidence_dir(seed_id, base)
    if not d.exists():
        return []
    entries = []
    for p in sorted(d.glob("*.json")):
        try:
            entries.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return entries


def rebuild_index(seed_id: str, seed_title: str | None = None, base: Path | None = None) -> Path:
    """Rescan every dossier sidecar and regenerate index.md from scratch.

    Safe to call anytime after at least one dossier exists; if no
    dossiers exist yet, does nothing and returns the (non-existent) path.
    """
    entries = _load_all_dossiers(seed_id, base)
    p = index_path(seed_id, base)
    if not entries:
        return p

    verified = [e for e in entries if e.get("verification_status") == "verified"]
    pending = [e for e in entries if e.get("verification_status") != "verified"]
    verified.sort(key=_score, reverse=True)
    pending.sort(key=_score, reverse=True)

    lines: list[str] = []
    lines.append("---")
    lines.append("type: index")
    title = f"Evidence Wiki: {seed_title}" if seed_title else "Evidence Wiki"
    lines.append(f'title: "{title}"')
    lines.append(f"timestamp: {now_iso()}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(
        "Catalog of full-text-verified findings for citing works "
        "(`wake evidence`). See `log.md` for the full investigation history."
    )
    lines.append("")

    def _render_group(group: list[dict[str, Any]]) -> None:
        for e in group:
            cid = e.get("citing_openalex_id", "")
            rel = e.get("proposed", {}).get("relationship", "?")
            score = round(_score(e), 2)
            when = e.get("human_verification", {}).get("verified_at") or e.get("generated_at", "")
            verb = "verified" if e.get("verification_status") == "verified" else "investigated"
            lines.append(f"- [{cid}]({cid}.md) — *{rel}* — score {score} — {verb} {when}")
        lines.append("")

    lines.append(f"## Verified ({len(verified)})")
    lines.append("")
    if verified:
        _render_group(verified)
    else:
        lines.append("*(none yet)*")
        lines.append("")

    lines.append(f"## Pending Review ({len(pending)})")
    lines.append("")
    if pending:
        _render_group(pending)
    else:
        lines.append("*(none yet)*")
        lines.append("")

    atomic_write_text(p, "\n".join(lines))
    return p


def append_log_entry(
    seed_id: str,
    *,
    event: str,
    citing_id: str,
    detail: str = "",
    seed_title: str | None = None,
    base: Path | None = None,
) -> Path:
    """Append one chronological entry to log.md, newest at the bottom.
    Creates the file with an OKF header on first write.

    Links to the dossier markdown when it exists (successful builds,
    verifications); failed investigations (no PDF found, extraction
    failed) have no dossier to link to, so the citing ID is left as
    plain text instead of a dead link.
    """
    p = log_path(seed_id, base)
    has_dossier = dossier_path(seed_id, citing_id, base).exists()
    citing_ref = f"[{citing_id}]({citing_id}.md)" if has_dossier else citing_id
    line = f"- {now_iso()} — {event} — {citing_ref}"
    if detail:
        line += f" — {detail}"

    if not p.exists():
        title = f"Evidence Wiki Log: {seed_title}" if seed_title else "Evidence Wiki Log"
        header = "\n".join([
            "---",
            "type: log",
            f'title: "{title}"',
            "---",
            "",
            f"# {title}",
            "",
            "Chronological record of every `wake evidence` investigation and",
            "its resolution. Newest entry at the bottom.",
            "",
        ])
        atomic_write_text(p, header + line + "\n")
        return p

    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return p


def mark_verified(
    seed_id: str,
    citing_id: str,
    *,
    justification: str = "",
    base: Path | None = None,
) -> bool:
    """Patch an existing dossier (.json + .md) from pending-human-review
    to verified, recording the human's justification and timestamp.

    Returns False (no-op) if no dossier exists for this citing work —
    e.g. a plain human-judgment override with no `wake evidence` behind
    it has nothing to mark.
    """
    from .evidence import dossier_json_path

    json_path = dossier_json_path(seed_id, citing_id, base)
    if not json_path.exists():
        return False

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    verified_at = now_iso()
    payload["verification_status"] = "verified"
    payload["human_verification"] = {
        "justification": justification,
        "verified_at": verified_at,
    }
    atomic_write_text(json_path, json.dumps(payload, indent=2, default=str))

    md_path = dossier_path(seed_id, citing_id, base)
    if md_path.exists():
        md_text = md_path.read_text(encoding="utf-8")
        md_text = md_text.replace("status:pending-human-review", "status:verified")

        old_status_block = (
            "## Status: pending your review\n\n"
            "This finding has not been applied to the impact brief. An agent "
            "should present the passages above to a human, then run "
            "`wake override` on their behalf once the human accepts or adjusts "
            "the reading — see SKILL.md.\n"
        )
        new_status_block = (
            "## Status: verified\n\n"
            f"Verified by a human on {verified_at}"
            + (f" — {justification}" if justification else "")
            + ".\n"
        )
        md_text = md_text.replace(old_status_block, new_status_block)
        atomic_write_text(md_path, md_text)

    return True
