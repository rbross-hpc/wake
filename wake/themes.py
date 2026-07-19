# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Combined-evidence / thematic documents (BACKLOG Theme C).

When several individual citing works together support a broader claim
(e.g. "extensive use in Earth system modeling"), a theme document
synthesizes them into one OKF concept doc at
`wake-out/<seed>/evidence/themes/<slug>.md`, linking out to each work's
own evidence dossier rather than duplicating its content.

Pure write-primitive, no LLM call: the agent (having already read the
underlying dossiers/classifications) supplies the title, synthesis
paragraph, and which citing works belong together; this module validates
and persists that judgment -- it never decides what's thematically
related and never writes the synthesis prose itself. Same trust model as
`wake override`: wake persists a human/agent decision, it doesn't make one.

Two independent verification tracks, matching the codebase-wide rule that
only a human promotes anything to a settled state:

  1. Per-work relationship claims -- unchanged, existing lifecycle
     (provisional -> proposed -> verified via classify/evidence/override).
     create_theme() never alters a work's own status; every cited work is
     shown with its own honest, current tag.
  2. The theme's synthesis claim -- new: "draft" -> "confirmed".
     create_theme() always writes "draft". Only confirm_theme() (run by
     the agent on the human's behalf, exactly like wake override) can
     promote to "confirmed" -- and it refuses unless every cited work is
     already "verified". A theme can never appear settled while resting
     on unverified findings.

`needs_evidence` (citing works with no dossier yet, included anyway per
explicit design decision to allow mixed sourcing) is tracked in the
theme's own JSON sidecar -- v1, deliberately simple, flagged for revisit:
see BACKLOG.md. `wake theme queue` surfaces these across all themes for a
seed, plus any whose dossier has since appeared but hasn't been reviewed
and re-asserted via a fresh create_theme() call -- nothing is silently
upgraded.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .evidence import dossier_json_path, dossier_path, evidence_dir
from .io import atomic_write_json, atomic_write_text, now_iso, read_json

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"Invalid theme slug {slug!r}: must be lowercase letters/digits/"
            "hyphens only, e.g. 'earth-system-modeling'."
        )


def themes_dir(seed_id: str, base: Path | None = None) -> Path:
    return evidence_dir(seed_id, base) / "themes"


def theme_path(seed_id: str, slug: str, base: Path | None = None) -> Path:
    return themes_dir(seed_id, base) / f"{slug}.md"


def theme_json_path(seed_id: str, slug: str, base: Path | None = None) -> Path:
    return themes_dir(seed_id, base) / f"{slug}.json"


def load_theme(seed_id: str, slug: str, base: Path | None = None) -> dict[str, Any] | None:
    p = theme_json_path(seed_id, slug, base)
    if not p.exists():
        return None
    return read_json(p)


def _resolve_work_status(
    seed_id: str,
    citing_id: str,
    *,
    classified_by_id: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
    base: Path | None = None,
) -> dict[str, Any]:
    """Resolve one citing work's current, honest status for inclusion in a
    theme -- never upgraded by theme creation, always reflecting the real
    state of classify.py/evidence.py/report.py's own lifecycle.

    Returns a dict: {citing_id, status, has_dossier, title}
      status is one of: "verified", "proposed", "provisional", "unclassified"
    """
    classified = classified_by_id.get(citing_id)
    if classified is None:
        return {"citing_id": citing_id, "status": "unclassified", "has_dossier": False, "title": None}

    title = classified.get("title")
    has_dossier = dossier_json_path(seed_id, citing_id, base).exists()

    if citing_id in overrides:
        status = "verified"
    elif has_dossier:
        status = "proposed"
    else:
        status = "provisional"

    return {"citing_id": citing_id, "status": status, "has_dossier": has_dossier, "title": title}


