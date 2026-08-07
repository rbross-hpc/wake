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
from pathlib import Path
from typing import Any

from .evidence import dossier_json_path, evidence_dir
from .io import atomic_write_text, now_iso
from .models import EvidenceDossier
from .seed import work_dir


def index_path(seed_id: str, base: Path | None = None) -> Path:
    return evidence_dir(seed_id, base) / "index.md"


def log_path(seed_id: str, base: Path | None = None) -> Path:
    return evidence_dir(seed_id, base) / "log.md"


def themes_index_path(seed_id: str, base: Path | None = None) -> Path:
    return evidence_dir(seed_id, base) / "themes" / "index.md"


def wiki_home_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "README.md"


def agents_md_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "AGENTS.md"


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

    Links to the dossier markdown when a dossier exists for this citing
    work (successful builds, verifications) -- checked via the JSON
    sidecar, not the .md itself, since rendering is a separate explicit
    step (`wake rebuild`) and a dossier freshly built/verified in this
    same call legitimately has JSON but no .md yet (see build.py's
    module docstring); the link still points at the eventual .md
    filename, which will resolve once rendered. Failed investigations
    (no PDF found, extraction failed) have no dossier JSON at all, so
    the citing ID is left as plain text instead of a link.

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
    has_dossier = dossier_json_path(seed_id, citing_id, base).exists()
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
    """Patch an existing dossier's JSON sidecar from pending-human-review
    to verified, recording the human's justification and timestamp. Does
    not touch the dossier's .md -- rendering is `wake rebuild`'s job now,
    not a write-time side effect (see build.py's module docstring).

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

    from .evidence import _normalize_proposed_relationships, dossier_json_path

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
    # A fresh verification supersedes whatever reason a prior
    # mark_pending() revert recorded -- see EvidenceDossier.pending_reason.
    payload.pop("pending_reason", None)

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

    EvidenceDossier.validate_or_raise(payload, context=f"evidence dossier {citing_id!r}")
    atomic_write_text(json_path, json.dumps(payload, indent=2, default=str))

    # The dossier's .md is intentionally NOT re-rendered here -- rendering
    # is an explicit step (`wake rebuild`), not a write-time side effect;
    # see build.py's module docstring. rerender_dossier_md() re-derives
    # the whole .md (tags, per-facet sections, status block, including
    # "corrected_from" when applicable) from exactly the JSON just
    # written above, whenever `wake rebuild` next runs.
    return True


def mark_pending(
    seed_id: str,
    citing_id: str,
    *,
    reason: str = "",
    base: Path | None = None,
) -> bool:
    """Patch an existing dossier's JSON sidecar back from verified to
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
    if reason:
        payload["pending_reason"] = reason
    else:
        payload.pop("pending_reason", None)

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

    EvidenceDossier.validate_or_raise(payload, context=f"evidence dossier {citing_id!r}")
    atomic_write_text(json_path, json.dumps(payload, indent=2, default=str))

    # The dossier's .md is intentionally NOT re-rendered here -- rendering
    # is an explicit step (`wake rebuild`), not a write-time side effect;
    # see build.py's module docstring. *reason* is persisted above
    # (payload["pending_reason"]) so rerender_dossier_md() can reproduce
    # it from JSON alone whenever `wake rebuild` next runs -- no more
    # patching it into already-rendered .md text out of band.
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


