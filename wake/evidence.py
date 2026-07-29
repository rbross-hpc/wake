# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Evidence deep-dive: full-text verification of a citing work's provisional
classification, and an OKF-style dossier documenting the finding.

Lifecycle (see BACKLOG.md / classify.py / report.py):
  provisional  — classify.py's abstract-only guess (always this, by default)
  proposed     — this module's full-text reading, with quoted passages
  verified     — only after the human reviews and an agent runs
                 `wake override` on their behalf (see report.add_override)

wake evidence never promotes anything to "verified" itself — it always
stops at "proposed" and hands structured findings back to the caller (the
CLI, and above that, the agent) to present to the human. The agent is the
one that runs `wake override`, never the human directly (see SKILL.md) —
and per explicit design requirement, when the agent walks a human through
a finding rather than asking them to read the dossier independently, it
must paste the literal quoted passage(s) into the conversation, in
context, not a paraphrase.

Fully general-purpose: no DOE-specific (or any other domain-specific)
logic lives here. See signals_doe.py for that, wired in separately and
off by default.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import config, cost as cost_mod
from .io import atomic_write_json, atomic_write_text, now_iso, read_json
from .llm.openai_client import chat_json
from .pdf_fetch import fetch_pdf
from .seed import work_dir
from .sources.pdf_fulltext import extract_full_text_from_pages, extract_pages_cached, extracted_text_path

_STAGE = "evidence"

_SYSTEM = """\
You are verifying a bibliometric classification by reading a citing paper's
full text. You are given:
  1. The seed paper being cited (title, year).
  2. A PROVISIONAL classification of how the citing paper relates to the
     seed — this was made from title/abstract alone, WITHOUT reading the
     citing paper's actual text. Treat it only as a weak, unverified guess,
     not a fact to confirm.
  3. The citing paper's full text, with [page N] markers.

Your job: read the full text and determine what it actually shows about
the paper's relationship to the seed. Do not simply try to justify the
provisional guess — form your own judgment from the text.

You MUST choose exactly one relationship label from this exact list (copy
verbatim, do not invent a new one):
- "extends": directly extends the method, framework, or theory of the seed.
- "builds-on": builds a new system, algorithm, or tool that depends on the seed.
- "uses-as-tool": uses the seed's software, tool, or dataset as-is.
- "benchmarks": benchmarks against or compares performance with the seed.
- "applies-to-domain": applies the seed's approach to a new domain or problem.
- "related-infrastructure": complementary tooling in the same ecosystem, no direct dependency.
- "background-mention": cites only as background/related work, or the seed
  is mentioned so briefly/indirectly that no specific technical relationship
  can be determined from the text.

For EVERY passage you rely on, quote the FULL PARAGRAPH containing it (not
a bare sentence fragment) exactly as it appears in the source text, along
with its page number. A human will read these quotes directly to judge
your reasoning — they must be complete enough to stand on their own,
in context, without needing to see the original document.

If the seed paper is not clearly discussed anywhere in the text (e.g. it
only appears in a bare reference-list entry with no in-text discussion),
say so honestly — do not fabricate a passage that doesn't exist. In that
case use "background-mention" with an empty quotes list and explain why
in the justification.

Respond with ONLY a single JSON object and NOTHING else — no markdown
fence, no preamble, no reasoning or commentary before or after the JSON.
Your entire response must be parseable as JSON on its own:
{
  "relationship": "<one of the exact strings above>",
  "confidence": <float 0.0-1.0>,
  "justification": "<1-3 sentences explaining your reading>",
  "agrees_with_provisional": <true or false>,
  "quotes": [
    {"page": <int>, "text": "<full paragraph, verbatim>", "note": "<what this passage shows>"}
  ]
}\
"""

_USER_TEMPLATE = """\
Seed paper: "{seed_title}" ({seed_year})

Provisional classification (abstract-only, UNVERIFIED): "{provisional_relationship}" \
(confidence {provisional_confidence}) — {provisional_justification}

Citing paper: "{citing_title}" ({citing_year})

Full text:
---
{full_text}
---

Read the full text and determine the actual relationship to the seed paper.\
"""


def _evidence_cfg() -> dict[str, Any]:
    return config.evidence_cfg()


def _prompt_version() -> str:
    return _evidence_cfg().get("prompt_version", "evidence-1")