def create_theme(
    seed_work: dict[str, Any],
    slug: str,
    *,
    title: str,
    summary: str,
    citing_ids: list[str],
    base: Path | None = None,
) -> dict[str, Any]:
    """Write (or overwrite) a theme document. Always writes theme_status
    "draft" -- creating/re-creating a theme is an agent judgment, not a
    human sign-off, so it can never itself produce a "confirmed" theme.
    Always overwrites (no --force): unlike every other write command in
    this codebase, there is no expensive LLM/network call to protect
    against re-doing, so there's nothing to cache-guard.

    Raises ValueError if any citing_id has never been classified (same
    bar `wake evidence` already enforces) -- run `wake classify --ids
    <id>` first.

    Returns a summary dict: {ok, theme_path, theme_json_path, theme_status,
    citing_works: [...], needs_evidence: [...]}.
    """
    from .classify import load_classified
    from .report import load_overrides

    _validate_slug(slug)
    seed_id = seed_work["openalex_id"]

    if not citing_ids:
        raise ValueError("citing_ids must not be empty.")

    classified = load_classified(seed_id, base) or []
    classified_by_id = {w.get("openalex_id"): w for w in classified}
    overrides = load_overrides(seed_id, base)

    citing_works: list[dict[str, Any]] = []
    unclassified: list[str] = []
    for cid in citing_ids:
        resolved = _resolve_work_status(
            seed_id, cid, classified_by_id=classified_by_id, overrides=overrides, base=base,
        )
        if resolved["status"] == "unclassified":
            unclassified.append(cid)
        citing_works.append(resolved)

    if unclassified:
        raise ValueError(
            "The following citing works have never been classified, so they "
            f"can't be added to a theme yet: {', '.join(unclassified)}. "
            f"Run `wake classify {seed_work.get('openalex_id')} --ids "
            f"{','.join(unclassified)}` first."
        )

    # A work only "needs evidence" if it isn't already verified -- a plain
    # human-judgment override (no dossier at all) already meets the bar
    # confirm_theme() checks, so it must never be flagged here even though
    # has_dossier is False for it.
    needs_evidence = [
        w["citing_id"] for w in citing_works
        if w["status"] != "verified" and not w["has_dossier"]
    ]

    existing = load_theme(seed_id, slug, base)
    created_at = existing.get("created_at") if existing else now_iso()

    payload = {
        "seed_openalex_id": seed_id,
        "slug": slug,
        "title": title,
        "summary": summary,
        "theme_status": "draft",
        "created_at": created_at,
        "updated_at": now_iso(),
        "citing_works": citing_works,
        "needs_evidence": needs_evidence,
    }

    wd = themes_dir(seed_id, base)
    wd.mkdir(parents=True, exist_ok=True)
    json_path = theme_json_path(seed_id, slug, base)
    md_path = theme_path(seed_id, slug, base)

    atomic_write_json(json_path, payload)
    atomic_write_text(md_path, _render_theme_markdown(seed_work, payload))

    from .evidence_wiki import rebuild_themes_index
    rebuild_themes_index(seed_id, seed_title=seed_work.get("title"), base=base)

    return {
        "ok": True,
        "theme_path": str(md_path),
        "theme_json_path": str(json_path),
        "theme_status": "draft",
        "citing_works": citing_works,
        "needs_evidence": needs_evidence,
    }


def confirm_theme(
    seed_work: dict[str, Any],
    slug: str,
    *,
    base: Path | None = None,
) -> dict[str, Any]:
    """Human-approved sign-off promoting a theme from "draft" to
    "confirmed" -- run by the agent on the human's behalf, exactly like
    `wake override`. Refuses unless every cited work is already
    "verified" (i.e. human-reviewed via `wake override`), re-resolved
    fresh at confirm time (not from the theme's own possibly-stale JSON)
    so a work verified after the theme was created still counts.

    Returns {"ok": True, ...} on success, or {"ok": False, "reason":
    "unverified_works", "unverified": [...]}} if blocked.
    """
    from .classify import load_classified
    from .report import load_overrides

    seed_id = seed_work["openalex_id"]
    theme = load_theme(seed_id, slug, base)
    if theme is None:
        raise ValueError(f"No theme {slug!r} found for seed {seed_id}. Run `wake theme create` first.")

    classified = load_classified(seed_id, base) or []
    classified_by_id = {w.get("openalex_id"): w for w in classified}
    overrides = load_overrides(seed_id, base)

    citing_ids = [w["citing_id"] for w in theme["citing_works"]]
    refreshed = [
        _resolve_work_status(seed_id, cid, classified_by_id=classified_by_id, overrides=overrides, base=base)
        for cid in citing_ids
    ]
    unverified = [w["citing_id"] for w in refreshed if w["status"] != "verified"]

    if unverified:
        return {
            "ok": False,
            "reason": "unverified_works",
            "unverified": unverified,
            "message": (
                f"Cannot confirm theme {slug!r}: {len(unverified)} of "
                f"{len(citing_ids)} cited work(s) are not yet human-verified: "
                f"{', '.join(unverified)}. Run `wake evidence` + `wake override` "
                "on each first, then re-run `wake theme confirm`."
            ),
        }

    theme["theme_status"] = "confirmed"
    theme["confirmed_at"] = now_iso()
    theme["citing_works"] = refreshed
    theme["needs_evidence"] = []
    theme["updated_at"] = now_iso()

    json_path = theme_json_path(seed_id, slug, base)
    md_path = theme_path(seed_id, slug, base)
    atomic_write_json(json_path, theme)
    atomic_write_text(md_path, _render_theme_markdown(seed_work, theme))

    from .evidence_wiki import rebuild_themes_index
    rebuild_themes_index(seed_id, seed_title=seed_work.get("title"), base=base)

    return {
        "ok": True,
        "theme_path": str(md_path),
        "theme_json_path": str(json_path),
        "theme_status": "confirmed",
    }


