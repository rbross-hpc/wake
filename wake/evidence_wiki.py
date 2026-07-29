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
from .seed import work_dir

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


def wiki_home_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "README.md"


def _score(entry: dict[str, Any]) -> float:
    """Rank score for a dossier .json sidecar. Delegates to
    report.relationship_score() -- the single source of truth for this
    formula -- so the impact brief's "Strongest Evidence" ranking and this
    wiki's Verified/Pending Review ranking can never silently drift apart.
    Prefers the multi-facet "relationships" list when present (see
    evidence.py's multi-facet schema), falling back to the legacy
    "relationship" scalar."""
    from .report import relationship_score

    proposed = entry.get("proposed", {})
    relationships = proposed.get("relationships") or proposed.get("relationship", "background-mention")
    return relationship_score(relationships, entry.get("citing_cited_by_count", 0))


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
            proposed = e.get("proposed", {})
            facets = proposed.get("relationships") or [{"label": proposed.get("relationship", "?")}]
            rel = ", ".join(f["label"] for f in facets)
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
    override` call, matched against the dossier's `proposed.relationships`
    facets (see evidence.py's multi-facet schema):

      - If it matches an existing facet's label, that facet is flagged
        `"verified": true` -- the model's *other* facets are left in
        place, untouched, as unaffirmed-but-still-evidenced alternative
        readings (a paper can genuinely be both `uses-as-tool` and
        `applies-to-domain`; the human affirming one doesn't make the
        other one wrong, just unconfirmed).
      - If it matches no existing facet (the human corrected the model
        to a reading it never proposed), a new facet is appended with
        `"verified": true` -- the model's original facets are preserved
        untouched here too, since they're still real readings of the
        text, just not the one the human is affirming.
      - If *relationship* is None (a plain accept, no override
        `--relationship` divergence), the model's own top (most
        confident) facet is marked verified as-is.

    The legacy `proposed.relationship`/`confidence`/`justification`
    scalars (read by evidence_wiki._score, rebuild_index's display line,
    and any pre-multi-facet consumer) are updated to describe whichever
    facet ends up flagged verified, since that's now the dossier's
    authoritative reading.

    Returns False (no-op) if no dossier exists for this citing work —
    e.g. a plain human-judgment override with no `wake evidence` behind
    it has nothing to mark.
    """
    import copy
    from .evidence import dossier_json_path, _normalize_proposed_relationships

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
    facets = _normalize_proposed_relationships(proposed, payload.get("quotes", []))
    model_top_label = facets[0]["label"]
    # Snapshot before mutation, so mark_pending() can restore the model's
    # original facets list byte-for-byte when reverting a correction --
    # analogous to the old single-label model_relationship/
    # model_justification pair, but for the whole facets list.
    model_facets_snapshot = copy.deepcopy(facets)

    for f in facets:
        f.setdefault("verified", False)

    corrected = relationship is not None and relationship != model_top_label
    if relationship is None:
        facets[0]["verified"] = True
        verified_facet = facets[0]
    else:
        match = next((f for f in facets if f["label"] == relationship), None)
        if match is not None:
            match["verified"] = True
            verified_facet = match
        else:
            verified_facet = {
                "label": relationship,
                "confidence": 1.0,
                "justification": justification or "(human correction)",
                "quotes": [],
                "verified": True,
            }
            facets.append(verified_facet)

    proposed["relationships"] = facets
    proposed["relationship"] = verified_facet["label"]
    proposed["confidence"] = verified_facet["confidence"]
    proposed["justification"] = verified_facet["justification"]

    if corrected:
        proposed["model_relationship"] = model_top_label
        proposed["model_justification"] = model_facets_snapshot[0]["justification"]
        proposed["model_relationships"] = model_facets_snapshot
        payload["human_verification"]["corrected_from"] = model_top_label

    atomic_write_text(json_path, json.dumps(payload, indent=2, default=str))

    # Full re-render, not the old targeted string replace: the dossier's
    # proposed-facets structure may have changed shape (a new facet
    # appended, or an existing facet's "verified" flag flipped), which a
    # single-line tag/status text replace can't express once there's more
    # than one facet. rerender_dossier_md() reads the JSON sidecar we
    # just wrote and re-derives the whole .md from it -- tags, per-facet
    # sections, and (via finding["human_verification"], which now
    # includes "corrected_from" when applicable) the status block too.
    if dossier_path(seed_id, citing_id, base).exists():
        from .evidence import rerender_dossier_md
        from .seed import load_seed
        seed_work = load_seed(seed_id, base) or {"openalex_id": seed_id}
        rerender_dossier_md(seed_work, citing_id, base=base)

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
    facets (`mark_verified` snapshotted the pre-correction facets list
    into `proposed.model_relationships`), that correction is undone too --
    `proposed.relationships` (and the legacy scalars derived from its top
    facet) are restored to the model's own original reading, since the
    human's corrected reading is exactly the judgment being reverted.
    `human_verification` is removed entirely (it's the record of a human
    sign-off that no longer stands). If the verification was a plain
    accept (no correction, no facets appended/removed), only the
    per-facet "verified" flags are cleared -- there's nothing to restore
    because nothing was replaced.

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
    model_facets = proposed.pop("model_relationships", None)
    proposed.pop("model_relationship", None)
    proposed.pop("model_justification", None)
    was_corrected = model_facets is not None
    if was_corrected:
        for f in model_facets:
            f["verified"] = False
        proposed["relationships"] = model_facets
        proposed["relationship"] = model_facets[0]["label"]
        proposed["confidence"] = model_facets[0]["confidence"]
        proposed["justification"] = model_facets[0]["justification"]
    else:
        for f in proposed.get("relationships", []) or []:
            f["verified"] = False

    atomic_write_text(json_path, json.dumps(payload, indent=2, default=str))

    # Full re-render (see mark_verified()'s comment on why a targeted
    # string replace can't safely express a facets-list-shaped change).
    if dossier_path(seed_id, citing_id, base).exists():
        from .evidence import rerender_dossier_md
        from .seed import load_seed
        seed_work = load_seed(seed_id, base) or {"openalex_id": seed_id}
        rerender_dossier_md(seed_work, citing_id, base=base)

        if reason:
            # rerender_dossier_md's pending-status block doesn't know
            # about *reason* (unverify-specific context, not part of the
            # dossier's own persisted state) -- append it after the fact
            # via the same structural marker replace the old code used.
            md_path = dossier_path(seed_id, citing_id, base)
            md_text = md_path.read_text(encoding="utf-8")
            m = _STATUS_SECTION_RE.search(md_text)
            if m:
                annotated = m.group(0).replace(
                    "— see SKILL.md.",
                    f"— see SKILL.md. (A prior verification was reverted: {reason})",
                )
                md_text = md_text[:m.start()] + annotated + md_text[m.end():]
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


def rebuild_wiki_home(seed_id: str, seed_work: dict[str, Any] | None = None, base: Path | None = None) -> Path:
    """Regenerate `wake-out/<seed>/README.md`, the wiki's single entry
    point: a minimal navigation page linking out to the four top-level
    artifacts (impact brief, narrative, evidence wiki, themes), each with
    a one-line count, and omitted entirely if its target doesn't exist
    yet. Like every other wiki file here, this is a derived view --
    recomputed from whatever's currently on disk, never itself a source
    of truth -- so it's always safe to regenerate and never goes stale in
    a way a fresh call can't fix.

    Called as a side effect of the commands that create the artifacts it
    links to (`wake bake`, `wake evidence`, `wake theme create`/`confirm`,
    `wake narrative stitch`, `wake override`) -- no separate command
    needed, same pattern as index.md/log.md/themes/index.md.
    """
    from .narrative import narrative_md_path

    wd = work_dir(seed_id, base)
    p = wiki_home_path(seed_id, base)

    title = (seed_work or {}).get("title") or seed_id
    doi = (seed_work or {}).get("doi")
    year = (seed_work or {}).get("year")
    authors = (seed_work or {}).get("authors") or []
    author_str = ", ".join(authors[:5]) + (" et al." if len(authors) > 5 else "")

    lines: list[str] = []
    lines.append("---")
    lines.append("type: wiki-home")
    lines.append(f'title: "Wake Wiki: {title}"')
    lines.append(f"timestamp: {now_iso()}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    meta_parts = [str(year) if year else "", f"DOI: {doi}" if doi else "", f"OpenAlex: {seed_id}"]
    lines.append(f"**{' · '.join(mp for mp in meta_parts if mp)}**")
    if author_str:
        lines.append(f"*{author_str}*")
    lines.append("")

    if (wd / "impact.md").exists():
        lines.append("- **[Impact Brief](impact.md)** — reach metrics, top-cited citing works, ranked evidence")

    if narrative_md_path(seed_id, base).exists():
        lines.append("- **[Narrative](narrative.md)** — assembled prose from confirmed themes")

    dossiers = _load_all_dossiers(seed_id, base)
    if dossiers:
        verified = sum(1 for e in dossiers if e.get("verification_status") == "verified")
        pending = len(dossiers) - verified
        lines.append(
            f"- **[Evidence Wiki](evidence/index.md)** — every full-text-verified "
            f"citing work ({verified} verified / {pending} pending)"
        )

    all_themes = _load_all_themes(seed_id, base)
    if all_themes:
        confirmed = sum(1 for t in all_themes if t.get("theme_status") == "confirmed")
        draft_n = len(all_themes) - confirmed
        lines.append(
            f"- **[Themes](evidence/themes/index.md)** — combined-evidence "
            f"thematic docs ({confirmed} confirmed / {draft_n} draft)"
        )

    if dossiers:
        lines.append("- **[Log](evidence/log.md)** — chronological history of all evidence investigations")

    lines.append("")

    atomic_write_text(p, "\n".join(lines))
    return p
