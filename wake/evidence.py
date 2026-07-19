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


def _render_dossier_markdown(
    seed_work: dict[str, Any],
    citing_work: dict[str, Any],
    finding: dict[str, Any],
    *,
    pdf_path: Path | None,
    pdf_source: str | None,
    extracted_text_path_str: str | None = None,
) -> str:
    """Render the evidence dossier as an OKF concept document."""
    citing_id = citing_work.get("openalex_id", "")
    title = citing_work.get("title") or "Unknown"
    doi = citing_work.get("doi")
    resource = doi and f"https://doi.org/{doi}" or citing_work.get("url") or f"https://openalex.org/{citing_id}"
    proposed_rel = finding["proposed"]["relationship"]
    provisional_rel = finding["provisional"]["relationship"]

    author_overlap = bool(finding.get("author_overlap"))

    lines: list[str] = []
    lines.append("---")
    lines.append("type: citing-work-evidence")
    lines.append(f'title: "{title}"')
    lines.append(f'description: "{finding["proposed"]["justification"][:150]}"')
    lines.append(f"resource: \"{resource}\"")
    tags = [f"provisional:{provisional_rel}", f"proposed:{proposed_rel}", "status:pending-human-review"]
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

    lines.append("## Status: pending your review")
    lines.append("")
    lines.append(
        "This finding has not been applied to the impact brief. An agent "
        "should present the passages above to a human, then run "
        "`wake override` on their behalf once the human accepts or adjusts "
        "the reading — see SKILL.md."
    )
    lines.append("")

    if pdf_path is not None:
        lines.append("## Source")
        lines.append("")
        lines.append(f"- Local PDF: `{pdf_path}`" + (f" (via {pdf_source})" if pdf_source else ""))
        if extracted_text_path_str:
            lines.append(
                f"- Raw extracted text (what the model actually read): `{extracted_text_path_str}` — "
                "open this if a finding looks wrong, to check whether the extraction was "
                "garbled before assuming the reasoning was."
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
            return {
                "ok": True,
                "dossier_path": str(dossier_path(seed_id, citing_id, base)),
                "dossier_json_path": str(dossier_json_path(seed_id, citing_id, base)),
                "pdf_path": cached.get("pdf_path"),
                "pdf_source": cached.get("pdf_source"),
                "extracted_text_path": cached.get("extracted_text_path"),
                "provisional": cached.get("provisional"),
                "proposed": cached.get("proposed"),
                "quotes": cached.get("quotes"),
            }

    fetch_result = fetch_pdf(
        seed_id, citing_id,
        doi=citing_work.get("doi"),
        title=citing_work.get("title"),
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
    )

    wd = evidence_dir(seed_id, base)
    wd.mkdir(parents=True, exist_ok=True)
    md_path = dossier_path(seed_id, citing_id, base)
    json_path = dossier_json_path(seed_id, citing_id, base)

    atomic_write_text(md_path, md_text)

    json_payload = {
        "seed_openalex_id": seed_id,
        "citing_openalex_id": citing_id,
        "generated_at": now_iso(),
        "prompt_version": _prompt_version(),
        "model": _model(),
        "pdf_path": pdf_path_str,
        "pdf_source": pdf_source,
        "extracted_text_path": extracted_text_path_str,
        "citing_cited_by_count": citing_work.get("cited_by_count", 0),
        "verification_status": "pending-human-review",
        **finding,
    }
    atomic_write_json(json_path, json_payload)

    if verbose:
        print(f"[wake] Dossier written: {md_path}", file=sys.stderr)

    from .evidence_wiki import append_log_entry, rebuild_index
    event = "dossier_rebuilt" if force else "dossier_built"
    append_log_entry(
        seed_id, event=event, citing_id=citing_id,
        detail=f"proposed: {finding['proposed']['relationship']} ({len(finding['quotes'])} quotes)",
        seed_title=seed_work.get("title"), base=base,
    )
    rebuild_index(seed_id, seed_title=seed_work.get("title"), base=base)

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


def load_dossier(seed_id: str, citing_id: str, base: Path | None = None) -> dict[str, Any] | None:
    p = dossier_json_path(seed_id, citing_id, base)
    if not p.exists():
        return None
    return read_json(p)
