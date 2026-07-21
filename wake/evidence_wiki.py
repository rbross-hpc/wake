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
consistent with impact.md not existing until `wake bake` and
overrides.jsonl not existing until the first override.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .evidence import evidence_dir, dossier_path
from .io import atomic_write_text, now_iso

_STATUS_SECTION_RE = re.compile(
    r"<!-- status-section:start -->.*?<!-- status-section:end -->",
    re.DOTALL,
)


def index_path(seed_id: str, base: Path | None = None) -> Path:
    return evidence_dir(seed_id, base) / "index.md"


def log_path(seed_id: str, base: Path | None = None) -> Path:
    return evidence_dir(seed_id, base) / "log.md"


def themes_index_path(seed_id: str, base: Path | None = None) -> Path:
    return evidence_dir(seed_id, base) / "themes" / "index.md"


def _score(entry: dict[str, Any]) -> float:
    """Rank score for a dossier .json sidecar. Delegates to
    report.relationship_score() -- the single source of truth for this
    formula -- so the impact brief's "Strongest Evidence" ranking and this
    wiki's Verified/Pending Review ranking can never silently drift apart.
    """
    from .report import relationship_score

    relationship = entry.get("proposed", {}).get("relationship", "background-mention")
    return relationship_score(relationship, entry.get("citing_cited_by_count", 0))


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

    Concurrency assumption: wake is designed for single-process serial
    access per seed. Individual log-line writes are atomic on Linux for
    the line sizes wake produces (well under PIPE_BUF), so two concurrent
    wake invocations against the same seed will not corrupt individual
    lines but may write them in wall-clock-timestamp order rather than
    invocation order. Running concurrent wake commands against the same
    seed is not supported and may produce unexpected results in other
    append-only files (overrides.jsonl, exclusions.jsonl, etc.) as well.
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
    relationship: str | None = None,
    base: Path | None = None,
) -> bool:
    """Patch an existing dossier (.json + .md) from pending-human-review
    to verified, recording the human's justification and timestamp.

    *relationship* is the human-confirmed relationship from the `wake
    override` call. When it differs from the dossier's own
    `proposed.relationship` (the human corrected the model's reading,
    rather than simply accepting it), the dossier's `proposed` field is
    updated to match — otherwise index.md/log.md would keep displaying
    the model's superseded conclusion forever, even though the override
    that actually governs the impact brief disagrees with it. The
    dossier's original `proposed.confidence` and `proposed.justification`
    are preserved in `proposed.model_relationship`/`model_justification`
    so the original (superseded) reading stays visible for audit.

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

    proposed = payload.setdefault("proposed", {})
    model_relationship = proposed.get("relationship")
    corrected = relationship is not None and relationship != model_relationship
    if corrected:
        proposed["model_relationship"] = model_relationship
        proposed["model_justification"] = proposed.get("justification")
        proposed["relationship"] = relationship
        payload["human_verification"]["corrected_from"] = model_relationship

    atomic_write_text(json_path, json.dumps(payload, indent=2, default=str))

    md_path = dossier_path(seed_id, citing_id, base)
    if md_path.exists():
        md_text = md_path.read_text(encoding="utf-8")
        md_text = md_text.replace("status:pending-human-review", "status:verified")
        if corrected:
            md_text = md_text.replace(
                f"proposed:{model_relationship}", f"proposed:{relationship}"
            )

        # Structural replace via the <!-- status-section:... --> markers
        # _render_dossier_markdown() wraps this block in -- not a literal
        # match on the surrounding prose, so this keeps working even if
        # that prose is edited later (see evidence.py for the markers).
        status_note = f"Verified by a human on {verified_at}"
        if corrected:
            status_note += (
                f" — human corrected the model's reading from "
                f"*{model_relationship}* to *{relationship}*"
            )
        if justification:
            status_note += f" — {justification}"
        new_status_block = (
            "<!-- status-section:start -->\n"
            "## Status: verified\n\n"
            f"{status_note}.\n"
            "<!-- status-section:end -->"
        )
        if _STATUS_SECTION_RE.search(md_text):
            md_text = _STATUS_SECTION_RE.sub(new_status_block, md_text, count=1)
            atomic_write_text(md_path, md_text)

    return True


def mark_pending(
    seed_id: str,
    citing_id: str,
    *,
    reason: str = "",
    base: Path | None = None,
) -> bool:
    """Patch an existing dossier (.json + .md) back from verified to
    pending-human-review -- the reverse of `mark_verified()`, used by
    `wake unverify` to undo a mistaken verification.

    If the human's original verification corrected the model's proposed
    relationship (`mark_verified` moved the original reading into
    `proposed.model_relationship`/`model_justification`), that correction
    is undone too -- `proposed.relationship`/`justification` are restored
    to the model's own original reading, since the human's corrected
    reading is exactly the judgment being reverted. `human_verification`
    is removed entirely (it's the record of a human sign-off that no
    longer stands).

    Returns False (no-op) if no dossier exists for this citing work --
    e.g. undoing a plain human-judgment override with no `wake evidence`
    behind it has nothing to mark.
    """
    from .evidence import dossier_json_path

    json_path = dossier_json_path(seed_id, citing_id, base)
    if not json_path.exists():
        return False

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["verification_status"] = "pending-human-review"
    payload.pop("human_verification", None)

    proposed = payload.setdefault("proposed", {})
    model_relationship = proposed.pop("model_relationship", None)
    model_justification = proposed.pop("model_justification", None)
    current_relationship = proposed.get("relationship")
    if model_relationship is not None:
        proposed["relationship"] = model_relationship
        if model_justification is not None:
            proposed["justification"] = model_justification

    atomic_write_text(json_path, json.dumps(payload, indent=2, default=str))

    md_path = dossier_path(seed_id, citing_id, base)
    if md_path.exists():
        md_text = md_path.read_text(encoding="utf-8")
        md_text = md_text.replace("status:verified", "status:pending-human-review")
        if model_relationship is not None:
            md_text = md_text.replace(
                f"proposed:{current_relationship}", f"proposed:{model_relationship}"
            )

        status_note = "This finding has not been applied to the impact brief. An agent"
        new_status_block = (
            "<!-- status-section:start -->\n"
            "## Status: pending your review\n\n"
            f"{status_note} "
            "should present the passages above to a human, then run "
            "`wake override` on their behalf once the human accepts or adjusts "
            "the reading — see SKILL.md."
            + (f" (A prior verification was reverted: {reason})" if reason else "")
            + "\n"
            "<!-- status-section:end -->"
        )
        if _STATUS_SECTION_RE.search(md_text):
            md_text = _STATUS_SECTION_RE.sub(new_status_block, md_text, count=1)
            atomic_write_text(md_path, md_text)

    return True


def _load_all_themes(seed_id: str, base: Path | None = None) -> list[dict[str, Any]]:
    from .themes import themes_dir

    d = themes_dir(seed_id, base)
    if not d.exists():
        return []
    entries = []
    for p in sorted(d.glob("*.json")):
        try:
            entries.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return entries


def rebuild_themes_index(seed_id: str, seed_title: str | None = None, base: Path | None = None) -> Path:
    """Rescan every theme .json sidecar and regenerate themes/index.md
    from scratch, grouped Confirmed / Draft. Safe to call anytime; if no
    themes exist yet, does nothing and returns the (non-existent) path --
    same pattern as rebuild_index() for the top-level evidence wiki.
    """
    themes = _load_all_themes(seed_id, base)
    p = themes_index_path(seed_id, base)
    if not themes:
        return p

    confirmed = [t for t in themes if t.get("theme_status") == "confirmed"]
    draft = [t for t in themes if t.get("theme_status") != "confirmed"]
    confirmed.sort(key=lambda t: t.get("slug", ""))
    draft.sort(key=lambda t: t.get("slug", ""))

    lines: list[str] = []
    lines.append("---")
    lines.append("type: index")
    title = f"Themes: {seed_title}" if seed_title else "Themes"
    lines.append(f'title: "{title}"')
    lines.append(f"timestamp: {now_iso()}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(
        "Catalog of combined-evidence thematic documents, each synthesizing "
        "several citing works' dossiers/classifications. See each theme doc "
        "for its own cited-works list and status."
    )
    lines.append("")

    def _render_group(group: list[dict[str, Any]]) -> None:
        for t in group:
            slug = t.get("slug", "")
            n = len(t.get("citing_works", []))
            needs = len(t.get("needs_evidence", []))
            needs_note = f", {needs} needing evidence" if needs else ""
            lines.append(f"- [{t.get('title', slug)}]({slug}.md) — {n} citing work(s){needs_note}")
        lines.append("")

    lines.append(f"## Confirmed ({len(confirmed)})")
    lines.append("")
    if confirmed:
        _render_group(confirmed)
    else:
        lines.append("*(none yet)*")
        lines.append("")

    lines.append(f"## Draft ({len(draft)})")
    lines.append("")
    if draft:
        _render_group(draft)
    else:
        lines.append("*(none yet)*")
        lines.append("")

    atomic_write_text(p, "\n".join(lines))
    return p
