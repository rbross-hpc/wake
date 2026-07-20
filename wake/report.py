# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Assemble impact brief (impact.md + impact.json) from classified citing works."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import config
from .classify import RELATIONSHIP_STRENGTH
from .io import atomic_write_json, atomic_write_text, now_iso, read_json
from .seed import work_dir
from .state import mark_stage_complete

_STAGE = "report"


def overrides_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "overrides.jsonl"


def _legacy_overrides_path(seed_id: str, base: Path | None = None) -> Path:
    """Pre-rename dotfile location. A working directory the human is
    explicitly expected to inspect shouldn't hide the human's own
    verification decisions behind a dotfile convention meant for
    user-home/config directories. Kept only for one release's worth of
    read-compat with packets built before the rename; see
    `_migrate_legacy_overrides_if_needed`."""
    return work_dir(seed_id, base) / ".overrides.jsonl"


def _migrate_legacy_overrides_if_needed(seed_id: str, base: Path | None = None) -> None:
    """Rename `.overrides.jsonl` -> `overrides.jsonl` in place the first
    time this seed's overrides are written to after the rename. No-op if
    the new-named file already exists (never overwrites) or if there's
    nothing to migrate."""
    new_path = overrides_path(seed_id, base)
    old_path = _legacy_overrides_path(seed_id, base)
    if old_path.exists() and not new_path.exists():
        old_path.rename(new_path)


def load_overrides(seed_id: str, base: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load human-reviewed overrides, keyed by citing OpenAlex ID.

    Later entries for the same ID win (append-only log; last write wins).
    Reads the current `overrides.jsonl` name; falls back to the
    pre-rename `.overrides.jsonl` dotfile if the new name doesn't exist
    yet (a packet built before the rename that hasn't had a fresh
    `wake override` call to trigger migration). This is read-only
    compat -- migration to the new filename happens in `add_override`,
    the write path, not here.
    """
    p = overrides_path(seed_id, base)
    if not p.exists():
        p = _legacy_overrides_path(seed_id, base)
        if not p.exists():
            return {}
    overrides: dict[str, dict[str, Any]] = {}
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
                overrides[cid] = entry
    return overrides


def add_override(
    seed_id: str,
    citing_id: str,
    *,
    relationship: str,
    justification: str = "",
    base: Path | None = None,
    verification_source: str = "human-judgment",
    seed_title: str | None = None,
) -> dict[str, Any]:
    """Append a human-reviewed override for a citing work's relationship.

    This is the only path by which a classification is promoted to
    "verified" — an agent calls this on the human's behalf after the human
    has reviewed and accepted a relationship (see BACKLOG.md's provisional
    -> proposed -> verified lifecycle). *verification_source* distinguishes
    how the human arrived at their judgment:
      - "human-judgment": a plain manual correction, no wake evidence dossier
      - "evidence-dossier": the human accepted a full-text reading proposed
        by `wake evidence` (quoted, page-cited passages)

    When *verification_source* is "evidence-dossier", also patches the
    matching evidence dossier (pending-human-review -> verified) and
    updates the evidence wiki's index.md/log.md (BACKLOG Theme D). A
    plain "human-judgment" override has no dossier behind it and leaves
    the evidence wiki untouched.
    """
    entry = {
        "citing_id": citing_id,
        "relationship": relationship,
        "justification": justification,
        "confidence": 1.0,
        "human_reviewed": True,
        "verification_status": "verified",
        "verification_source": verification_source,
        "strength": RELATIONSHIP_STRENGTH.get(relationship, 1),
        "overridden_at": now_iso(),
    }
    _migrate_legacy_overrides_if_needed(seed_id, base)
    p = overrides_path(seed_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    if verification_source == "evidence-dossier":
        from .evidence_wiki import append_log_entry, mark_verified, rebuild_index
        if mark_verified(
            seed_id, citing_id, justification=justification,
            relationship=relationship, base=base,
        ):
            append_log_entry(
                seed_id, event="verified_by_human", citing_id=citing_id,
                detail=f"-> {relationship}", seed_title=seed_title, base=base,
            )
            rebuild_index(seed_id, seed_title=seed_title, base=base)

    return entry


def remove_override(seed_id: str, citing_id: str, *, base: Path | None = None) -> bool:
    """Remove every entry for *citing_id* from `overrides.jsonl` -- used by
    `wake unverify` to undo a mistaken verification.

    Unlike `exclude.py`/`dedup.py`'s reversal pattern (an explicit
    `"excluded": false`/rejection entry appended to the same append-only
    log), there's no "not verified" override entry shape to append here --
    the only way a citing work stops being verified is for it to have no
    override on file at all. So this rewrites the log with every prior
    entry for that ID removed, rather than appending a new one. This
    matches what the original ad hoc recovery this session actually did
    (a manual backup-and-restore of the whole file).

    Migrates a legacy `.overrides.jsonl` dotfile first, same as
    `add_override`, so the rewritten file always lands at the current
    name.

    Returns True if at least one entry existed and was removed, False if
    *citing_id* had no override to remove (nothing to undo).
    """
    _migrate_legacy_overrides_if_needed(seed_id, base)
    p = overrides_path(seed_id, base)
    if not p.exists():
        return False

    remaining: list[str] = []
    removed = False
    with open(p, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                remaining.append(stripped)
                continue
            if entry.get("citing_id") == citing_id:
                removed = True
                continue
            remaining.append(stripped)

    if not removed:
        return False

    text = "\n".join(remaining) + ("\n" if remaining else "")
    atomic_write_text(p, text)
    return True


def apply_overrides(
    classified: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge human overrides into classified works; overrides win."""
    if not overrides:
        return classified
    result = []
    for w in classified:
        cid = w.get("openalex_id")
        if cid in overrides:
            merged = {**w, **overrides[cid]}
            result.append(merged)
        else:
            result.append(w)
    return result


