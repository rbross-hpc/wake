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
    return work_dir(seed_id, base) / ".overrides.jsonl"


def load_overrides(seed_id: str, base: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load human-reviewed overrides, keyed by citing OpenAlex ID.

    Later entries for the same ID win (append-only log; last write wins).
    """
    p = overrides_path(seed_id, base)
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
) -> dict[str, Any]:
    """Append a human-reviewed override for a citing work's relationship."""
    entry = {
        "citing_id": citing_id,
        "relationship": relationship,
        "justification": justification,
        "confidence": 1.0,
        "human_reviewed": True,
        "strength": RELATIONSHIP_STRENGTH.get(relationship, 1),
        "overridden_at": now_iso(),
    }
    p = overrides_path(seed_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


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


def _score(work: dict) -> float:
    """Rank score: relationship strength × log(1 + downstream cited_by_count)."""
    import math
    strength = work.get("strength", 1)
    downstream = work.get("cited_by_count", 0) or 0
    return strength * math.log1p(downstream)


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
    rendered brief.
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

    for w in citing_works:
        yr = w.get("year")
        if yr:
            by_year[int(yr)] += 1
        vt = w.get("venue_type") or "unknown"
        by_venue_type[vt] += 1
        for field in w.get("topics", []):
            by_field[field] += 1
        if (w.get("cited_by_count") or 0) >= high_cited_thresh:
            highly_cited += 1
        if not w.get("has_abstract"):
            no_abstract += 1

    by_relationship: dict[str, int] = Counter()
    for w in classified:
        rel = w.get("relationship", "background-mention")
        by_relationship[rel] += 1

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
        "coverage": round(coverage, 4),
        "highly_cited_citing": highly_cited,
        "no_abstract_count": no_abstract,
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
                "score": round(_score(w), 3),
            }
            for w in top_evidence
        ],
    }


def render_markdown(
    seed_work: dict[str, Any],
    metrics: dict[str, Any],
) -> str:
    """Render the impact brief as a Markdown string."""
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
    lines.append(f"- **{total:,}** works cite this paper")
    if highly_cited:
        lines.append(f"- **{highly_cited:,}** of those are themselves highly cited (≥50 citations)")
    if no_abstract:
        lines.append(f"- {no_abstract:,} citing works lack an abstract (classified from title/venue only)")
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
        reviewed_tag = " (human-reviewed)" if ev.get("human_reviewed") else ""
        lines.append(f"> *{rel}*{reviewed_tag} (confidence: {conf:.2f}) — {just}")
        if ev.get("doi"):
            lines.append(f"> DOI: {ev['doi']}")
        elif ev.get("openalex_id"):
            lines.append(f"> OpenAlex: {ev['openalex_id']}")
        lines.append("")

    return "\n".join(lines)


def render_and_save(
    seed_work: dict[str, Any],
    citing_works: list[dict[str, Any]],
    *,
    base: Path | None = None,
    verbose: bool = True,
    apply_human_overrides: bool = True,
) -> tuple[Path, Path]:
    """Build metrics, render markdown, write impact.json + impact.md.

    *citing_works* may be the full set (some possibly unclassified — the
    brief will note partial coverage) or a pre-filtered subset. Human
    overrides from .overrides.jsonl are applied unless disabled.

    Returns (json_path, md_path).
    """
    seed_id = seed_work["openalex_id"]
    wd = work_dir(seed_id, base)
    wd.mkdir(parents=True, exist_ok=True)

    if verbose:
        print("[wake] Building impact report...", file=sys.stderr)

    works = citing_works
    if apply_human_overrides:
        overrides = load_overrides(seed_id, base)
        works = apply_overrides(works, overrides)

    metrics = build_metrics(seed_work, works)
    md_text = render_markdown(seed_work, metrics)

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