def seed_pdf_status(seed_id: str, base: Path | None = None) -> dict[str, Any]:
    """Classify the seed paper's own PDF-acquisition state into one of
    three buckets, from whatever seed.json/seed.pdf currently say on
    disk -- used by both orientation files and bake_markdown() so all
    three surfaces (README.md, AGENTS.md, impact.md) agree on the same
    status, the same "derived from disk, never itself a source of
    truth" convention as every other orientation field.

      "cached"           -- seed.pdf exists (wake seed fetch-pdf, auto
                             or manual, succeeded).
      "attempted-failed" -- seed.json's seed_pdf sub-object records an
                             attempt (auto-fetch at `wake resolve` time
                             tried every configured source) that did
                             not produce a cached PDF.
      "not-attempted"    -- no seed_pdf sub-object at all, e.g. a very
                             early-pipeline packet, or
                             pdf_fetch.seed_pdf_at_resolve was disabled.

    A `wake resolve` auto-fetch failure is silent by design (see
    seed.py's _maybe_auto_fetch_seed_pdf) so it never blocks the
    workflow -- but that silence means the *only* record of it is this
    seed_pdf sub-object, easy to miss without surfacing it explicitly
    in every human/agent-facing view of the folder.
    """
    from .pdf_fetch import seed_pdf_path
    from .seed import load_seed

    if seed_pdf_path(seed_id, base).exists():
        return {"status": "cached", "tried": [], "fallback_links": {}}

    seed_work = load_seed(seed_id, base) or {}
    info = seed_work.get("seed_pdf") or {}
    if not info:
        return {"status": "not-attempted", "tried": [], "fallback_links": {}}

    return {
        "status": "attempted-failed",
        "tried": info.get("tried") or [],
        "fallback_links": info.get("fallback_links") or {},
    }


def _orientation_counts(seed_id: str, base: Path | None = None) -> dict[str, Any]:
    """Gather the counts both README.md and AGENTS.md need to describe
    what's been done so far, from whatever's currently on disk. Shared
    by both builders so the two files never disagree about a number."""
    from .classify import load_classified
    from .narrative import narrative_md_path
    from .report import load_overrides

    wd = work_dir(seed_id, base)

    classified = load_classified(seed_id, base) or []
    classified_count = sum(1 for w in classified if w.get("relationship"))

    dossiers = _load_all_dossiers(seed_id, base)
    verified_dossiers = sum(1 for e in dossiers if e.get("verification_status") == "verified")

    overrides = load_overrides(seed_id, base)
    verified_overrides = sum(1 for o in overrides.values() if o.get("verification_status") == "verified")

    all_themes = _load_all_themes(seed_id, base)
    themes_confirmed = sum(1 for t in all_themes if t.get("theme_status") == "confirmed")
    themes_draft = len(all_themes) - themes_confirmed

    return {
        "impact_exists": (wd / "impact.md").exists(),
        "narrative_exists": narrative_md_path(seed_id, base).exists(),
        "citing_count": len(load_citing_ids(seed_id, base)),
        "classified_count": classified_count,
        "dossier_count": len(dossiers),
        "verified_count": max(verified_dossiers, verified_overrides),
        "pending_count": len(dossiers) - verified_dossiers,
        "themes_confirmed": themes_confirmed,
        "themes_draft": themes_draft,
        "themes_exist": bool(all_themes),
        "seed_pdf": seed_pdf_status(seed_id, base),
    }


def load_citing_ids(seed_id: str, base: Path | None = None) -> list[str]:
    """Best-effort count of citing works fetched so far, used only for
    orientation-file counts -- returns an empty list rather than raising
    if citing.json doesn't exist yet (nothing fetched) or is malformed."""
    from .citing import load_citing

    try:
        return [wid for w in (load_citing(seed_id, base) or []) if (wid := w.get("openalex_id"))]
    except (OSError, ValueError):
        return []