def relationship_score(relationship: str, cited_by_count: int | None, *, strength: int | None = None) -> float:
    """Single source of truth for the ranking formula used both for the
    impact brief's "Strongest Evidence" (this module) and the evidence
    wiki's index.md ranking (evidence_wiki.py) -- relationship strength x
    log(1 + downstream cited_by_count).

    *strength* lets a caller that already has a precomputed strength
    (classified works carry a "strength" field) skip the RELATIONSHIP_STRENGTH
    lookup; callers working from a relationship label alone (e.g. an
    evidence dossier, which has no "strength" field of its own) omit it.
    """
    import math
    if strength is None:
        strength = RELATIONSHIP_STRENGTH.get(relationship, 1)
    downstream = cited_by_count or 0
    return strength * math.log1p(downstream)


def _score(work: dict) -> float:
    """Rank score for a classified citing work dict (has "strength" and
    "cited_by_count" fields). See relationship_score() for the formula."""
    return relationship_score(
        work.get("relationship", "background-mention"),
        work.get("cited_by_count", 0),
        strength=work.get("strength", 1),
    )


_OPENALEX_TYPE_TO_VENUE_TYPE = {
    "conference-paper": "conference",
    "article": "journal",
    "book-chapter": "book series",
    "book": "book series",
    "preprint": "repository",
    "dissertation": "thesis",
    "report": "report",
    "peer-review": "journal",
    "conference-abstract": "conference",
    "reference-entry": "reference work",
    "software-paper": "journal",
    "other": "unknown",
}


def _venue_type_or_fallback(work: dict) -> str:
    """Return the work's venue_type, falling back to a mapping from
    OpenAlex's own 'type' field when venue_type is unset.

    OpenAlex's primary_location.source.type (our venue_type) is missing
    for roughly half of works in practice — most commonly conference
    papers, whose venue metadata OpenAlex often doesn't fully populate.
    Its top-level 'type' field is far more reliably populated, so we use
    it as a fallback rather than lumping these into an uninformative
    'unknown' bucket.
    """
    vt = work.get("venue_type")
    if vt:
        return vt
    oa_type = work.get("type")
    return _OPENALEX_TYPE_TO_VENUE_TYPE.get(oa_type, "unknown")


