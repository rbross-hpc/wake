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

_REF_RE = re.compile(r"\[ref:([A-Za-z0-9_,\s]+)\]")
_SEED_REF = "SEED"


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


def refs_json_path(seed_id: str, base: Path | None = None) -> Path:
    return narrative_dir(seed_id, base) / "refs.json"


def refs_results_json_path(seed_id: str, base: Path | None = None) -> Path:
    return narrative_dir(seed_id, base) / "refs.results.json"


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


def _verified_ids(seed_id: str, base: Path | None = None) -> set[str]:
    """The set of citing IDs currently human-verified for this seed --
    same definition themes.py uses (`_resolve_work_status`): a work
    counts as verified once it appears in `overrides.jsonl`, regardless
    of whether it went through a full evidence dossier or a plain
    `wake override` judgment call. `classified.json`'s own
    `verification_status` field is never updated in place and must not
    be trusted for this check.
    """
    from .classify import load_classified
    from .report import load_overrides

    classified = load_classified(seed_id, base) or []
    classified_ids = {w.get("openalex_id") for w in classified}
    overrides = load_overrides(seed_id, base)
    return {cid for cid in overrides if cid in classified_ids}


def _check_packet_consistency(seed_id: str, base: Path | None = None) -> None:
    """Guard against a corrupted/half-migrated packet before trusting any
    reference marker in it: every citing work this seed's own bookkeeping
    considers verified must have an actual dossier markdown file on disk
    (the physical artifact of that verification). If any are missing,
    the packet itself is inconsistent and no narrative built on top of it
    can be trusted -- raise naming every offender, not just the first.
    """
    from .evidence import dossier_path

    missing = [
        cid for cid in sorted(_verified_ids(seed_id, base))
        if not dossier_path(seed_id, cid, base).exists()
    ]
    if missing:
        raise ValueError(
            "Packet inconsistency: the following citing work(s) are marked "
            "verified but have no evidence dossier on disk: "
            f"{', '.join(missing)}. Fix the packet (e.g. re-run `wake evidence` "
            "or `wake override`) before drafting narrative sections that cite them."
        )


def _parse_ref_markers(prose: str) -> list[list[str]]:
    """Return the list of ID-lists named by each `[ref:ID,ID,...]` marker
    in *prose*, in order of appearance. Whitespace around commas/brackets
    is tolerated; IDs themselves are returned exactly as written (case
    preserved) for exact-match validation against citing IDs and `SEED`.
    """
    markers = []
    for m in _REF_RE.finditer(prose):
        ids = [part.strip() for part in m.group(1).split(",") if part.strip()]
        markers.append(ids)
    return markers


def _validate_ref_ids(seed_id: str, prose: str, base: Path | None = None) -> None:
    """Validate every `[ref:...]` marker in *prose*: each named ID must be
    either `SEED` or a citing work currently human-verified for this seed
    (see `_verified_ids`). Raises ValueError naming every invalid ID at
    once, not one at a time.

    This validates only that the referenced source is real and verified
    -- not that it actually supports the sentence's claim, which remains
    an agent/human judgment (a future `wake narrative section audit`
    command is the intended place for that check, kept deliberately
    separate from this structural validation).
    """
    all_ids: set[str] = set()
    for ids in _parse_ref_markers(prose):
        all_ids.update(ids)
    if not all_ids:
        return

    verified = _verified_ids(seed_id, base)
    bad = sorted(i for i in all_ids if i != _SEED_REF and i not in verified)
    if bad:
        raise ValueError(
            "prose references source(s) that are not SEED and not a "
            f"currently human-verified citing work: {', '.join(bad)}. "
            "Every [ref:...] marker must name SEED or a citing ID that has "
            "been through `wake evidence` + `wake override` (or a plain "
            "`wake override`) for this seed."
        )


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

    Prose may cite its sources with `[ref:ID,ID,...]` markers, where each
    ID is `SEED` or a citing work's OpenAlex ID. Every marker is validated
    against the packet: first a consistency pass (every citing work this
    seed's bookkeeping calls verified must have a dossier file on disk --
    a corrupted packet is refused outright, not just the specific claim),
    then each named ID must resolve to `SEED` or a currently
    human-verified citing work. This guarantees every reference in the
    stitched narrative points at a real, human-checked source -- it does
    not guarantee the source actually supports the sentence, which stays
    an agent/human judgment.

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

    _check_packet_consistency(seed_id, base)
    _validate_ref_ids(seed_id, prose, base)

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


def _work_metadata_for_ref(ref_id: str, seed_work: dict[str, Any], base: Path | None = None) -> dict[str, Any] | None:
    """Bibliographic fields for one reference ID, for the Chicago-style
    entry: SEED resolves to the seed work itself; any other ID resolves
    to its entry in classified.json (the only place wake persists a
    citing work's authors/year/venue/DOI)."""
    if ref_id == _SEED_REF:
        return seed_work

    from .classify import load_classified

    seed_id = seed_work["openalex_id"]
    classified = load_classified(seed_id, base) or []
    for w in classified:
        if w.get("openalex_id") == ref_id:
            return w
    return None