def _build_readme_lines(seed_id: str, seed_work: dict[str, Any] | None, counts: dict[str, Any]) -> list[str]:
    """Render README.md's content: a human-oriented explanation of what
    this folder is, what's been done, and where to start reading -- not
    just a bare link list. See rebuild_wiki_orientation()'s docstring for
    why this and AGENTS.md are two separate files."""
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

    lines.append("## What this folder is")
    lines.append("")
    lines.append(
        "This is a citation-impact analysis of the paper above, produced by "
        "[wake](https://github.com/rbross-hpc/wake). It catalogs every work "
        "that cites this paper, classifies the *nature* of each citation "
        "(does the citing work extend it, use it as a tool, benchmark "
        "against it, or just mention it in passing?), and — for the "
        "highest-signal citations — reads the full text of the citing paper "
        "to verify that classification and quote the specific passages that "
        "support it."
    )
    lines.append("")

    what_was_done: list[str] = []
    if counts["citing_count"]:
        what_was_done.append(
            f"**{counts['citing_count']}** citing works pulled from OpenAlex"
        )
    if counts["classified_count"]:
        what_was_done.append(
            f"**{counts['classified_count']}** classified by an LLM from title/abstract "
            "into one of seven relationship types (extends, builds-on, "
            "uses-as-tool, benchmarks, applies-to-domain, "
            "related-infrastructure, background-mention)"
        )
    if counts["dossier_count"]:
        what_was_done.append(
            f"**{counts['dossier_count']}** had their full PDF fetched, extracted, and "
            "re-classified against the actual body text, with supporting "
            "passages quoted directly"
        )
    if counts["verified_count"]:
        what_was_done.append(
            f"**{counts['verified_count']}** verified findings signed off by a human reviewer"
        )
    if counts["themes_exist"]:
        theme_bit = f"**{counts['themes_confirmed']}** confirmed"
        if counts["themes_draft"]:
            theme_bit += f" ({counts['themes_draft']} still draft)"
        what_was_done.append(
            f"{theme_bit} combined-evidence theme(s) synthesized across multiple dossiers"
        )
    if counts["narrative_exists"]:
        what_was_done.append("a narrative assembled from those confirmed themes")

    # Only "attempted-failed" gets a bullet here -- "not-attempted" isn't
    # an actionable problem (nothing has happened yet, same as every
    # other bullet in this section only appearing for completed work,
    # not its absence), and "cached" is the silent green path.
    seed_pdf = counts["seed_pdf"]
    if seed_pdf["status"] == "attempted-failed":
        tried = ", ".join(seed_pdf["tried"]) or "the configured sources"
        what_was_done.append(
            f"**Seed paper's own PDF**: not yet acquired (tried {tried} "
            "without success; see `seed.json` for fallback links to try "
            "by hand, or run `wake seed fetch-pdf --from-pdf PATH` once "
            "you have one)"
        )

    if what_was_done:
        lines.append("## What was done")
        lines.append("")
        for item in what_was_done:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("## Where to start")
    lines.append("")
    if counts["impact_exists"]:
        lines.append(
            "- **Get the top-line finding fast** — read the "
            "[Impact Brief](impact.md). Its \"Strongest Evidence\" section "
            "ranks the most impactful adoptions."
        )
    if counts["narrative_exists"]:
        lines.append(
            "- **Read the story** — read the [Narrative](narrative.md), "
            "prose that stitches the confirmed themes together with "
            "numbered citations back to the evidence."
        )
    if counts["dossier_count"]:
        lines.append(
            "- **Drill into a specific citing work** — start at the "
            "[Evidence Wiki](evidence/index.md) and pick a dossier. Each "
            "has quoted passages with page numbers."
        )
    if counts["themes_exist"]:
        lines.append(
            "- **See what patterns emerged across citing works** — read "
            "[Themes](evidence/themes/index.md)."
        )
    if counts["dossier_count"]:
        lines.append(
            "- **Audit what was investigated, in what order** — read the "
            "[Log](evidence/log.md)."
        )
    if not any([counts["impact_exists"], counts["dossier_count"], counts["themes_exist"]]):
        lines.append(
            "- Nothing has been generated yet beyond this page. Run `wake "
            "classify` and `wake bake` in the directory above `wake-out/` "
            "to produce an impact brief."
        )
    lines.append("")

    lines.append("## Reading conventions")
    lines.append("")
    lines.append(
        "- Every `.md` file in this folder that documents a specific "
        "finding has a `.json` sidecar with the same data in structured "
        "form. The `.md` is what you're meant to read; the `.json` is for "
        "tools."
    )
    lines.append(
        "- \"Provisional\" findings are from the abstract only — treat them "
        "as placeholder guesses. \"Verified\" findings have been checked "
        "against the full text and signed off by a human."
    )
    lines.append(
        "- All links in this folder are relative, so the whole folder can "
        "be moved, zipped, or shared and everything will still resolve."
    )
    lines.append(
        "- A citing work flagged as author-overlap with the seed is the "
        "seed's own team publishing follow-on work, not independent "
        "third-party adoption — called out wherever it applies."
    )
    lines.append("")

    lines.append("## Editing this folder by hand")
    lines.append("")
    lines.append("Human-facing files you might edit directly, one JSON object per line:")
    lines.append("")
    lines.append("- `overrides.jsonl` — record a corrected classification")
    lines.append("- `duplicates.jsonl` — mark a citing work as a duplicate of another")
    lines.append("- `exclusions.jsonl` — exclude a work from theme synthesis")
    lines.append("- `manual_abstracts.jsonl` — supply an abstract OpenAlex is missing")
    lines.append("")
    lines.append(
        "These are append-only — later lines for the same work win, "
        "nothing is ever rewritten in place. Everything else in this "
        "folder is derived from these plus the raw fetched/LLM data, and "
        "is safe to delete and regenerate."
    )
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*Generated by [wake](https://github.com/rbross-hpc/wake). To "
        "regenerate any view from the underlying data, run `wake bake` in "
        "the directory above `wake-out/`. If you're an agent working with "
        "this folder, see [AGENTS.md](AGENTS.md).*"
    )
    lines.append("")
    return lines