def _model() -> str:
    return config.models().get("evidence", "Claude Sonnet 4.6")


def _max_fulltext_chars() -> int:
    return _evidence_cfg().get("max_fulltext_chars", 40000)


def evidence_dir(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / "evidence"


def dossier_path(seed_id: str, citing_id: str, base: Path | None = None) -> Path:
    return evidence_dir(seed_id, base) / f"{citing_id}.md"


def dossier_json_path(seed_id: str, citing_id: str, base: Path | None = None) -> Path:
    """Sidecar JSON alongside the rendered dossier markdown, holding the
    same data in structured form for programmatic re-use (e.g. re-rendering
    the dossier, or feeding a later `wake override` call without re-running
    the LLM verification pass)."""
    return evidence_dir(seed_id, base) / f"{citing_id}.json"


def _relpath_from(path: Path, from_dir: Path) -> str:
    """Render *path* relative to *from_dir*, e.g. a dossier's evidence/
    directory pointing at a sibling pdfs/ file as `../pdfs/<id>.pdf`.

    Both wake-out/ paths are always on the same filesystem, so this never
    needs to fall back to an absolute path -- unlike os.path.relpath, which
    can raise on Windows across drives, this is safe unconditionally here.
    """
    return os.path.relpath(path, from_dir)


def _resolve_sidecar_path(value: str | None, sidecar_dir: Path) -> str | None:
    """Resolve a `pdf_path`/`extracted_text_path` JSON field to an
    absolute path string, for callers that need to open the file.

    New dossiers store these fields relative to the JSON sidecar's own
    directory (see build_dossier()); dossiers written before this
    convention store an absolute path. Handling both means old, unrerendered
    wikis keep working without forcing a migration before their next
    `wake evidence --rerender-all` normalizes them.
    """
    if not value:
        return None
    p = Path(value)
    if p.is_absolute():
        return str(p)
    return str((sidecar_dir / p).resolve())


def verify_full_text(
    seed_work: dict[str, Any],
    citing_work: dict[str, Any],
    full_text: str,
    *,
    seed_id: str | None = None,
    base: Path | None = None,
    record_cost: bool = True,
) -> dict[str, Any]:
    """Run the full-text verification LLM pass. Returns the proposed
    finding: relationship, confidence, justification, agreement flag, and
    quoted passages with page numbers.
    """
    provisional = {
        "relationship": citing_work.get("relationship", "background-mention"),
        "confidence": citing_work.get("confidence", 0.0),
        "justification": citing_work.get("justification", ""),
    }

    user_msg = _USER_TEMPLATE.format(
        seed_title=seed_work.get("title") or "Unknown",
        seed_year=seed_work.get("year") or "Unknown",
        provisional_relationship=provisional["relationship"],
        provisional_confidence=provisional["confidence"],
        provisional_justification=provisional["justification"] or "(none)",
        citing_title=citing_work.get("title") or "Unknown",
        citing_year=citing_work.get("year") or "Unknown",
        full_text=full_text[:_max_fulltext_chars()],
    )

    cost_sink = None
    if record_cost and seed_id is not None:
        def cost_sink(model: str, system: str, user: str, response_text: str) -> None:
            cost_mod.record_call(
                seed_id, stage="evidence", model=model,
                system=system, user=user, response_text=response_text, base=base,
            )

    result = chat_json(_SYSTEM, user_msg, model_role="evidence", cost_sink=cost_sink)

    from .classify import RELATIONSHIPS
    relationship = result.get("relationship", "background-mention")
    if relationship not in RELATIONSHIPS:
        relationship = "background-mention"

    quotes = []
    for q in result.get("quotes", []) or []:
        if not isinstance(q, dict):
            continue
        text = (q.get("text") or "").strip()
        if not text:
            continue
        quotes.append({
            "page": q.get("page"),
            "text": text,
            "note": (q.get("note") or "").strip(),
        })

    from .author_overlap import compute_overlap
    overlap = compute_overlap(seed_work, citing_work)

    return {
        "provisional": provisional,
        "proposed": {
            "relationship": relationship,
            "confidence": float(result.get("confidence", 0.5)),
            "justification": result.get("justification", ""),
            "agrees_with_provisional": bool(result.get("agrees_with_provisional", relationship == provisional["relationship"])),
        },
        "quotes": quotes,
        **overlap,
    }


def _themes_citing(seed_id: str, citing_id: str, base: Path | None = None) -> list[dict[str, Any]]:
    """Every theme (any status) whose `citing_works` list names this
    citing work, for the dossier's "Referenced by" back-link line. Reads
    theme JSON sidecars directly -- no import of themes.py's own loaders
    needed beyond the directory helper, since this is a lightweight scan,
    not a themes.py-owned operation."""
    from .themes import themes_dir

    d = themes_dir(seed_id, base)
    if not d.exists():
        return []
    hits = []
    for p in sorted(d.glob("*.json")):
        try:
            theme = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if any(w.get("citing_id") == citing_id for w in theme.get("citing_works", [])):
            hits.append(theme)
    return hits


def _sections_citing(seed_id: str, citing_id: str, base: Path | None = None) -> list[dict[str, Any]]:
    """Every narrative section (any status) whose prose contains a
    `[ref:...]` marker naming this citing work, for the dossier's
    "Referenced by" back-link line."""
    from .narrative import _parse_ref_markers, sections_dir

    d = sections_dir(seed_id, base)
    if not d.exists():
        return []
    hits = []
    for p in sorted(d.glob("*.json")):
        try:
            section = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        cited_ids = {i for ids in _parse_ref_markers(section.get("prose", "")) for i in ids}
        if citing_id in cited_ids:
            hits.append(section)
    return hits


def _referenced_by_line(seed_id: str, citing_id: str, base: Path | None = None) -> str | None:
    """One-line back-link summary naming every theme and narrative section
    that currently cites this work, or None if it appears in neither (a
    plain background-mention dossier with no downstream synthesis yet).
    Purely a derived view over already-persisted theme/section sidecars --
    recomputed at render time, never itself persisted, so it can never go
    silently stale in a way that survives a re-render."""
    themes = _themes_citing(seed_id, citing_id, base)
    sections = _sections_citing(seed_id, citing_id, base)
    if not themes and not sections:
        return None

    parts = []
    for t in themes:
        slug = t.get("slug", "")
        title = t.get("title", slug)
        parts.append(f"theme [{title}](themes/{slug}.md)")
    for s in sections:
        slug = s.get("slug", "")
        title = s.get("title", slug)
        parts.append(f"narrative section [{title}](../narrative/sections/{slug}.md)")
    return "**Referenced by:** " + "; ".join(parts)


def _render_dossier_markdown(
    seed_work: dict[str, Any],
    citing_work: dict[str, Any],
    finding: dict[str, Any],
    *,
    pdf_path: Path | None,
    pdf_source: str | None,
    extracted_text_path_str: str | None = None,
    base: Path | None = None,
    verification_status: str = "pending-human-review",
) -> str:
    """Render the evidence dossier as an OKF concept document.

    *verification_status* controls the frontmatter `status:` tag and
    which "## Status" block is written. It defaults to
    "pending-human-review" (every fresh `build_dossier()` call always
    starts there); `rerender_dossier_md()` passes the dossier's actual
    current status so a re-render of an already-verified dossier doesn't
    regress its status back to pending. This function never itself
    decides verification status -- that remains evidence_wiki.py's
    mark_verified()/mark_pending()'s job; this only needs to know which
    of the two static blocks to print.
    """
    seed_id = seed_work.get("openalex_id", "")
    citing_id = citing_work.get("openalex_id", "")
    title = citing_work.get("title") or "Unknown"
    doi = citing_work.get("doi")
    resource = doi and f"https://doi.org/{doi}" or citing_work.get("url") or f"https://openalex.org/{citing_id}"
    proposed_rel = finding["proposed"]["relationship"]
    provisional_rel = finding["provisional"]["relationship"]

    author_overlap = bool(finding.get("author_overlap"))

    dossier_dir = evidence_dir(seed_id, base) if seed_id else None
    pdf_rel = _relpath_from(pdf_path, dossier_dir) if pdf_path is not None and dossier_dir is not None else None

    lines: list[str] = []
    lines.append("---")
    lines.append("type: citing-work-evidence")
    lines.append(f'title: "{title}"')
    lines.append(f'description: "{finding["proposed"]["justification"][:150]}"')
    lines.append(f"resource: \"{resource}\"")
    if pdf_rel:
        lines.append(f'pdf: "{pdf_rel}"')
    tags = [f"provisional:{provisional_rel}", f"proposed:{proposed_rel}", f"status:{verification_status}"]
    if author_overlap:
        tags.append("author-overlap:true")
    lines.append(f"tags: [{', '.join(tags)}]")
    lines.append(f"timestamp: {now_iso()}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Evidence: {title}")
    lines.append("")

    authors = citing_work.get("authors", [])
    author_str = ", ".join(authors[:8]) + (" et al." if len(authors) > 8 else "")
    year = citing_work.get("year", "")
    venue = citing_work.get("venue", "")
    meta_parts = [str(year), venue, f"DOI: {doi}" if doi else "", f"OpenAlex: {citing_id}"]
    lines.append(f"**{' · '.join(p for p in meta_parts if p)}**")
    if author_str:
        lines.append(f"*{author_str}*")
    if author_overlap:
        overlapping = ", ".join(finding.get("overlapping_authors", []))
        lines.append(
            f"**Author overlap with seed:** {overlapping} — this appears to be "
            "the original team's own follow-on work, not an independent third party."
        )
    lines.append("")

    referenced_by = _referenced_by_line(seed_id, citing_id, base) if seed_id and citing_id else None
    if referenced_by:
        lines.append(referenced_by)
        lines.append("")

    if citing_work.get("abstract"):
        lines.append("## Abstract")
        lines.append("")
        lines.append(citing_work["abstract"])
        lines.append("")

    lines.append("## Provisional Classification (abstract-only — not yet checked against the paper)")
    lines.append("")
    lines.append(
        f"> *{provisional_rel}* (confidence: {finding['provisional']['confidence']:.2f}) — "
        f"{finding['provisional']['justification'] or '(no justification recorded)'}"
    )
    lines.append("")
    lines.append(
        "This was produced from title/abstract/venue alone, without reading "
        "the paper — treat it as a placeholder guess, not a finding."
    )
    lines.append("")

    lines.append("## Full-Text Reading (proposed — pending human review)")
    lines.append("")
    proposed = finding["proposed"]
    agree_note = (
        "confirms the provisional guess" if proposed["agrees_with_provisional"]
        else f"differs from the provisional guess (was: *{provisional_rel}*)"
    )
    lines.append(
        f"> *{proposed_rel}* (confidence: {proposed['confidence']:.2f}) — {proposed['justification']}"
    )
    lines.append(f"> ({agree_note})")
    lines.append("")

    if finding["quotes"]:
        lines.append("### Supporting Passages")
        lines.append("")
        for q in finding["quotes"]:
            page = q.get("page")
            page_str = f"p. {page}" if page else "page unknown"
            lines.append(f"**{page_str}**")
            lines.append("")
            quoted = q["text"].replace("\n", "\n> ")
            lines.append(f"> {quoted}")
            lines.append("")
            if q.get("note"):
                lines.append(f"*{q['note']}*")
                lines.append("")
    else:
        lines.append(
            "*No supporting passages found — the seed paper may only appear "
            "in a reference-list entry with no in-text discussion.*"
        )
        lines.append("")

    # Marked with HTML comments (invisible when rendered) rather than
    # matched by literal prose, so evidence_wiki.py::mark_verified()/
    # mark_pending() can replace this whole block without depending on
    # the exact wording above staying byte-for-byte identical forever.
    # rerender_dossier_md() re-derives this same block from the dossier's
    # persisted human_verification data (rather than calling
    # mark_verified/mark_pending, which are meant for an actual status
    # *transition*, not a plain re-render), so a bulk rendering-only pass
    # never regresses an already-verified dossier back to pending.
    lines.append("<!-- status-section:start -->")
    if verification_status == "verified":
        hv = finding.get("human_verification") or {}
        verified_at = hv.get("verified_at", "")
        status_note = f"Verified by a human on {verified_at}"
        corrected_from = hv.get("corrected_from")
        if corrected_from:
            status_note += (
                f" — human corrected the model's reading from "
                f"*{corrected_from}* to *{proposed_rel}*"
            )
        justification = hv.get("justification")
        if justification:
            status_note += f" — {justification}"
        lines.append("## Status: verified")
        lines.append("")
        lines.append(f"{status_note}.")
    else:
        lines.append("## Status: pending your review")
        lines.append("")
        lines.append(
            "This finding has not been applied to the impact brief. An agent "
            "should present the passages above to a human, then run "
            "`wake override` on their behalf once the human accepts or adjusts "
            "the reading — see SKILL.md."
        )
    lines.append("<!-- status-section:end -->")
    lines.append("")

    if pdf_path is not None and dossier_dir is not None:
        lines.append("## Source")
        lines.append("")
        lines.append(f"- [Cached PDF]({pdf_rel})" + (f" (via {pdf_source})" if pdf_source else ""))
        if extracted_text_path_str:
            extracted_rel = _relpath_from(Path(extracted_text_path_str), dossier_dir)
            lines.append(
                f"- [Raw extracted text]({extracted_rel}) — the exact page-tagged text "
                "the model was given, as a JSON cache. Read this first if a finding looks "
                "wrong: multi-column academic layouts are a known source of garbled "
                "extraction, and a bad extraction looks very different from a bad "
                "inference once you see the raw text."
            )
        lines.append("")

    return "\n".join(lines)


def build_dossier(
    seed_work: dict[str, Any],
    citing_work: dict[str, Any],
    *,
    base: Path | None = None,
    force: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Full pipeline: fetch PDF -> extract full text -> LLM verification ->
    write the OKF dossier (.md + .json sidecar).

    Returns a summary dict for the caller (CLI -> agent) to act on:
      {
        "ok": True,
        "dossier_path": "...", "dossier_json_path": "...",
        "pdf_path": "..." | None, "pdf_source": "..." | None,
        "provisional": {...}, "proposed": {...}, "quotes": [...],
      }
    or, if no PDF could be acquired:
      {"ok": False, "reason": "no_pdf", "fetch_result": {...}}

    If a dossier already exists for this citing work and force=False,
    returns the cached finding without re-running the LLM verification
    pass (the PDF itself is still resolved via fetch_pdf's own cache, so
    this is effectively free — one dict-merge, no network calls).

    force=True re-runs both the LLM verification pass AND the PDF text
    extraction (see sources/pdf_fulltext.py's extract_pages_cached) — so a
    bad/garbled extraction can be fixed by re-running with --force even
    when the underlying PDF file hasn't changed. The extracted text
    itself is always cached next to the PDF
    (wake-out/<seed>/pdfs/<citing-id>.json) regardless of force, so anyone
    diagnosing a surprising finding — a human directly, or an agent
    checking on the human's behalf before assuming the model reasoned
    poorly — can open that file and see exactly what text the LLM saw.
    """
    seed_id = seed_work["openalex_id"]
    citing_id = citing_work["openalex_id"]

    if not force:
        cached = load_dossier(seed_id, citing_id, base)
        if cached is not None:
            if verbose:
                print(f"[wake] Dossier already exists: {dossier_path(seed_id, citing_id, base)}", file=sys.stderr)
            wd = evidence_dir(seed_id, base)
            return {
                "ok": True,
                "dossier_path": str(dossier_path(seed_id, citing_id, base)),
                "dossier_json_path": str(dossier_json_path(seed_id, citing_id, base)),
                "pdf_path": _resolve_sidecar_path(cached.get("pdf_path"), wd),
                "pdf_source": cached.get("pdf_source"),
                "extracted_text_path": _resolve_sidecar_path(cached.get("extracted_text_path"), wd),
                "provisional": cached.get("provisional"),
                "proposed": cached.get("proposed"),
                "quotes": cached.get("quotes"),
                "citing_title": cached.get("citing_title") or citing_work.get("title"),
                "citing_authors": cached.get("citing_authors") or citing_work.get("authors") or [],
            }

    fetch_result = fetch_pdf(
        seed_id, citing_id,
        doi=citing_work.get("doi"),
        title=citing_work.get("title"),
        seed_title=seed_work.get("title"),
        base=base,
        verbose=verbose,
    )
    if not fetch_result.get("ok"):
        _log_investigation(
            seed_work, citing_id, base,
            event="investigation_failed",
            detail="no PDF found (tried: " + ", ".join(fetch_result.get("tried", [])) + ")",
        )
        return {"ok": False, "reason": "no_pdf", "fetch_result": fetch_result}

    pdf_path_str = fetch_result["path"]
    pdf_source = fetch_result.get("source")
    extracted_text_path_str = str(extracted_text_path(Path(pdf_path_str)))

    if verbose:
        print(f"[wake] Extracting full text from {pdf_path_str}...", file=sys.stderr)
    pages = extract_pages_cached(pdf_path_str, force=force)
    full_text = extract_full_text_from_pages(pages)
    if not full_text.strip():
        _log_investigation(
            seed_work, citing_id, base,
            event="investigation_failed",
            detail="PDF text extraction produced no text (possibly scanned, no text layer)",
        )
        return {
            "ok": False,
            "reason": "extraction_failed",
            "pdf_path": pdf_path_str,
            "extracted_text_path": extracted_text_path_str,
            "message": "Could not extract any text from the PDF (possibly scanned with no text layer).",
        }

    if verbose:
        print(f"[wake] Running full-text verification (model={_model()})...", file=sys.stderr)
    finding = verify_full_text(
        seed_work, citing_work, full_text,
        seed_id=seed_id, base=base,
    )

    md_text = _render_dossier_markdown(
        seed_work, citing_work, finding,
        pdf_path=Path(pdf_path_str), pdf_source=pdf_source,
        extracted_text_path_str=extracted_text_path_str,
        base=base,
    )

    wd = evidence_dir(seed_id, base)
    wd.mkdir(parents=True, exist_ok=True)
    md_path = dossier_path(seed_id, citing_id, base)
    json_path = dossier_json_path(seed_id, citing_id, base)

    atomic_write_text(md_path, md_text)

    # Stored relative to this sidecar's own directory (evidence/), not
    # absolute -- so the whole wake-out/<seed>/ tree stays self-consistent
    # if it's ever moved or shared. See _relpath_from()/rerender_dossier_md()
    # for the read side, which resolves these back to absolute paths before
    # re-rendering the markdown.
    json_payload = {
        "seed_openalex_id": seed_id,
        "citing_openalex_id": citing_id,
        "citing_title": citing_work.get("title"),
        "citing_authors": citing_work.get("authors") or [],
        "generated_at": now_iso(),
        "prompt_version": _prompt_version(),
        "model": _model(),
        "pdf_path": _relpath_from(Path(pdf_path_str), wd),
        "pdf_source": pdf_source,
        "extracted_text_path": _relpath_from(Path(extracted_text_path_str), wd),
        "citing_cited_by_count": citing_work.get("cited_by_count", 0),
        "verification_status": "pending-human-review",
        **finding,
    }
    atomic_write_json(json_path, json_payload)

    if verbose:
        print(f"[wake] Dossier written: {md_path}", file=sys.stderr)

    from .evidence_wiki import append_log_entry, rebuild_index, rebuild_wiki_home
    event = "dossier_rebuilt" if force else "dossier_built"
    append_log_entry(
        seed_id, event=event, citing_id=citing_id,
        detail=f"proposed: {finding['proposed']['relationship']} ({len(finding['quotes'])} quotes)",
        seed_title=seed_work.get("title"), base=base,
    )
    rebuild_index(seed_id, seed_title=seed_work.get("title"), base=base)
    rebuild_wiki_home(seed_id, seed_work, base=base)

    return {
        "ok": True,
        "dossier_path": str(md_path),
        "dossier_json_path": str(json_path),
        "pdf_path": pdf_path_str,
        "pdf_source": pdf_source,
        "extracted_text_path": extracted_text_path_str,
        **finding,
    }


def _log_investigation(
    seed_work: dict[str, Any],
    citing_id: str,
    base: Path | None,
    *,
    event: str,
    detail: str,
) -> None:
    from .evidence_wiki import append_log_entry
    append_log_entry(
        seed_work["openalex_id"], event=event, citing_id=citing_id,
        detail=detail, seed_title=seed_work.get("title"), base=base,
    )


def rerender_dossier_md(
    seed_work: dict[str, Any],
    citing_id: str,
    *,
    base: Path | None = None,
) -> Path | None:
    """Re-emit one dossier's .md from its already-persisted .json sidecar,
    with a fresh back-link scan (`_referenced_by_line`) -- no LLM call, no
    PDF fetch, no state change. This is purely a rendering pass: the
    finding itself (provisional/proposed/quotes/verification_status) is
    read as-is from the sidecar and written back out unchanged, only the
    markdown's derived "Referenced by" line (and any other future
    rendering-only content) is recomputed.

    Used two ways: (1) targeted, from themes.py/narrative.py hooks right
    after a theme or section is written, to refresh just the dossiers it
    affects; (2) bulk, via `wake evidence rerender-all`, to backfill every
    dossier in a wiki after a rendering-code upgrade.

    Returns the .md path, or None if no dossier exists for this citing_id
    (nothing to re-render).
    """
    seed_id = seed_work["openalex_id"]
    payload = load_dossier(seed_id, citing_id, base)
    if payload is None:
        return None

    from .citing import load_citing

    # Prefer the full record from citing.json (has abstract, venue, DOI,
    # etc.) when available; the dossier's own citing_title/citing_authors
    # sidecar fields are only a fallback for the (unlikely) case where
    # citing.json has been pruned/rotated out from under an old dossier.
    citing_work = None
    for w in load_citing(seed_id, base) or []:
        if w.get("openalex_id") == citing_id:
            citing_work = w
            break
    if citing_work is None:
        citing_work = {
            "openalex_id": citing_id,
            "title": payload.get("citing_title"),
            "authors": payload.get("citing_authors") or [],
            "cited_by_count": payload.get("citing_cited_by_count", 0),
        }

    finding = {
        "provisional": payload.get("provisional", {}),
        "proposed": payload.get("proposed", {}),
        "quotes": payload.get("quotes", []),
        "author_overlap": payload.get("author_overlap", False),
        "overlapping_authors": payload.get("overlapping_authors", []),
        "human_verification": payload.get("human_verification", {}),
    }

    wd = evidence_dir(seed_id, base)
    pdf_path_str = _resolve_sidecar_path(payload.get("pdf_path"), wd)
    extracted_text_path_str = _resolve_sidecar_path(payload.get("extracted_text_path"), wd)
    md_text = _render_dossier_markdown(
        seed_work, citing_work, finding,
        pdf_path=Path(pdf_path_str) if pdf_path_str else None,
        pdf_source=payload.get("pdf_source"),
        extracted_text_path_str=extracted_text_path_str,
        base=base,
        verification_status=payload.get("verification_status", "pending-human-review"),
    )

    md_path = dossier_path(seed_id, citing_id, base)
    atomic_write_text(md_path, md_text)

    # Opportunistic migration: normalize a legacy absolute pdf_path/
    # extracted_text_path in the JSON sidecar to relative-from-sidecar
    # form, so a --rerender-all pass across an older wiki also fixes up
    # its JSON, not just its markdown. Idempotent (no-op once already
    # relative); skipped entirely if there's nothing to normalize.
    normalized = dict(payload)
    changed = False
    if pdf_path_str and payload.get("pdf_path") != (rel := _relpath_from(Path(pdf_path_str), wd)):
        normalized["pdf_path"] = rel
        changed = True
    if extracted_text_path_str and payload.get("extracted_text_path") != (
        rel := _relpath_from(Path(extracted_text_path_str), wd)
    ):
        normalized["extracted_text_path"] = rel
        changed = True
    if changed:
        atomic_write_json(dossier_json_path(seed_id, citing_id, base), normalized)

    return md_path


def rerender_all_dossiers(seed_id: str, seed_work: dict[str, Any], base: Path | None = None) -> list[str]:
    """Re-emit every dossier .md in this seed's evidence/ directory from
    its .json sidecar -- the bulk counterpart to `rerender_dossier_md()`,
    used by `wake evidence rerender-all` to backfill an existing wiki
    after a rendering-code upgrade. No LLM call, no PDF fetch, no state
    change. Returns the sorted list of citing IDs re-rendered."""
    d = evidence_dir(seed_id, base)
    if not d.exists():
        return []
    citing_ids = sorted(p.stem for p in d.glob("*.json"))
    for cid in citing_ids:
        rerender_dossier_md(seed_work, cid, base=base)
    return citing_ids


def load_dossier(seed_id: str, citing_id: str, base: Path | None = None) -> dict[str, Any] | None:
    p = dossier_json_path(seed_id, citing_id, base)
    if not p.exists():
        return None
    return read_json(p)