def _chicago_entry(work: dict[str, Any] | None, ref_id: str) -> str:
    """One Chicago author-date-style reference-list entry. Missing fields
    (venue, DOI) are omitted cleanly rather than rendered as blanks.
    wake has no persisted OSTI identifier for any citing work (OSTI is
    used only transiently, as one candidate PDF source), so no OSTI
    suffix is ever rendered here."""
    if work is None:
        return f"*{ref_id}: no bibliographic record found in classified.json.*"

    authors = work.get("authors") or []
    if not authors:
        author_str = ""
    elif len(authors) == 1:
        author_str = authors[0]
    elif len(authors) == 2:
        author_str = f"{authors[0]} and {authors[1]}"
    else:
        author_str = ", ".join(authors[:-1]) + f", and {authors[-1]}"

    year = work.get("year")
    title = work.get("title") or "(untitled)"
    venue = work.get("venue")
    doi = work.get("doi")

    parts: list[str] = []
    if author_str:
        parts.append(f"{author_str}.")
    if year:
        parts.append(f"{year}.")
    parts.append(f'"{title}."')
    if venue:
        parts.append(f"{venue}.")
    if doi:
        doi_url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
        parts.append(f"DOI: [{doi}]({doi_url}).")

    return " ".join(parts)


def _render_refs_in_prose(prose: str, ref_numbers: dict[str, int]) -> str:
    """Rewrite every `[ref:ID,ID,...]` marker in *prose* into
    `[R<n>]`/`[R<n>, R<m>]` linked to that reference's entry in the
    References section, using the already-assigned *ref_numbers* map.
    Each `R<n>` is individually linked; a multi-ID marker is rendered as
    several comma-separated links rather than nested inside one extra
    pair of brackets."""

    def _replace(m: re.Match) -> str:
        ids = [part.strip() for part in m.group(1).split(",") if part.strip()]
        links = [f"[R{ref_numbers[i]}](#r{ref_numbers[i]})" for i in ids if i in ref_numbers]
        return ", ".join(links)

    return _REF_RE.sub(_replace, prose)


def _compute_ref_numbers(
    outline: dict[str, Any], sections: dict[str, dict[str, Any]]
) -> dict[str, int]:
    """Assign R-numbers to every `[ref:...]`-marked ID across the whole
    document, in reading (outline) order, stable across reuse -- the
    same source cited in two different sections keeps one number. Shared
    by `stitch()` (to number the rendered document) and `export_refs()`
    (to number the ref-checker input identically), so the R-numbers a
    human sees in `narrative.md` always match the ones in any refs-check
    report."""
    ref_numbers: dict[str, int] = {}
    for component in outline["components"]:
        section = sections.get(component["slug"])
        if section is None:
            continue
        for ids in _parse_ref_markers(section.get("prose", "")):
            for ref_id in ids:
                if ref_id not in ref_numbers:
                    ref_numbers[ref_id] = len(ref_numbers) + 1
    return ref_numbers


