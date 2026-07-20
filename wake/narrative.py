# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Narrative drafting (BACKLOG Theme F1/F2 seed).

A narrative is built in three explicit stages, matching the same
"agent proposes, human confirms" trust model as `wake theme` and `wake
override` — wake never writes prose or decides what's thematically
related; it validates and persists the agent's/human's judgment.

  1. Outline (`wake narrative outline create`) — the agent plans the
     overall structure before writing any prose: an ordered list of
     components, each either "theme" (backed by one or more already-
     existing themes) or "free" (framing prose with no evidence claim,
     e.g. an intro or conclusion). Always overwritable, no confirmation
     of its own — it's a plan, not a claim, and can be revised freely as
     drafting proceeds.

  2. Sections (`wake narrative section create` / `section confirm`) —
     one at a time, the agent drafts the actual prose for a component,
     having read the underlying theme(s)/dossiers itself. Always written
     as "draft". Only `section confirm` (run by the agent on the human's
     behalf, exactly like `wake theme confirm`) can promote a section to
     "confirmed" — and for a "theme"-kind section, it refuses unless
     every referenced theme is *currently* confirmed, re-checked fresh
     at confirm time (not from a cached status), so a theme that was
     later reopened to draft (e.g. an unverified work was added) is
     caught rather than silently ignored. "free" sections have no theme
     to check and confirm immediately on request — they still go through
     the same draft -> confirmed lifecycle for a uniform mental model,
     since framing prose can still make claims worth a human's eye.

  3. Stitch (`wake narrative stitch`) — assembles the outline order and
     every section (confirmed or not) into one top-level
     `wake-out/<seed>/narrative.md`, clearly labeling each section's
     status (confirmed prose vs. still-draft vs. not yet written) rather
     than pretending a partial narrative is more final than it is — same
     "works on partial data, marks coverage" philosophy as `wake bake`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .io import atomic_write_json, atomic_write_text, now_iso, read_json
from .seed import work_dir

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_KINDS = ("theme", "free")


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"Invalid slug {slug!r}: must be lowercase letters/digits/"
            "hyphens only, e.g. 'earth-system-modeling'."
        )