def list_theme_needs_evidence(seed_id: str, base: Path | None = None) -> list[dict[str, Any]]:
    """Scan every theme's JSON sidecar and return a flattened report of
    outstanding work, for `wake theme queue`:
      - citing works with no dossier yet ("needs-evidence")
      - citing works whose dossier now exists but hasn't been reviewed
        and re-asserted via a fresh `wake theme create` call
        ("dossier-available-unreviewed") -- computed fresh here, never
        written into the theme's own JSON automatically, so nothing is
        silently upgraded.

    Each entry: {theme_slug, citing_id, status}
    """
    wd = themes_dir(seed_id, base)
    if not wd.exists():
        return []

    entries: list[dict[str, Any]] = []
    for p in sorted(wd.glob("*.json")):
        try:
            theme = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        slug = theme.get("slug", p.stem)
        for cid in theme.get("needs_evidence", []):
            has_dossier = dossier_json_path(seed_id, cid, base).exists()
            status = "dossier-available-unreviewed" if has_dossier else "needs-evidence"
            entries.append({"theme_slug": slug, "citing_id": cid, "status": status})
    return entries


def _render_theme_markdown(seed_work: dict[str, Any], theme: dict[str, Any]) -> str:
    """Render the theme as an OKF concept document."""
    slug = theme["slug"]
    title = theme["title"]
    status = theme["theme_status"]

    lines: list[str] = []
    lines.append("---")
    lines.append("type: theme")
    lines.append(f'title: "{title}"')
    lines.append(f'description: "{theme["summary"][:150]}"')
    tags = [f"status:{status}"]
    lines.append(f"tags: [{', '.join(tags)}]")
    lines.append(f"timestamp: {theme['updated_at']}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Theme: {title}")
    lines.append("")

    if status == "confirmed":
        lines.append(f"**✓ CONFIRMED** by a human on {theme.get('confirmed_at', '')}.")
    else:
        lines.append(
            "**⚠ DRAFT** — this synthesis has not yet been human-confirmed. "
            "Present it to the human and run `wake theme confirm` on their "
            "behalf once they approve it (requires every cited work below "
            "to be individually human-verified first)."
        )
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(theme["summary"])
    lines.append("")

    lines.append("## Citing Works")
    lines.append("")

    status_labels = {
        "verified": "[VERIFIED]",
        "proposed": "[PROPOSED — full-text read, pending human review]",
        "provisional": "[PROVISIONAL — abstract-only, no full-text dossier]",
    }
    for w in theme["citing_works"]:
        cid = w["citing_id"]
        label = status_labels.get(w["status"], f"[{w['status'].upper()}]")
        display_title = w.get("title") or cid
        if w.get("has_dossier"):
            lines.append(f"- {label} [{display_title}](../{cid}.md)")
        elif w["status"] == "verified":
            # Verified via a plain human-judgment override -- no dossier
            # exists (and none is needed; the human already signed off
            # directly), so there's nothing to link to and no "go verify
            # this" hint to show.
            lines.append(f"- {label} {display_title} ({cid})")
        else:
            lines.append(
                f"- {label} {display_title} ({cid}) — no full-text dossier yet; "
                f"run `wake evidence <seed> {cid}` to verify"
            )
    lines.append("")

    needs_evidence = theme.get("needs_evidence", [])
    if needs_evidence:
        lines.append("## Needs Full-Text Verification")
        lines.append("")
        lines.append(
            "The following cited works have no evidence dossier yet — this "
            "theme's synthesis rests partly on abstract-only classifications "
            "for them, and confirmation is blocked until they're verified:"
        )
        lines.append("")
        for cid in needs_evidence:
            lines.append(f"- {cid}")
        lines.append("")

    return "\n".join(lines)