def build_metrics(
    seed_work: dict[str, Any],
    citing_works: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute all aggregated metrics from citing works.

    *citing_works* is the full set of works citing the seed. Reach metrics
    (counts, per-year, venue/field breakdown) are computed over the full
    set. Relationship-based metrics (nature-of-impact breakdown, top
    evidence) are computed only over the subset that has been classified
    (i.e. has a 'relationship' key) — callers building a brief on partial
    data will see an accurate `coverage` fraction and a note in the
    baked brief.
    """
    rpt_cfg = config.report_cfg()
    top_n = rpt_cfg.get("top_evidence_n", 20)
    high_cited_thresh = rpt_cfg.get("high_cited_threshold", 50)

    total = len(citing_works)
    classified = [w for w in citing_works if w.get("relationship")]
    classified_count = len(classified)

    by_year: dict[int, int] = Counter()
    by_venue_type: dict[str, int] = Counter()
    by_field: dict[str, int] = Counter()
    highly_cited = 0
    no_abstract = 0
    backfilled_abstract = 0

    for w in citing_works:
        yr = w.get("year")
        if yr:
            by_year[int(yr)] += 1
        vt = _venue_type_or_fallback(w)
        by_venue_type[vt] += 1
        for field in w.get("topics", []):
            by_field[field] += 1
        if (w.get("cited_by_count") or 0) >= high_cited_thresh:
            highly_cited += 1
        if not w.get("has_abstract"):
            no_abstract += 1
        if w.get("abstract_source"):
            backfilled_abstract += 1

    by_relationship: dict[str, int] = Counter()
    verified_count = 0
    self_extension_count = 0
    for w in classified:
        rel = w.get("relationship", "background-mention")
        by_relationship[rel] += 1
        if w.get("verification_status") == "verified":
            verified_count += 1
        if w.get("author_overlap"):
            self_extension_count += 1

    sorted_works = sorted(classified, key=_score, reverse=True)
    top_evidence = sorted_works[:top_n]

    per_year_sorted = [
        {"year": yr, "count": cnt}
        for yr, cnt in sorted(by_year.items())
    ]

    coverage = (classified_count / total) if total else 0.0

    return {
        "seed_openalex_id": seed_work["openalex_id"],
        "seed_title": seed_work.get("title"),
        "total_citing_works": total,
        "classified_count": classified_count,
        "verified_count": verified_count,
        "self_extension_count": self_extension_count,
        "coverage": round(coverage, 4),
        "highly_cited_citing": highly_cited,
        "no_abstract_count": no_abstract,
        "backfilled_abstract_count": backfilled_abstract,
        "by_year": per_year_sorted,
        "by_relationship": dict(by_relationship),
        "by_venue_type": dict(by_venue_type),
        "top_fields": [
            {"field": f, "count": c}
            for f, c in sorted(by_field.items(), key=lambda x: x[1], reverse=True)[:10]
        ],
        "top_evidence": [
            {
                "openalex_id": w.get("openalex_id"),
                "title": w.get("title"),
                "authors": w.get("authors", [])[:3],
                "year": w.get("year"),
                "venue": w.get("venue"),
                "doi": w.get("doi"),
                "cited_by_count": w.get("cited_by_count", 0),
                "relationship": w.get("relationship"),
                "confidence": w.get("confidence"),
                "justification": w.get("justification"),
                "human_reviewed": bool(w.get("human_reviewed")),
                "verification_status": w.get("verification_status", "provisional"),
                "verification_source": w.get("verification_source"),
                "author_overlap": bool(w.get("author_overlap")),
                "overlapping_authors": w.get("overlapping_authors", []),
                "score": round(_score(w), 3),
            }
            for w in top_evidence
        ],
    }


def bake_markdown(
    seed_work: dict[str, Any],
    metrics: dict[str, Any],
) -> str:
    """Bake the impact brief into a Markdown string."""
    lines: list[str] = []
    title = seed_work.get("title") or "Unknown Paper"
    oid = seed_work.get("openalex_id", "")
    doi = seed_work.get("doi")
    year = seed_work.get("year", "")
    venue = seed_work.get("venue", "")
    authors = seed_work.get("authors", [])
    author_str = ", ".join(authors[:5]) + (" et al." if len(authors) > 5 else "")
    description = seed_work.get("description", "")

    lines.append(f"# Impact Brief: {title}")
    lines.append("")
    meta_parts = [str(year), venue, f"DOI: {doi}" if doi else "", f"OpenAlex: {oid}"]
    lines.append(f"**{' · '.join(p for p in meta_parts if p)}**")
    if author_str:
        lines.append(f"*{author_str}*")
    lines.append("")
    lines.append(f"*Generated by wake on {now_iso()}*")

    total = metrics.get("total_citing_works", 0)
    classified_count = metrics.get("classified_count", total)
    coverage = metrics.get("coverage", 1.0)
    if total and classified_count < total:
        lines.append("")
        lines.append(
            f"> **Partial analysis**: evidence based on {classified_count:,} of "
            f"{total:,} citing works classified ({coverage:.0%} coverage)."
        )

    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## The Contribution")
    lines.append("")
    if description:
        lines.append(description)
    else:
        lines.append("*(description not available — run `wake describe` first)*")
    lines.append("")

    lines.append("## Reach")
    lines.append("")
    total = metrics["total_citing_works"]
    highly_cited = metrics["highly_cited_citing"]
    no_abstract = metrics["no_abstract_count"]
    backfilled = metrics.get("backfilled_abstract_count", 0)
    lines.append(f"- **{total:,}** works cite this paper")
    if highly_cited:
        lines.append(f"- **{highly_cited:,}** of those are themselves highly cited (≥50 citations)")
    if backfilled:
        lines.append(f"- {backfilled:,} abstracts recovered via OSTI/Semantic Scholar backfill (OpenAlex lacked them)")
    if no_abstract:
        lines.append(f"- {no_abstract:,} citing works still lack an abstract (classified from title/venue only)")
    lines.append("")

    by_year = metrics.get("by_year", [])
    if by_year:
        lines.append("### Citations per Year")
        lines.append("")
        lines.append("| Year | Count |")
        lines.append("|------|------:|")
        for entry in by_year:
            lines.append(f"| {entry['year']} | {entry['count']:,} |")
        lines.append("")

    top_fields = metrics.get("top_fields", [])
    if top_fields:
        lines.append("### Top Research Fields")
        lines.append("")
        lines.append("| Field | Citing Works |")
        lines.append("|-------|-------------:|")
        for entry in top_fields[:8]:
            lines.append(f"| {entry['field']} | {entry['count']:,} |")
        lines.append("")

    by_vt = metrics.get("by_venue_type", {})
    if by_vt:
        lines.append("### Venue Types")
        lines.append("")
        lines.append("| Type | Count |")
        lines.append("|------|------:|")
        for vt, cnt in sorted(by_vt.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {vt} | {cnt:,} |")
        lines.append("")

    lines.append("## Nature of Impact")
    lines.append("")
    if classified_count < total:
        lines.append(f"*(based on {classified_count:,} classified works)*")
        lines.append("")
    verified_count = metrics.get("verified_count", 0)
    if classified_count:
        provisional_count = classified_count - verified_count
        lines.append(
            f"> {provisional_count:,} classification(s) are **provisional** "
            f"(abstract-only, not yet checked against full text); "
            f"{verified_count:,} have been **verified** "
            f"(`wake evidence` full-text reading + human sign-off)."
        )
        lines.append("")
    self_extension_count = metrics.get("self_extension_count", 0)
    if self_extension_count:
        lines.append(
            f"> {self_extension_count:,} of these are the seed's own team "
            "publishing a follow-on/extension (author overlap with the "
            "seed paper), not independent third-party adoption."
        )
        lines.append("")
    by_rel = metrics.get("by_relationship", {})
    relationship_order = [
        "extends", "builds-on", "uses-as-tool", "benchmarks",
        "applies-to-domain", "related-infrastructure", "background-mention",
    ]
    lines.append("| Relationship | Count | % |")
    lines.append("|---|---:|---:|")
    for rel in relationship_order:
        cnt = by_rel.get(rel, 0)
        pct = 100.0 * cnt / classified_count if classified_count else 0.0
        lines.append(f"| {rel} | {cnt:,} | {pct:.1f}% |")
    lines.append("")

    lines.append("## Strongest Evidence")
    lines.append("")
    lines.append(
        "Ranked by relationship strength × downstream influence "
        "(log of citing-work's own cited-by count)."
    )
    lines.append("")

    for i, ev in enumerate(metrics.get("top_evidence", []), 1):
        ev_authors = ev.get("authors", [])
        author_tag = ev_authors[0].split()[-1] if ev_authors else "Unknown"
        lines.append(
            f"**{i}. {ev.get('title', 'Unknown')}** — "
            f"{author_tag} et al., {ev.get('year', '?')} "
            f"| {ev.get('cited_by_count', 0):,} citations"
        )
        rel = ev.get("relationship", "?")
        conf = ev.get("confidence", 0)
        just = ev.get("justification", "")
        status = ev.get("verification_status", "provisional")
        if status == "verified":
            source = ev.get("verification_source")
            if source == "evidence-dossier":
                status_tag = " [VERIFIED via full-text reading]"
            else:
                status_tag = " [VERIFIED via human judgment]"
        else:
            status_tag = " [PROVISIONAL — abstract-only, not yet checked against full text]"
        if ev.get("author_overlap"):
            status_tag += " [SELF-EXTENSION — seed's own team]"
        lines.append(f"> *{rel}*{status_tag} (confidence: {conf:.2f}) — {just}")
        if ev.get("doi"):
            lines.append(f"> DOI: {ev['doi']}")
        elif ev.get("openalex_id"):
            lines.append(f"> OpenAlex: {ev['openalex_id']}")
        lines.append("")

    return "\n".join(lines)


def bake_and_save(
    seed_work: dict[str, Any],
    citing_works: list[dict[str, Any]],
    *,
    base: Path | None = None,
    verbose: bool = True,
    apply_human_overrides: bool = True,
) -> tuple[Path, Path]:
    """Build metrics, bake markdown, write impact.json + impact.md.

    *citing_works* may be the full set (some possibly unclassified — the
    brief will note partial coverage) or a pre-filtered subset. Human
    overrides from overrides.jsonl are applied unless disabled.

    Returns (json_path, md_path).
    """
    seed_id = seed_work["openalex_id"]
    wd = work_dir(seed_id, base)
    wd.mkdir(parents=True, exist_ok=True)

    if verbose:
        print("[wake] Building impact report...", file=sys.stderr)

    from .dedup import load_duplicates
    from .exclude import is_excluded, load_exclusions

    works = citing_works
    if apply_human_overrides:
        overrides = load_overrides(seed_id, base)
        works = apply_overrides(works, overrides)

    duplicates = load_duplicates(seed_id, base)
    if duplicates:
        # A confirmed duplicate is excluded outright rather than merged
        # into its canonical's entry -- the canonical work is already in
        # `works` in its own right (it's a real citing ID, just like the
        # duplicate), so dropping the duplicate is sufficient to avoid
        # double-counting reach metrics without needing to reconcile two
        # different relationship classifications into one.
        works = [w for w in works if w.get("openalex_id") not in duplicates]

    exclusions = load_exclusions(seed_id, base)
    if exclusions:
        works = [w for w in works if not is_excluded(w.get("openalex_id"), exclusions)]

    metrics = build_metrics(seed_work, works)
    md_text = bake_markdown(seed_work, metrics)

    json_path = wd / "impact.json"
    md_path = wd / "impact.md"

    atomic_write_json(json_path, metrics)
    atomic_write_text(md_path, md_text)

    mark_stage_complete(wd, _STAGE, seed_id=seed_id)

    if verbose:
        print(f"[wake] Report written:", file=sys.stderr)
        print(f"  {md_path}", file=sys.stderr)
        print(f"  {json_path}", file=sys.stderr)

    return json_path, md_path
