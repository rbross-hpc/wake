# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Timeline curation (BACKLOG Theme G).

The agent and human are jointly deciding which citing works are the
"key developments" in the seed paper's story over time, and how to
periodize that story -- an editorial/narrative act, not something wake
can compute on its own. So this module follows the exact same
"candidate material -> curated units -> stitch" pattern as
`wake/narrative.py` and `wake/themes.py`, not `wake/report.py`'s
non-interactive metrics rollup:

  1. Candidates (`wake timeline candidates`) -- a read-only, complete,
     scored view of every dated classified work, grouped into buckets
     (year by default, or an N-year window). This is the material the
     agent reads to decide what's worth highlighting, exactly as it
     reads dossiers/classifications before drafting a narrative section.
     wake scores every work (via `report.relationship_score()` -- never
     a second, drifted formula) but never pre-selects a "top N" or drops
     weak relationships: the editorial threshold stays in the
     conversation between the agent and the human, not baked into a
     config default.

  2. Periods (`wake timeline period create` / `period confirm`) -- the
     curated unit: a named span (agent/human decided the periodization
     up front, e.g. "2003-2007: early adoption") or an emergent
     single-year bucket (a bare year slug, defaulted range) -- both are
     the same JSON shape, so neither mode requires a separate outline
     step. `create_period()` validates every highlighted work is
     classified and not excluded/a confirmed duplicate (same bar
     `wake theme create` enforces) and always writes "draft".
     `confirm_period()` (agent-run, after human sign-off, exactly like
     `wake theme confirm`) refuses unless every highlighted work is
     *currently* human-verified, re-resolved fresh at confirm time --
     a period is an evidentiary claim about what mattered when, so it
     rests on the same verified-evidence bar a theme does, not merely on
     an agent's classification guess. Periods may overlap or leave year
     gaps between them; that's the team's editorial call, never enforced
     or auto-corrected here.

  3. Stitch (`wake timeline stitch`) -- assembles every period
     (chronological by from_year) into `timeline.md` (the working,
     human-readable artifact -- like `narrative.md`) and `timeline.json`
     (the confirmed selection only, structured for handoff to a separate
     Tufte-style graphic-rendering tool). Works on partial data, labeling
     each period confirmed/draft, same "works on partial data, marks
     coverage" philosophy as `wake bake`/`narrative.stitch`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import atomic_write_json, atomic_write_text, now_iso, read_json
from .models import (
    TIMELINE_PERIOD_VERSION,
    TimelinePeriodWrite,
    migrate_period,
)
from .seed import work_dir

_UNCLASSIFIED_STATUS = "unclassified"