def narrative_dir(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "narrative"


def sections_dir(seed_id: str, base: Path | None = None) -> Path:
    return narrative_dir(seed_id, base) / "sections"


def outline_json_path(seed_id: str, base: Path | None = None) -> Path:
    return narrative_dir(seed_id, base) / "outline.json"


def outline_md_path(seed_id: str, base: Path | None = None) -> Path:
    return narrative_dir(seed_id, base) / "outline.md"


def section_json_path(seed_id: str, slug: str, base: Path | None = None) -> Path:
    return sections_dir(seed_id, base) / f"{slug}.json"


def section_md_path(seed_id: str, slug: str, base: Path | None = None) -> Path:
    return sections_dir(seed_id, base) / f"{slug}.md"


def narrative_md_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "narrative.md"


def load_outline(seed_id: str, base: Path | None = None) -> dict[str, Any] | None:
    p = outline_json_path(seed_id, base)
    if not p.exists():
        return None
    return read_json(p)


def load_section(seed_id: str, slug: str, base: Path | None = None) -> dict[str, Any] | None:
    p = section_json_path(seed_id, slug, base)
    if not p.exists():
        return None
    return read_json(p)


def _load_all_sections(seed_id: str, base: Path | None = None) -> dict[str, dict[str, Any]]:
    d = sections_dir(seed_id, base)
    if not d.exists():
        return {}
    sections: dict[str, dict[str, Any]] = {}
    for p in sorted(d.glob("*.json")):
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        slug = entry.get("slug", p.stem)
        sections[slug] = entry
    return sections


def create_outline(
    seed_work: dict[str, Any],
    *,
    components: list[dict[str, Any]],
    base: Path | None = None,
) -> dict[str, Any]:
    """Write (or overwrite) the narrative outline: an ordered plan of
    components before any prose is drafted.

    Each component dict must have:
      - "slug": lowercase-hyphenated identifier, matched to a later
        `wake narrative section create` call.
      - "title": human-readable section title.
      - "kind": "theme" or "free".
      - "theme_slugs": required (non-empty list) if kind == "theme";
        must be omitted or empty if kind == "free". Referenced themes
        must already exist (loadable via `wake theme create`) but need
        not be confirmed yet — planning ahead of confirmation is fine;
        confirmation is enforced later, at `section confirm` time.

    Always overwrites (no --force, same rationale as `wake theme
    create`: nothing expensive to protect against re-doing). Does not
    itself require or produce any confirmation — the outline is a plan,
    not a claim.

    Raises ValueError on a malformed component list (bad kind, missing
    theme_slugs for a theme-kind component, a referenced theme that
    doesn't exist, or a duplicate slug).
    """
    from .themes import load_theme

    seed_id = seed_work["openalex_id"]

    if not components:
        raise ValueError("components must not be empty.")

    seen_slugs: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for c in components:
        slug = c.get("slug")
        title = c.get("title")
        kind = c.get("kind")
        if not slug or not title or kind not in _KINDS:
            raise ValueError(
                f"Each component needs slug/title/kind (kind in {_KINDS}); got {c!r}."
            )
        _validate_slug(slug)
        if slug in seen_slugs:
            raise ValueError(f"Duplicate component slug {slug!r}.")
        seen_slugs.add(slug)

        theme_slugs = c.get("theme_slugs") or []
        if kind == "theme":
            if not theme_slugs:
                raise ValueError(f"Component {slug!r} has kind='theme' but no theme_slugs.")
            missing = [ts for ts in theme_slugs if load_theme(seed_id, ts, base) is None]
            if missing:
                raise ValueError(
                    f"Component {slug!r} references theme(s) that don't exist yet: "
                    f"{', '.join(missing)}. Run `wake theme create` first."
                )
        elif theme_slugs:
            raise ValueError(f"Component {slug!r} has kind='free' but theme_slugs were given.")

        normalized.append({
            "slug": slug, "title": title, "kind": kind, "theme_slugs": theme_slugs,
        })

    existing = load_outline(seed_id, base)
    created_at = existing.get("created_at") if existing else now_iso()

    payload = {
        "seed_openalex_id": seed_id,
        "components": normalized,
        "created_at": created_at,
        "updated_at": now_iso(),
    }

    d = narrative_dir(seed_id, base)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_json(outline_json_path(seed_id, base), payload)

    sections = _load_all_sections(seed_id, base)
    atomic_write_text(outline_md_path(seed_id, base), _render_outline_markdown(seed_work, payload, sections))

    return {
        "ok": True,
        "outline_path": str(outline_md_path(seed_id, base)),
        "outline_json_path": str(outline_json_path(seed_id, base)),
        "components": normalized,
    }


def create_section(
    seed_work: dict[str, Any],
    slug: str,
    *,
    title: str,
    prose: str,
    theme_slugs: list[str] | None = None,
    base: Path | None = None,
) -> dict[str, Any]:
    """Write (or overwrite) one narrative section's prose. Always writes
    section_status "draft" -- drafting/redrafting is an agent judgment,
    not a human sign-off, so it can never itself produce a "confirmed"
    section (same rule as `wake theme create` / `theme_status`).

    kind is inferred: "theme" if theme_slugs is non-empty, else "free".
    For a "theme" section, every referenced theme must already exist
    (loadable) but need not be confirmed yet -- that's enforced at
    `confirm_section()` time, re-checked fresh.

    Always overwrites (no --force: nothing expensive to protect against
    re-doing -- same rationale as `wake theme create`).
    """
    from .themes import load_theme

    _validate_slug(slug)
    seed_id = seed_work["openalex_id"]

    if not prose or not prose.strip():
        raise ValueError("prose must not be empty.")

    theme_slugs = theme_slugs or []
    kind = "theme" if theme_slugs else "free"

    if kind == "theme":
        missing = [ts for ts in theme_slugs if load_theme(seed_id, ts, base) is None]
        if missing:
            raise ValueError(
                f"Section {slug!r} references theme(s) that don't exist yet: "
                f"{', '.join(missing)}. Run `wake theme create` first."
            )

    existing = load_section(seed_id, slug, base)
    created_at = existing.get("created_at") if existing else now_iso()

    payload = {
        "seed_openalex_id": seed_id,
        "slug": slug,
        "title": title,
        "kind": kind,
        "theme_slugs": theme_slugs,
        "prose": prose,
        "section_status": "draft",
        "created_at": created_at,
        "updated_at": now_iso(),
    }

    d = sections_dir(seed_id, base)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_json(section_json_path(seed_id, slug, base), payload)
    atomic_write_text(section_md_path(seed_id, slug, base), _render_section_markdown(seed_work, payload))

    _refresh_outline_md(seed_work, base)

    return {
        "ok": True,
        "section_path": str(section_md_path(seed_id, slug, base)),
        "section_json_path": str(section_json_path(seed_id, slug, base)),
        "section_status": "draft",
        "kind": kind,
        "theme_slugs": theme_slugs,
    }


def confirm_section(
    seed_work: dict[str, Any],
    slug: str,
    *,
    base: Path | None = None,
) -> dict[str, Any]:
    """Human-approved sign-off promoting a section from "draft" to
    "confirmed" -- run by the agent on the human's behalf, exactly like
    `wake theme confirm`.

    For a "theme"-kind section: refuses unless every referenced theme is
    *currently* confirmed, re-resolved fresh (not from the section's own
    possibly-stale JSON) -- if a theme was reopened to draft after this
    section was last drafted (e.g. a new unverified work was added to
    it), that inconsistency is caught here rather than silently ignored.

    For a "free"-kind section: no themes to check, confirms immediately
    (the human's approval of the framing prose itself is the only bar).

    Returns {"ok": True, ...} on success, or {"ok": False, "reason":
    "unconfirmed_themes", "unconfirmed": [...]} if blocked.
    """
    from .themes import load_theme

    seed_id = seed_work["openalex_id"]
    section = load_section(seed_id, slug, base)
    if section is None:
        raise ValueError(f"No section {slug!r} found for seed {seed_id}. Run `wake narrative section create` first.")

    theme_slugs = section.get("theme_slugs") or []
    if theme_slugs:
        unconfirmed = []
        for ts in theme_slugs:
            theme = load_theme(seed_id, ts, base)
            if theme is None or theme.get("theme_status") != "confirmed":
                unconfirmed.append(ts)
        if unconfirmed:
            return {
                "ok": False,
                "reason": "unconfirmed_themes",
                "unconfirmed": unconfirmed,
                "message": (
                    f"Cannot confirm section {slug!r}: theme(s) not currently confirmed: "
                    f"{', '.join(unconfirmed)}. Run `wake theme confirm` on each first, "
                    "then re-run `wake narrative section confirm`."
                ),
            }

    section["section_status"] = "confirmed"
    section["confirmed_at"] = now_iso()
    section["updated_at"] = now_iso()

    atomic_write_json(section_json_path(seed_id, slug, base), section)
    atomic_write_text(section_md_path(seed_id, slug, base), _render_section_markdown(seed_work, section))

    _refresh_outline_md(seed_work, base)

    return {
        "ok": True,
        "section_path": str(section_md_path(seed_id, slug, base)),
        "section_json_path": str(section_json_path(seed_id, slug, base)),
        "section_status": "confirmed",
    }


def stitch(seed_work: dict[str, Any], *, base: Path | None = None) -> dict[str, Any]:
    """Assemble the outline order + every drafted section into one
    top-level `wake-out/<seed>/narrative.md`. Always runs, even on
    partial data (missing or still-draft sections) -- same "works on
    partial data, marks coverage" philosophy as `wake bake` -- so the
    output always clearly labels each section as confirmed prose,
    still-draft prose (shown but flagged), or not yet written at all,
    rather than silently omitting or overstating what's actually there.

    Raises ValueError if no outline has been created yet.
    """
    seed_id = seed_work["openalex_id"]
    outline = load_outline(seed_id, base)
    if outline is None:
        raise ValueError(
            f"No narrative outline found for seed {seed_id}. Run `wake narrative outline create` first."
        )

    sections = _load_all_sections(seed_id, base)

    confirmed_count = sum(1 for s in sections.values() if s.get("section_status") == "confirmed")
    draft_count = sum(1 for s in sections.values() if s.get("section_status") == "draft")
    missing = [c["slug"] for c in outline["components"] if c["slug"] not in sections]

    lines: list[str] = []
    title = seed_work.get("title") or seed_id
    lines.append(f"# Narrative: {title}")
    lines.append("")
    lines.append(f"*Assembled by wake on {now_iso()}*")
    lines.append("")
    if missing or draft_count:
        notes = []
        if draft_count:
            notes.append(f"{draft_count} section(s) still draft (not yet human-confirmed)")
        if missing:
            notes.append(f"{len(missing)} planned section(s) not yet written: {', '.join(missing)}")
        lines.append(f"> **Partial narrative** — {'; '.join(notes)}.")
        lines.append("")

    for component in outline["components"]:
        slug = component["slug"]
        section = sections.get(slug)
        lines.append(f"## {component['title']}")
        lines.append("")
        if section is None:
            lines.append(f"*(not yet drafted — run `wake narrative section create {seed_id} {slug} ...`)*")
        else:
            status = section.get("section_status")
            if status != "confirmed":
                lines.append("**⚠ DRAFT — not yet human-confirmed.**")
                lines.append("")
            lines.append(section["prose"])
        lines.append("")

    md_path = narrative_md_path(seed_id, base)
    atomic_write_text(md_path, "\n".join(lines))

    return {
        "ok": True,
        "narrative_path": str(md_path),
        "confirmed_sections": confirmed_count,
        "draft_sections": draft_count,
        "missing_sections": missing,
    }


def _render_outline_markdown(
    seed_work: dict[str, Any],
    outline: dict[str, Any],
    sections: dict[str, dict[str, Any]],
) -> str:
    title = seed_work.get("title") or outline["seed_openalex_id"]
    lines: list[str] = []
    lines.append("---")
    lines.append("type: narrative-outline")
    lines.append(f'title: "Narrative Outline: {title}"')
    lines.append(f"timestamp: {outline['updated_at']}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Narrative Outline: {title}")
    lines.append("")
    lines.append(
        "Planned structure for the narrative, before any prose is drafted. "
        "See `sections/` for drafted prose, one component at a time; "
        "`wake narrative stitch` assembles this order into the top-level "
        "`narrative.md`."
    )
    lines.append("")
    for c in outline["components"]:
        section = sections.get(c["slug"])
        if section is None:
            status = "not yet drafted"
        else:
            status = section.get("section_status", "draft")
        theme_note = f" — themes: {', '.join(c['theme_slugs'])}" if c["theme_slugs"] else " — free-form"
        lines.append(f"- **{c['title']}** (`{c['slug']}`){theme_note} — {status}")
    lines.append("")
    return "\n".join(lines)


def _refresh_outline_md(seed_work: dict[str, Any], base: Path | None = None) -> None:
    """Re-render outline.md's per-component status column after a section
    is created/confirmed, if an outline already exists. No-op otherwise
    (a section can be drafted before an outline names it)."""
    seed_id = seed_work["openalex_id"]
    outline = load_outline(seed_id, base)
    if outline is None:
        return
    sections = _load_all_sections(seed_id, base)
    atomic_write_text(outline_md_path(seed_id, base), _render_outline_markdown(seed_work, outline, sections))


def _render_section_markdown(seed_work: dict[str, Any], section: dict[str, Any]) -> str:
    status = section["section_status"]
    lines: list[str] = []
    lines.append("---")
    lines.append("type: narrative-section")
    lines.append(f'title: "{section["title"]}"')
    tags = [f"kind:{section['kind']}", f"status:{status}"]
    lines.append(f"tags: [{', '.join(tags)}]")
    lines.append(f"timestamp: {section['updated_at']}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Section: {section['title']}")
    lines.append("")

    if status == "confirmed":
        lines.append(f"**✓ CONFIRMED** by a human on {section.get('confirmed_at', '')}.")
    else:
        if section["kind"] == "theme":
            lines.append(
                "**⚠ DRAFT** — this section has not yet been human-confirmed. "
                "Present it to the human and run `wake narrative section confirm` "
                "on their behalf once they approve it (requires every referenced "
                "theme below to be currently confirmed)."
            )
        else:
            lines.append(
                "**⚠ DRAFT** — this section has not yet been human-confirmed. "
                "Present it to the human and run `wake narrative section confirm` "
                "on their behalf once they approve it."
            )
    lines.append("")

    if section["theme_slugs"]:
        lines.append("**Grounded in themes:** " + ", ".join(
            f"[{ts}](../../evidence/themes/{ts}.md)" for ts in section["theme_slugs"]
        ))
        lines.append("")

    lines.append("## Prose")
    lines.append("")
    lines.append(section["prose"])
    lines.append("")

    return "\n".join(lines)