def _build_agents_md_lines(seed_id: str, seed_work: dict[str, Any] | None, counts: dict[str, Any]) -> list[str]:
    """Render AGENTS.md's content: a terse, schema-first reference for an
    agent handed this folder with no other context (no access to wake's
    own source, and possibly not even wake installed). See
    rebuild_wiki_orientation()'s docstring for why this is a separate
    file from README.md."""
    title = (seed_work or {}).get("title") or seed_id
    doi = (seed_work or {}).get("doi")
    year = (seed_work or {}).get("year")

    narrative_status = "assembled" if counts["narrative_exists"] else "absent"

    lines: list[str] = []
    lines.append("# AGENTS.md — orientation for an agent handed this folder")
    lines.append("")
    lines.append(
        "This folder is a **citation-impact analysis** of one seed paper, "
        "produced by [wake](https://github.com/rbross-hpc/wake). Every "
        "file here is one of a small number of artifact types, each with a "
        "stable schema described below. This file is self-contained — you "
        "do not need wake installed, or access to its source, to read the "
        "data in this folder."
    )
    lines.append("")

    lines.append("## Seed paper")
    lines.append("")
    lines.append(f"- Title: {title}")
    if year:
        lines.append(f"- Year: {year}")
    if doi:
        lines.append(f"- DOI: {doi}")
    lines.append(f"- OpenAlex ID: {seed_id}")
    lines.append(f"- Citing works fetched: {counts['citing_count']}")
    lines.append(f"- Citing works classified: {counts['classified_count']}")
    lines.append(f"- Full-text-verified: {counts['verified_count']}")
    lines.append(f"- Confirmed themes: {counts['themes_confirmed']}")
    lines.append(f"- Narrative status: {narrative_status}")
    seed_pdf = counts["seed_pdf"]
    if seed_pdf["status"] == "cached":
        lines.append("- Seed PDF: cached")
    elif seed_pdf["status"] == "attempted-failed":
        tried = ", ".join(seed_pdf["tried"]) or "configured sources"
        lines.append(f"- Seed PDF: attempted and failed (tried: {tried}) — see seed.json's `seed_pdf` field for fallback links")
    else:
        lines.append("- Seed PDF: not attempted yet")
    lines.append("")

    lines.append("## Two-surface convention")
    lines.append("")
    lines.append(
        "- **`.md` files** are the human surface: rendered prose, meant to "
        "be read by a person in Obsidian, GitHub, or a plain editor."
    )
    lines.append(
        "- **`.json` sidecars** are the agent surface. Every `.md` concept "
        "doc (dossier, theme, narrative section, impact brief) has a "
        "`.json` alongside it with the same information in structured "
        "form. **If you're programmatically extracting a finding, read "
        "the `.json`, never scrape prose out of the `.md`.**"
    )
    lines.append(
        "- Exception: `README.md`, `evidence/index.md`, `evidence/log.md`, "
        "and `evidence/themes/index.md` are pure catalogs with no JSON of "
        "their own — every fact in them is already in some other file's "
        "JSON sidecar."
    )
    lines.append("")

    lines.append("## Frontmatter `type:` values")
    lines.append("")
    lines.append(
        "Every rendered `.md` in this folder (except this file and "
        "README.md) opens with a YAML frontmatter block whose `type:` key "
        "is one of:"
    )
    lines.append("")
    lines.append("- `wiki-home` — README.md")
    lines.append("- `impact-brief` — impact.md")
    lines.append("- `narrative` — narrative.md")
    lines.append("- `narrative-outline` — narrative/outline.md")
    lines.append("- `narrative-section` — narrative/sections/<slug>.md")
    lines.append("- `theme` — evidence/themes/<slug>.md")
    lines.append("- `citing-work-evidence` — evidence/<id>.md")
    lines.append("- `index` — evidence/index.md, evidence/themes/index.md")
    lines.append("- `log` — evidence/log.md")
    lines.append("")

    lines.append("## File map")
    lines.append("")
    lines.append("```")
    lines.append("seed.json               resolved seed metadata + LLM description")
    lines.append("citing.json             every citing work fetched from OpenAlex")
    lines.append("classified.json         per-citing-work relationship classification")
    lines.append("impact.json / .md       aggregated reach metrics + ranked evidence")
    lines.append("narrative.md            assembled prose (sections live in narrative/)")
    lines.append("overrides.jsonl         human-reviewed relationship corrections")
    lines.append("duplicates.jsonl        citing works marked as duplicates of another")
    lines.append("exclusions.jsonl        citing works excluded from theme synthesis")
    lines.append("manual_abstracts.jsonl  human/PDF-recovered abstracts")
    lines.append("pdfs/<id>.pdf           cached PDF for a citing work")
    lines.append("pdfs/<id>.pdf.json      its extracted text, page-tagged")
    lines.append("evidence/<id>.md/.json  full-text verification dossier for a citing work")
    lines.append("evidence/index.md       dossier catalog: Verified / Pending Review")
    lines.append("evidence/log.md         chronological investigation history")
    lines.append("evidence/themes/*.md/.json     combined-evidence theme docs")
    lines.append("evidence/themes/index.md      theme catalog: Confirmed / Draft")
    lines.append("narrative/sections/*.md/.json  individual narrative section prose")
    lines.append("narrative/outline.md/.json     planned section order/status")
    lines.append("```")
    lines.append("")

    lines.append("## Schemas")
    lines.append("")

    lines.append("### `citing-work-evidence` — `evidence/<id>.json`")
    lines.append("")
    lines.append(
        "Keys: `citing_openalex_id`, `verification_status` "
        "(`verified` | `pending-human-review`), `provisional` "
        "(abstract-only guess: `relationship`, `confidence`, "
        "`justification`), `proposed` (full-text reading: `relationships` "
        "— a list of up to 3 facets, each `{label, confidence, "
        "justification, quotes, verified}` — plus legacy `relationship`/"
        "`confidence`/`justification` scalars mirroring the top facet), "
        "`quotes` (page-numbered supporting passages), `pdf_path`, "
        "`extracted_text_path`, `author_overlap`."
    )
    lines.append(
        "Relationship labels (fixed set of 7): `extends`, `builds-on`, "
        "`uses-as-tool`, `benchmarks`, `applies-to-domain`, "
        "`related-infrastructure`, `background-mention`. A citing work "
        "can have more than one facet (e.g. both `uses-as-tool` and "
        "`applies-to-domain`); ranking uses the strongest facet, not a sum."
    )
    lines.append(
        "The `.md`'s own frontmatter carries the same status at a glance: "
        "`verification_status`, `provisional_relationships` (label list), "
        "`proposed_relationships` (label list), and `author_overlap` "
        "(present only when `true`) — enough to filter dossiers without "
        "opening the `.json`."
    )
    lines.append("")

    lines.append("### `theme` — `evidence/themes/<slug>.json`")
    lines.append("")
    lines.append(
        "Keys: `slug`, `title`, `theme_status` (`draft` | `confirmed`), "
        "`summary` (synthesis prose), `citing_works` (list of "
        "`{citing_id, status, has_dossier, title}`), `needs_evidence`."
    )
    lines.append("The `.md`'s frontmatter mirrors `theme_status` directly.")
    lines.append("")

    lines.append("### `narrative-section` — `narrative/sections/<slug>.json`")
    lines.append("")
    lines.append(
        "Keys: `slug`, `title`, `kind`, `theme_slugs`, `status` "
        "(`draft` | `confirmed`), `prose` (with `[ref:ID]` markers, "
        "resolved to dossier links only in the rendered `.md`)."
    )
    lines.append(
        "The `.md`'s frontmatter carries `kind` and `section_status` "
        "(the JSON's `status`, renamed to avoid colliding with a "
        "dossier's `verification_status` in a vault-wide query)."
    )
    lines.append("")

    lines.append("### `impact-brief` — `impact.json`")
    lines.append("")
    lines.append(
        "Keys: `seed_openalex_id`, `total_citing_works`, "
        "`classified_count`, `verified_count`, `self_extension_count`, "
        "`coverage`, `by_year`, `by_relationship` (counts per label, one "
        "work may count under more than one), `by_venue_type`, "
        "`top_fields`, `top_evidence` (ranked list)."
    )
    lines.append("")

    lines.append("### Append-only decision logs (`*.jsonl`)")
    lines.append("")
    lines.append(
        "One JSON object per line; later lines for the same `citing_id` "
        "win on replay. Never rewritten in place, only appended to."
    )
    lines.append("")
    lines.append(
        "- `overrides.jsonl` — `{citing_id, relationship, justification, "
        "confidence, verification_status, overridden_at}`"
    )
    lines.append(
        "- `duplicates.jsonl` — `{duplicate_id, canonical_id, reason, "
        "confirmed_at}`"
    )
    lines.append(
        "- `exclusions.jsonl` — `{citing_id, excluded, reason, category, "
        "excluded_at}`"
    )
    lines.append(
        "- `manual_abstracts.jsonl` — `{citing_id, abstract, source, "
        "added_at}`"
    )
    lines.append("")

    lines.append("## Cross-file references")
    lines.append("")
    lines.append(
        "All paths inside this folder are relative to the file containing "
        "them, both in `.md` link syntax and in JSON path fields (e.g. a "
        "dossier's `pdf_path` reads `../pdfs/<id>.pdf`, relative to "
        "`evidence/`)."
    )
    lines.append("")

    lines.append("## Regenerating derived files")
    lines.append("")
    lines.append(
        "If you have wake installed (`pip install wake`), `wake rebuild "
        "<seed>` resyncs every derived file below (dossiers, evidence/"
        "index.md, theme docs + their index, narrative outline/sections/"
        "narrative.md, impact.md, and this folder's own README.md/"
        "AGENTS.md) from whatever JSON is already on disk, in one call, "
        "with no LLM/network calls — e.g. after hand-editing a JSON "
        "sidecar, or restoring from a partial backup. It skips any "
        "artifact type that has no JSON backing yet for this seed."
    )
    lines.append("")
    lines.append(
        "Individual verbs remain available for a narrower, targeted "
        "re-render instead of the full `wake rebuild`:"
    )
    lines.append("")
    lines.append("- `wake bake` — regenerate impact.md/json and this folder's orientation files")
    lines.append("- `wake evidence --rerender-all` — regenerate all dossier .md files from .json")
    lines.append("- `wake theme rerender-all` — regenerate all theme .md files from .json")
    lines.append("- `wake narrative section rerender-all` — regenerate all section .md files from .json")
    lines.append("- `wake narrative stitch` — regenerate narrative.md from sections")
    lines.append("")
    lines.append(
        "If wake is not installed, every `.md`/`.json` file here remains "
        "directly readable — none of them require wake to interpret, only "
        "to regenerate."
    )
    lines.append("")

    lines.append("## Query patterns")
    lines.append("")
    lines.append(
        "- **Which works cite the seed as `uses-as-tool`?** Read "
        "`classified.json`, filter `relationships[].label == "
        "\"uses-as-tool\"` (or the legacy `relationship` scalar)."
    )
    lines.append(
        "- **Show me all verified findings.** Read `evidence/<id>.json` "
        "for each entry in `evidence/index.md`, filter "
        "`verification_status == \"verified\"`. Or read `overrides.jsonl` "
        "for only the human-signed-off ones."
    )
    lines.append(
        "- **What did the citing paper actually say?** Read "
        "`pdfs/<id>.pdf.json` — the raw, page-tagged extracted text, the "
        "same input the LLM was given."
    )
    lines.append(
        "- **Show provenance of a specific finding.** A dossier's "
        "`proposed.relationships[].quotes` list carries page-numbered "
        "verbatim passages."
    )
    lines.append(
        "- **Is this citing work independent, or the same team's own "
        "follow-on?** Check `author_overlap` / `overlapping_authors` on "
        "the classified/dossier entry."
    )
    lines.append("")
    return lines