def timeline_dir(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "timeline"


def periods_dir(seed_id: str, base: Path | None = None) -> Path:
    return timeline_dir(seed_id, base) / "periods"


def period_json_path(seed_id: str, slug: str, base: Path | None = None) -> Path:
    return periods_dir(seed_id, base) / f"{slug}.json"


def period_md_path(seed_id: str, slug: str, base: Path | None = None) -> Path:
    return periods_dir(seed_id, base) / f"{slug}.md"


def timeline_md_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "timeline.md"


def timeline_json_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "timeline.json"


def load_period(seed_id: str, slug: str, base: Path | None = None) -> dict[str, Any] | None:
    p = period_json_path(seed_id, slug, base)
    if not p.exists():
        return None
    return migrate_period(read_json(p))


def _load_all_periods(seed_id: str, base: Path | None = None) -> dict[str, dict[str, Any]]:
    d = periods_dir(seed_id, base)
    if not d.exists():
        return {}
    periods: dict[str, dict[str, Any]] = {}
    for p in sorted(d.glob("*.json")):
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        entry = migrate_period(entry)
        slug = entry.get("slug", p.stem)
        periods[slug] = entry
    return periods


def _resolve_highlight_status(
    citing_id: str,
    *,
    classified_by_id: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
    seed_id: str,
    base: Path | None,
) -> dict[str, Any]:
    """Resolve one highlighted work's current, honest status -- same
    definition as `themes._resolve_work_status()` (verified iff in
    overrides.jsonl, else proposed iff a dossier exists, else
    provisional, else unclassified), duplicated here rather than
    imported to avoid a themes.py <-> timeline.py import cycle risk and
    because the return shape (TimelineHighlight fields) differs slightly
    from ThemeWork's."""
    from .evidence import dossier_json_path

    classified = classified_by_id.get(citing_id)
    if classified is None:
        return {"citing_id": citing_id, "status": _UNCLASSIFIED_STATUS, "has_dossier": False, "title": None}

    title = classified.get("title")
    has_dossier = dossier_json_path(seed_id, citing_id, base).exists()

    if citing_id in overrides:
        status = "verified"
    elif has_dossier:
        status = "proposed"
    else:
        status = "provisional"

    return {"citing_id": citing_id, "status": status, "has_dossier": has_dossier, "title": title}


def build_candidates(
    seed_work: dict[str, Any],
    *,
    base: Path | None = None,
    bucket_years: int = 1,
    min_strength: float | None = None,
    since: int | None = None,
    until: int | None = None,
) -> dict[str, Any]:
    """Complete, scored, dated view of classified citing works for the
    agent to choose highlights from -- the material `wake timeline period
    create` draws on, exactly as reading dossiers/classifications is what
    `wake narrative section create` draws on.

    Never pre-selects "the milestones": every classified work with a year
    is included, each with `score`/`score_inputs` so the agent (and the
    human, in conversation) can decide the threshold themselves.
    *min_strength* is an optional query-time filter (not a persisted
    decision) for when the agent already knows it wants to ignore weak
    relationships for this pass; omit it to see everything.

    Same full resolution `wake assess`/`wake bake` use: overrides applied
    (verified status wins), confirmed duplicates dropped outright (the
    canonical work already appears in its own right), excluded works
    flagged (kept, not silently hidden, so the agent understands why a
    work it might expect to see is marked unusable) -- so the agent never
    proposes a highlight the packet has already ruled out.

    *bucket_years* groups the periods in `data.buckets` into windows of
    that many years (e.g. 5 -> 2000-2004, 2005-2009, ...), starting from
    the earliest dated classified work's year; 1 (default) is per-year.
    This is purely a query-time view -- it has no bearing on how a period
    is later created; the agent can request a coarser view here to spot
    a shape, then still create a period with whatever from_year/to_year
    it and the human settle on.

    Returns {seed, bucket_years, min_strength, since, until, undated_count,
    excluded_count, duplicate_count, buckets: [{bucket_start, bucket_end,
    count, weighted_intensity, works: [...]}]}, works sorted by score
    descending within each bucket. A work whose classify call errored
    (no "relationship" key) is excluded entirely, same as
    `report.build_metrics`'s classified filter.
    """
    from .classify import load_classified
    from .dedup import load_duplicates
    from .exclude import is_excluded, load_exclusions
    from .report import _score, load_overrides

    oid = seed_work["openalex_id"]
    classified = load_classified(oid, base) or []
    overrides = load_overrides(oid, base)
    duplicates = load_duplicates(oid, base)
    exclusions = load_exclusions(oid, base)

    undated_count = 0
    excluded_count = 0
    duplicate_count = 0
    dated_works: list[dict[str, Any]] = []

    for w in classified:
        cid = w.get("openalex_id")
        if not cid or not w.get("relationship"):
            continue

        excluded = is_excluded(cid, exclusions)
        duplicate = cid in duplicates
        if excluded:
            excluded_count += 1
        if duplicate:
            duplicate_count += 1

        year = w.get("year")
        if not year:
            undated_count += 1
            continue

        score = _score(w)
        if min_strength is not None:
            from .classify import relationship_strength
            strengths = relationship_strength()
            relationships = w.get("relationships")
            if relationships:
                labels = [
                    label for f in relationships
                    if isinstance(f, dict) and isinstance(label := f.get("label"), str)
                ]
                best_strength = max((strengths.get(label, 1) for label in labels), default=1)
            else:
                best_strength = strengths.get(w.get("relationship", "cites"), 1)
            if best_strength < min_strength:
                continue

        status = "verified" if cid in overrides else "provisional"
        dated_works.append({
            "openalex_id": cid,
            "title": w.get("title"),
            "year": int(year),
            "cited_by_count": w.get("cited_by_count", 0),
            "relationship": w.get("relationship"),
            "relationships": w.get("relationships"),
            "confidence": w.get("confidence"),
            "author_overlap": bool(w.get("author_overlap")),
            "verification_status": status,
            "excluded": excluded,
            "duplicate": duplicate,
            "score": round(score, 3),
        })

    if since is not None:
        dated_works = [w for w in dated_works if w["year"] >= since]
    if until is not None:
        dated_works = [w for w in dated_works if w["year"] <= until]

    buckets: dict[int, list[dict[str, Any]]] = {}
    if dated_works:
        min_year = min(w["year"] for w in dated_works)
        for w in dated_works:
            offset = (w["year"] - min_year) // bucket_years
            bucket_start = min_year + offset * bucket_years
            buckets.setdefault(bucket_start, []).append(w)

    buckets_out = []
    for bucket_start in sorted(buckets):
        works = sorted(buckets[bucket_start], key=lambda w: -w["score"])
        buckets_out.append({
            "bucket_start": bucket_start,
            "bucket_end": bucket_start + bucket_years - 1,
            "count": len(works),
            "weighted_intensity": round(sum(w["score"] for w in works), 3),
            "works": works,
        })

    return {
        "seed": {
            "openalex_id": oid,
            "title": seed_work.get("title"),
        },
        "bucket_years": bucket_years,
        "min_strength": min_strength,
        "since": since,
        "until": until,
        "undated_count": undated_count,
        "excluded_count": excluded_count,
        "duplicate_count": duplicate_count,
        "buckets": buckets_out,
    }


def create_period(
    seed_work: dict[str, Any],
    slug: str,
    *,
    highlight_ids: list[str],
    highlight_notes: dict[str, str] | None = None,
    label: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    note: str | None = None,
    base: Path | None = None,
) -> dict[str, Any]:
    """Write (or overwrite) one timeline period: a curated set of
    highlighted citing works, optionally framed with a label/year-range
    and per-highlight/period notes. Always writes period_status "draft"
    -- curating/re-curating is an agent/human judgment, not itself a
    sign-off (same rule as `wake theme create`).

    *slug* may be a bare year (e.g. "2012", an emergent single-year
    period -- from_year/to_year default to that year if not given) or a
    named span (e.g. "early-adoption", in which case at least one of
    from_year/to_year should be given so the period's place on the
    timeline is meaningful). Neither mode is enforced over the other;
    wake persists whatever periodization the team settles on.

    Raises ValueError if highlight_ids is empty, includes a confirmed
    duplicate, includes an excluded work, or includes a work that's
    never been classified (same bars `wake theme create` enforces).

    Writes only the period's JSON sidecar. Does NOT render Markdown --
    run `wake rebuild` after this (see build.py's module docstring).

    Returns {ok, period_path, period_json_path, period_status, highlights,
    rebuild_needed: True}.
    """
    from .classify import load_classified
    from .dedup import load_duplicates
    from .exclude import is_excluded, load_exclusions
    from .report import load_overrides

    seed_id = seed_work["openalex_id"]

    if not highlight_ids:
        raise ValueError("highlight_ids must not be empty.")

    duplicates = load_duplicates(seed_id, base)
    confirmed_duplicates = [cid for cid in highlight_ids if cid in duplicates]
    if confirmed_duplicates:
        pointers = ", ".join(
            f"{cid} (use {duplicates[cid]['canonical_id']} instead)" for cid in confirmed_duplicates
        )
        raise ValueError(
            f"highlight_ids includes confirmed duplicate(s): {pointers}. "
            "Highlight the canonical work instead of a work confirmed to be its duplicate."
        )

    exclusions = load_exclusions(seed_id, base)
    excluded = [cid for cid in highlight_ids if is_excluded(cid, exclusions)]
    if excluded:
        raise ValueError(
            f"highlight_ids includes excluded work(s): {', '.join(excluded)}. "
            "An excluded work has been judged not actually about the seed and "
            "cannot be highlighted -- run `wake unexclude` first if this was a mistake."
        )

    classified = load_classified(seed_id, base) or []
    classified_by_id = {wid: w for w in classified if (wid := w.get("openalex_id"))}
    overrides = load_overrides(seed_id, base)

    highlight_notes = highlight_notes or {}
    highlights: list[dict[str, Any]] = []
    unclassified: list[str] = []
    for cid in highlight_ids:
        resolved = _resolve_highlight_status(
            cid, classified_by_id=classified_by_id, overrides=overrides, seed_id=seed_id, base=base,
        )
        if resolved["status"] == _UNCLASSIFIED_STATUS:
            unclassified.append(cid)
        resolved["note"] = highlight_notes.get(cid)
        highlights.append(resolved)

    if unclassified:
        raise ValueError(
            "The following highlighted works have never been classified: "
            f"{', '.join(unclassified)}. Run `wake classify {seed_id} --ids "
            f"{','.join(unclassified)}` first."
        )

    if from_year is None and to_year is None and slug.isdigit():
        from_year = to_year = int(slug)

    existing = load_period(seed_id, slug, base)
    created_at = existing.get("created_at") if existing else now_iso()

    payload = {
        "schema_version": TIMELINE_PERIOD_VERSION,
        "seed_openalex_id": seed_id,
        "slug": slug,
        "label": label,
        "from_year": from_year,
        "to_year": to_year,
        "note": note,
        "highlights": highlights,
        "period_status": "draft",
        "created_at": created_at,
        "updated_at": now_iso(),
    }

    validated = TimelinePeriodWrite.validate_or_raise(payload, context=f"timeline period {slug!r}")
    payload = validated.to_json_dict()

    d = periods_dir(seed_id, base)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_json(period_json_path(seed_id, slug, base), payload)

    # The period's .md, timeline.md/timeline.json, and README/AGENTS.md
    # are intentionally NOT re-rendered here -- rendering is `wake
    # rebuild`'s job, not a write-time side effect of this JSON write
    # (see build.py's module docstring).
    return {
        "ok": True,
        "period_path": str(period_md_path(seed_id, slug, base)),
        "period_json_path": str(period_json_path(seed_id, slug, base)),
        "period_status": "draft",
        "highlights": highlights,
        "rebuild_needed": True,
    }


def confirm_period(
    seed_work: dict[str, Any],
    slug: str,
    *,
    base: Path | None = None,
) -> dict[str, Any]:
    """Human-approved sign-off promoting a period from "draft" to
    "confirmed" -- run by the agent on the human's behalf, exactly like
    `wake theme confirm`. Refuses unless every highlighted work is
    already "verified" (human-reviewed via `wake override`), re-resolved
    fresh at confirm time (not from the period's own possibly-stale
    JSON) -- a confirmed period is an evidentiary claim about what
    mattered at that point in the seed's story, so it rests on the same
    verified-evidence bar `wake theme confirm` enforces, not merely on
    the agent's own classification guess.

    Writes only the period's JSON sidecar. Does NOT render Markdown --
    run `wake rebuild` after this (see build.py's module docstring).

    Returns {"ok": True, ..., "rebuild_needed": True} on success, or
    {"ok": False, "reason": "unverified_works", "unverified": [...]}
    if blocked.
    """
    from .classify import load_classified
    from .report import load_overrides

    seed_id = seed_work["openalex_id"]
    period = load_period(seed_id, slug, base)
    if period is None:
        raise ValueError(f"No timeline period {slug!r} found for seed {seed_id}. Run `wake timeline period create` first.")

    classified = load_classified(seed_id, base) or []
    classified_by_id = {wid: w for w in classified if (wid := w.get("openalex_id"))}
    overrides = load_overrides(seed_id, base)

    highlight_ids = [h["citing_id"] for h in period["highlights"]]
    notes_by_id = {h["citing_id"]: h.get("note") for h in period["highlights"]}
    refreshed = []
    for cid in highlight_ids:
        resolved = _resolve_highlight_status(
            cid, classified_by_id=classified_by_id, overrides=overrides, seed_id=seed_id, base=base,
        )
        resolved["note"] = notes_by_id.get(cid)
        refreshed.append(resolved)
    unverified = [h["citing_id"] for h in refreshed if h["status"] != "verified"]

    if unverified:
        return {
            "ok": False,
            "reason": "unverified_works",
            "unverified": unverified,
            "message": (
                f"Cannot confirm period {slug!r}: {len(unverified)} of "
                f"{len(highlight_ids)} highlighted work(s) are not yet human-verified: "
                f"{', '.join(unverified)}. Run `wake evidence` + `wake override` "
                "on each first, then re-run `wake timeline period confirm`."
            ),
        }

    period["period_status"] = "confirmed"
    period["confirmed_at"] = now_iso()
    period["updated_at"] = now_iso()
    period["highlights"] = refreshed

    validated = TimelinePeriodWrite.validate_or_raise(period, context=f"timeline period {slug!r}")
    period = validated.to_json_dict()
    atomic_write_json(period_json_path(seed_id, slug, base), period)

    return {
        "ok": True,
        "period_path": str(period_md_path(seed_id, slug, base)),
        "period_json_path": str(period_json_path(seed_id, slug, base)),
        "period_status": "confirmed",
        "rebuild_needed": True,
    }


def _period_sort_key(period: dict[str, Any]) -> tuple[int, str]:
    """Chronological order for stitch(): by from_year (undated periods,
    which shouldn't normally occur since create_period defaults a
    numeric slug's range, sort last), then by slug for a stable
    tie-break."""
    from_year = period.get("from_year")
    return (from_year if from_year is not None else 10**9, period.get("slug", ""))


def _detect_overlaps(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report (never enforce) pairs of periods whose [from_year, to_year]
    ranges overlap -- periodization is the team's editorial call; wake
    only surfaces it so the agent can raise it with the human, exactly
    as it would any other judgment call."""
    ranged = [
        p for p in periods
        if p.get("from_year") is not None and p.get("to_year") is not None
    ]
    overlaps = []
    for i, a in enumerate(ranged):
        for b in ranged[i + 1:]:
            if a["from_year"] <= b["to_year"] and b["from_year"] <= a["to_year"]:
                overlaps.append({"a": a["slug"], "b": b["slug"]})
    return overlaps


def _render_period_markdown(seed_work: dict[str, Any], period: dict[str, Any]) -> str:
    lines: list[str] = []
    title = period.get("label") or period["slug"]
    lines.append("---")
    lines.append("type: timeline-period")
    lines.append(f'title: "{title}"')
    lines.append(f"seed_openalex_id: {seed_work.get('openalex_id', '')}")
    lines.append(f"slug: {period['slug']}")
    if period.get("from_year") is not None:
        lines.append(f"from_year: {period['from_year']}")
    if period.get("to_year") is not None:
        lines.append(f"to_year: {period['to_year']}")
    lines.append(f"period_status: {period.get('period_status', 'draft')}")
    lines.append(f"generated_at: {now_iso()}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    if period.get("from_year") is not None or period.get("to_year") is not None:
        fy = period.get("from_year")
        ty = period.get("to_year")
        span = f"{fy}" if fy == ty else f"{fy}\u2013{ty}"
        lines.append(f"*{span}*")
        lines.append("")
    status = period.get("period_status", "draft")
    lines.append(f"**Status:** {'Confirmed' if status == 'confirmed' else 'Draft'}")
    lines.append("")
    if period.get("note"):
        lines.append(period["note"])
        lines.append("")
    lines.append("## Highlights")
    lines.append("")
    for h in period.get("highlights", []):
        tag = "[VERIFIED]" if h.get("status") == "verified" else f"[{(h.get('status') or 'unclassified').upper()}]"
        line = f"- {tag} **{h.get('title') or h['citing_id']}** ({h['citing_id']})"
        lines.append(line)
        if h.get("note"):
            lines.append(f"  {h['note']}")
    lines.append("")
    return "\n".join(lines)


def rerender_all_periods(seed_id: str, seed_work: dict[str, Any], base: Path | None = None) -> list[str]:
    """Re-emit every timeline period's .md from its .json sidecar --
    rendering only, no change to any period's own status/highlights.
    Used by `wake rebuild` (see build.py's module docstring)."""
    d = periods_dir(seed_id, base)
    if not d.exists():
        return []
    rendered = []
    for p in sorted(d.glob("*.json")):
        try:
            period = migrate_period(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
        md = _render_period_markdown(seed_work, period)
        md_path = period_md_path(seed_id, period.get("slug", p.stem), base)
        atomic_write_text(md_path, md)
        rendered.append(period.get("slug", p.stem))
    return rendered


def stitch(seed_work: dict[str, Any], *, base: Path | None = None) -> dict[str, Any]:
    """Assemble every timeline period (chronological by from_year) into
    `timeline.md` (the working, human-readable artifact -- like
    `narrative.md`) and `timeline.json` (the CONFIRMED selection only,
    structured for handoff to a separate graphic-rendering tool).

    Works on partial data, same "works on partial data, marks coverage"
    philosophy as `wake bake`/`narrative.stitch`: draft periods are
    included in `timeline.md`, clearly labeled, but never in
    `timeline.json` -- a period only enters the handoff once a human has
    confirmed it rests on verified evidence (see confirm_period()).

    Overlapping period ranges are reported (`overlaps` in the return
    value and a callout in timeline.md) but never blocked or
    auto-corrected -- periodization is the team's editorial call.

    Does NOT refresh README.md/AGENTS.md wiki orientation -- run `wake
    rebuild` for that (see build.py's module docstring).

    Returns {ok, timeline_path, timeline_json_path, confirmed_count,
    draft_count, overlaps}. ok is False (no files written) if there are
    no periods at all yet.
    """
    seed_id = seed_work["openalex_id"]
    periods = list(_load_all_periods(seed_id, base).values())

    if not periods:
        return {
            "ok": False,
            "message": f"No timeline periods found for seed {seed_id}. Run `wake timeline period create` first.",
        }

    periods.sort(key=_period_sort_key)
    overlaps = _detect_overlaps(periods)

    confirmed = [p for p in periods if p.get("period_status") == "confirmed"]
    draft = [p for p in periods if p.get("period_status") != "confirmed"]

    title = seed_work.get("title") or seed_id
    generated_at = now_iso()

    lines: list[str] = []
    lines.append("---")
    lines.append("type: timeline")
    lines.append(f'title: "Timeline: {title}"')
    lines.append(f"seed_openalex_id: {seed_id}")
    lines.append(f"confirmed_periods: {len(confirmed)}")
    lines.append(f"draft_periods: {len(draft)}")
    lines.append(f"timestamp: {generated_at}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Timeline: {title}")
    lines.append("")
    lines.append(f"*Assembled by wake on {generated_at}*")
    lines.append("")
    if overlaps:
        pairs = ", ".join(f"{o['a']} / {o['b']}" for o in overlaps)
        lines.append(f"> **Note:** overlapping period ranges: {pairs}.")
        lines.append("")

    for period in periods:
        period_title = period.get("label") or period["slug"]
        status = period.get("period_status", "draft")
        tag = "" if status == "confirmed" else " *(draft)*"
        fy, ty = period.get("from_year"), period.get("to_year")
        span = ""
        if fy is not None or ty is not None:
            span = f" ({fy})" if fy == ty else f" ({fy}\u2013{ty})"
        lines.append(f"## {period_title}{span}{tag}")
        lines.append("")
        if period.get("note"):
            lines.append(period["note"])
            lines.append("")
        for h in period.get("highlights", []):
            h_tag = "[VERIFIED]" if h.get("status") == "verified" else f"[{(h.get('status') or 'unclassified').upper()}]"
            lines.append(f"- {h_tag} **{h.get('title') or h['citing_id']}** ({h['citing_id']})")
            if h.get("note"):
                lines.append(f"  {h['note']}")
        lines.append("")

    md_text = "\n".join(lines)

    confirmed_json = {
        "seed_openalex_id": seed_id,
        "seed_title": seed_work.get("title"),
        "generated_at": generated_at,
        "periods": [
            {
                "slug": p["slug"],
                "label": p.get("label"),
                "from_year": p.get("from_year"),
                "to_year": p.get("to_year"),
                "note": p.get("note"),
                "highlights": [
                    {
                        "citing_id": h["citing_id"],
                        "title": h.get("title"),
                        "note": h.get("note"),
                    }
                    for h in p.get("highlights", [])
                ],
            }
            for p in confirmed
        ],
        "overlaps": overlaps,
    }

    wd = timeline_dir(seed_id, base).parent
    wd.mkdir(parents=True, exist_ok=True)
    md_path = timeline_md_path(seed_id, base)
    json_path = timeline_json_path(seed_id, base)
    atomic_write_text(md_path, md_text)
    atomic_write_json(json_path, confirmed_json)

    return {
        "ok": True,
        "timeline_path": str(md_path),
        "timeline_json_path": str(json_path),
        "confirmed_count": len(confirmed),
        "draft_count": len(draft),
        "overlaps": overlaps,
    }