def stitch(seed_work: dict[str, Any], *, base: Path | None = None) -> dict[str, Any]:
    """Assemble the outline order + every drafted section into one
    top-level `wake-out/<seed>/narrative.md`. Always runs, even on
    partial data (missing or still-draft sections) -- same "works on
    partial data, marks coverage" philosophy as `wake bake` -- so the
    output always clearly labels each section as confirmed prose,
    still-draft prose (shown but flagged), or not yet written at all,
    rather than silently omitting or overstating what's actually there.

    Every `[ref:ID,...]` marker across the whole document is renumbered
    to `[R1]`, `[R2]`, ... in reading (outline) order, stable across
    reuse -- the same source cited in two different sections keeps one
    number -- and a Chicago-style "## References" section is appended,
    one entry per distinct ID, in R-order. This renumbering only happens
    here, once the whole document is available; the raw `[ref:...]`
    marker form is preserved in each section's own .json/.md.

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

    ref_numbers = _compute_ref_numbers(outline, sections)

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
            lines.append(_render_refs_in_prose(section["prose"], ref_numbers))
        lines.append("")

    if ref_numbers:
        lines.append("## References")
        lines.append("")
        for ref_id, n in sorted(ref_numbers.items(), key=lambda kv: kv[1]):
            work = _work_metadata_for_ref(ref_id, seed_work, base)
            lines.append(f'<a name="r{n}"></a>{n}. {_chicago_entry(work, ref_id)}')
            lines.append("")

    md_path = narrative_md_path(seed_id, base)
    atomic_write_text(md_path, "\n".join(lines))

    return {
        "ok": True,
        "narrative_path": str(md_path),
        "confirmed_sections": confirmed_count,
        "draft_sections": draft_count,
        "missing_sections": missing,
        "reference_count": len(ref_numbers),
    }


def export_refs(seed_work: dict[str, Any], *, base: Path | None = None) -> dict[str, Any]:
    """Export the stitched narrative's References list to
    `wake-out/<seed>/narrative/refs.json`, in the bare-JSON-array shape
    the external `ref-checker` tool (github.com/rbross-hpc/ref-checker)
    accepts via `ref-checker check --refs-json`.

    This is wake's half of the refs-check integration: producing the
    input file. wake never invokes ref-checker itself -- the agent
    installs it (if not already present) and runs `ref-checker check
    --refs-json <this file> --results-json <sidecar>` as its own
    subprocess, then hands the resulting sidecar to
    `summarize_refs_check()` for a human-facing report.

    R-numbers (the `index` field) are computed the same way `stitch()`
    numbers `[R1]`/`[R2]`/... in the rendered document, so a discrepancy
    ref-checker reports against index N always corresponds to `[RN]` in
    `narrative.md` -- no separate mapping to keep in sync.

    Raises ValueError if no outline has been created yet (same
    precondition as `stitch()`).
    """
    seed_id = seed_work["openalex_id"]
    outline = load_outline(seed_id, base)
    if outline is None:
        raise ValueError(
            f"No narrative outline found for seed {seed_id}. Run `wake narrative outline create` first."
        )

    sections = _load_all_sections(seed_id, base)
    ref_numbers = _compute_ref_numbers(outline, sections)

    refs = []
    for ref_id, n in sorted(ref_numbers.items(), key=lambda kv: kv[1]):
        work = _work_metadata_for_ref(ref_id, seed_work, base)
        entry: dict[str, Any] = {"index": n, "title": (work or {}).get("title") or ""}
        if work is not None:
            if work.get("authors"):
                entry["authors"] = work["authors"]
            if work.get("year"):
                entry["year"] = work["year"]
            if work.get("doi"):
                entry["doi"] = work["doi"]
            if work.get("venue"):
                entry["venue"] = work["venue"]
        refs.append(entry)

    p = refs_json_path(seed_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, refs)

    return {
        "ok": True,
        "refs_json_path": str(p),
        "reference_count": len(refs),
    }


def summarize_refs_check(seed_id: str, results_path: str | Path, *, base: Path | None = None) -> dict[str, Any]:
    """Parse a `ref-checker check --results-json <results_path>` sidecar
    (schema_version 3) and summarize it into a human-facing report: how
    many references are OK / CLOSEST / NO MATCH, and the specific detail
    for every reference that isn't a clean OK, so the human can decide
    whether to fix the citing work's metadata, accept it as a known
    limitation, or investigate further.

    wake never runs ref-checker itself -- this only reads a results file
    the agent already produced by running `ref-checker check` as its own
    subprocess. Raises ValueError if the file doesn't exist or isn't a
    recognizable ref-checker results sidecar.
    """
    p = Path(results_path)
    if not p.exists():
        raise ValueError(
            f"No ref-checker results file found at {p}. Run `ref-checker check "
            f"--refs-json <refs.json> --results-json {p}` first."
        )

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{p} is not valid JSON: {exc}") from exc

    references = data.get("references")
    if not isinstance(references, dict):
        raise ValueError(
            f"{p} doesn't look like a ref-checker results sidecar "
            "(missing top-level 'references' object)."
        )

    clean_ok_count = 0
    flagged: list[dict[str, Any]] = []
    for idx_str, entry in sorted(references.items(), key=lambda kv: int(kv[0])):
        ref = entry.get("ref", {})
        result = entry.get("result", {})
        status = result.get("status", "OTHER")
        year_mismatch_note = result.get("year_mismatch_note")
        id_notes = result.get("id_notes", []) or []
        dead_urls = result.get("dead_urls", []) or []
        exhausted_sources = result.get("exhausted_sources", []) or []

        has_notes = bool(year_mismatch_note or id_notes or dead_urls or exhausted_sources)
        if status == "OK" and not has_notes:
            clean_ok_count += 1
            continue

        # Flagged: anything not a clean, note-free OK -- CLOSEST/NO MATCH/
        # OTHER always, and an OK-status match that still carries a note
        # (year mismatch, DOI-title divergence, a dead URL, or exhausted
        # retries) since the match itself is confirmed but something
        # about it is still worth a human's eye.
        flagged.append({
            "index": ref.get("index", int(idx_str)),
            "title": ref.get("title"),
            "status": status,
            "score": result.get("display_score"),
            "best_source": result.get("best_source"),
            "year_mismatch_note": year_mismatch_note,
            "id_notes": id_notes,
            "dead_urls": dead_urls,
            "exhausted_sources": exhausted_sources,
        })

    return {
        "ok": True,
        "results_path": str(p),
        "total": len(references),
        "ok_count": clean_ok_count,
        "flagged_count": len(flagged),
        "flagged": sorted(flagged, key=lambda e: e["index"]),
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