def rebuild_wiki_orientation(
    seed_id: str, seed_work: dict[str, Any] | None = None, base: Path | None = None,
) -> tuple[Path, Path]:
    """Regenerate the wiki's two entry points:

      README.md — a human-oriented explanation of what this folder is,
                   what's been done so far, and where to start reading,
                   ending with links to the top-level artifacts (impact
                   brief, narrative, evidence wiki, themes, log), each
                   omitted until its target exists.
      AGENTS.md — a terse, schema-first reference for an agent handed
                   just this folder, with no access to wake's own source
                   and possibly wake not even installed: every artifact
                   type's schema, the two-surface (.md/.json) convention,
                   and a handful of concrete query recipes.

    Both are derived views, like every other file in this module --
    recomputed from whatever's currently on disk, never themselves a
    source of truth -- so it's always safe to regenerate them and they
    never go stale in a way a fresh call can't fix.

    Called as a side effect of the commands that create the artifacts
    they describe (`wake bake`, `wake evidence`, `wake theme
    create`/`confirm`, `wake narrative stitch`, `wake override`) -- no
    separate command needed, same pattern as index.md/log.md/themes/index.md.
    """
    counts = _orientation_counts(seed_id, base)

    readme_path = wiki_home_path(seed_id, base)
    atomic_write_text(readme_path, "\n".join(_build_readme_lines(seed_id, seed_work, counts)))

    agents_path = agents_md_path(seed_id, base)
    atomic_write_text(agents_path, "\n".join(_build_agents_md_lines(seed_id, seed_work, counts)))

    return readme_path, agents_path
