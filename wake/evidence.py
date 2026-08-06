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

from . import config
from . import cost as cost_mod
from .io import atomic_write_json, atomic_write_text, now_iso, read_json
from .llm.openai_client import chat_json
from .models import EvidenceDossier
from .pdf_fetch import fetch_pdf
from .seed import work_dir
from .sources.pdf_fulltext import (
    extract_full_text_from_pages,
    extract_pages_cached,
    extracted_text_path,
)

_STAGE = "evidence"

_SYSTEM_EVIDENCE_1 = """\
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

# evidence-2: multi-facet successor to evidence-1, above. Mirrors
# classify-3's reasoning (see classify.py's module docstring): a citing
# paper's actual relationship to the seed, once you've read the full
# text, is sometimes still genuinely more than one story -- each with
# its own supporting passages. Quotes attach to the specific facet they
# support rather than to the finding as a whole.
_SYSTEM_EVIDENCE_2 = """\
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

Choose from these seven relationship class strings — copy verbatim into
the "label" field, do not invent a new one:
- "extends": directly extends the method, framework, or theory of the seed.
- "builds-on": builds a new system, algorithm, or tool that depends on the seed.
- "uses-as-tool": uses the seed's software, tool, or dataset as-is.
- "benchmarks": benchmarks against or compares performance with the seed.
- "applies-to-domain": applies the seed's approach to a new domain or problem.
- "related-infrastructure": complementary tooling in the same ecosystem, no direct dependency.
- "background-mention": cites only as background/related work, or the seed
  is mentioned so briefly/indirectly that no specific technical relationship
  can be determined from the text.

Most citing papers have exactly ONE clear relationship to the seed, once
you've read the full text. Some genuinely have TWO -- for example, a
paper that both uses the seed's tool as-is ("uses-as-tool") AND applies
it to a new domain ("applies-to-domain") is telling two independent
stories, each with its own supporting passages. Very rarely does a paper
have THREE.

Return one facet by default. Return two only when both are independently
well-supported by distinct passages (each a defensible standalone
reading on its own — not the same story described two ways). Return
three only in the exceptional case where the paper genuinely does three
distinct things. Do not hedge: e.g. a paper that clearly "extends" the
seed should NOT also list "builds-on" just because extending could be
described as a kind of building-on -- that is one story, not two.

Every facet you return must have confidence >= 0.5.

For EVERY passage you rely on, quote the FULL PARAGRAPH containing it (not
a bare sentence fragment) exactly as it appears in the source text, along
with its page number. A human will read these quotes directly to judge
your reasoning — they must be complete enough to stand on their own, in
context, without needing to see the original document. Attach each quote
to the specific facet it supports.

If the seed paper is not clearly discussed anywhere in the text (e.g. it
only appears in a bare reference-list entry with no in-text discussion),
say so honestly — do not fabricate a passage that doesn't exist. In that
case return a single "background-mention" facet with an empty quotes
list and explain why in its justification.

Respond with ONLY a single JSON object and NOTHING else — no markdown
fence, no preamble, no reasoning or commentary before or after the JSON.
Your entire response must be parseable as JSON on its own:
{
  "relationships": [
    {
      "label": "<one of the exact strings above>",
      "confidence": <float 0.5-1.0>,
      "justification": "<1-3 sentences explaining this specific facet>",
      "quotes": [
        {"page": <int>, "text": "<full paragraph, verbatim>", "note": "<what this passage shows>"}
      ]
    }
  ],
  "agrees_with_provisional": <true or false>
}
List the facets most-confident first. "agrees_with_provisional" is true
if any facet you return matches the provisional label.\
"""

_SYSTEM_BY_VERSION: dict[str, str] = {
    "evidence-1": _SYSTEM_EVIDENCE_1,
    "evidence-2": _SYSTEM_EVIDENCE_2,
}


def _system_prompt(prompt_version: str) -> str:
    """The literal system prompt for *prompt_version* -- see
    _SYSTEM_BY_VERSION. Falls back to the evidence-1 (legacy,
    single-label) prompt for an unrecognized version string."""
    return _SYSTEM_BY_VERSION.get(prompt_version, _SYSTEM_EVIDENCE_1)


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


def _clean_quote(q: Any) -> dict[str, Any] | None:
    if not isinstance(q, dict):
        return None
    text = (q.get("text") or "").strip()
    if not text:
        return None
    return {"page": q.get("page"), "text": text, "note": (q.get("note") or "").strip()}


def _parse_proposed_relationships(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize an evidence-verification LLM response from either
    _SYSTEM_EVIDENCE_1 (single "relationship"/"confidence"/"justification"/
    "quotes" scalars) or _SYSTEM_EVIDENCE_2 ("relationships" list, each
    with its own "quotes") into a canonical facets list: valid labels
    only, confidence >= classify.MIN_FACET_CONFIDENCE, sorted
    confidence-descending, capped at classify.MAX_FACETS, each with its
    own cleaned quotes list. Mirrors classify._parse_relationships_response
    -- kept as a separate function because evidence facets additionally
    carry per-facet quotes, which classify's abstract-only facets never
    have. Always returns at least one facet."""
    from .classify import CANONICAL_RELATIONSHIPS, MAX_FACETS, MIN_FACET_CONFIDENCE

    raw_facets = result.get("relationships")
    if not isinstance(raw_facets, list) or not raw_facets:
        raw_facets = [{
            "label": result.get("relationship", "background-mention"),
            "confidence": result.get("confidence", 0.5),
            "justification": result.get("justification", ""),
            "quotes": result.get("quotes", []),
        }]

    facets: list[dict[str, Any]] = []
    for f in raw_facets:
        if not isinstance(f, dict):
            continue
        label = f.get("label")
        if label not in CANONICAL_RELATIONSHIPS:
            continue
        try:
            confidence = float(f.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        if confidence < MIN_FACET_CONFIDENCE:
            continue
        quotes = [q for q in (_clean_quote(q) for q in (f.get("quotes") or [])) if q is not None]
        facets.append({
            "label": label,
            "confidence": confidence,
            "justification": (f.get("justification") or "").strip(),
            "quotes": quotes,
        })

    facets.sort(key=lambda f: f["confidence"], reverse=True)
    facets = facets[:MAX_FACETS]

    if not facets:
        facets = [{"label": "background-mention", "confidence": 0.5, "justification": "", "quotes": []}]

    return facets


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
    finding: a multi-facet "relationships" list (see
    _parse_proposed_relationships), legacy "relationship"/"confidence"/
    "justification" scalars for read-compat set from the top
    (most-confident) facet, an agreement flag, and a top-level "quotes"
    list -- the deduplicated union of every facet's quotes, in the order
    the facets are listed, for callers that only care about the finding
    as a whole (e.g. `wake evidence`'s CLI printer)."""
    from .classify import _normalize_relationships

    provisional_facets = _normalize_relationships(citing_work)
    provisional = {
        "relationship": provisional_facets[0]["label"],
        "confidence": provisional_facets[0]["confidence"],
        "justification": provisional_facets[0]["justification"],
        "relationships": provisional_facets,
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

    system_prompt = _system_prompt(_prompt_version())
    result = chat_json(system_prompt, user_msg, model_role="evidence", cost_sink=cost_sink)

    facets = _parse_proposed_relationships(result)
    top = facets[0]

    provisional_labels = {f["label"] for f in provisional_facets}
    agrees = bool(result.get(
        "agrees_with_provisional",
        any(f["label"] in provisional_labels for f in facets),
    ))

    # Deduplicated union of every facet's quotes, preserving facet order
    # then in-facet order, for legacy readers that only look at the
    # top-level "quotes" list (e.g. the CLI's human printer).
    seen: set[tuple[Any, str]] = set()
    quotes: list[dict[str, Any]] = []
    for f in facets:
        for q in f["quotes"]:
            key = (q.get("page"), q["text"])
            if key in seen:
                continue
            seen.add(key)
            quotes.append(q)

    from .author_overlap import compute_overlap
    overlap = compute_overlap(seed_work, citing_work)

    return {
        "provisional": provisional,
        "proposed": {
            "relationship": top["label"],
            "confidence": top["confidence"],
            "justification": top["justification"],
            "agrees_with_provisional": agrees,
            "relationships": facets,
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


def _normalize_proposed_relationships(proposed: dict[str, Any], top_level_quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Like classify._normalize_relationships, but for a dossier's
    "proposed" block specifically: when there's no "relationships" list
    (a legacy, pre-multi-facet dossier), the synthesized single facet
    must also carry quotes -- which classify's generic normalizer
    doesn't know about, since classify's own facets (abstract-only) never
    have quotes. Falls back to *top_level_quotes* (the dossier's
    top-level "quotes" field) for that legacy case; a genuine multi-facet
    "relationships" list already carries its own per-facet quotes and is
    returned as-is."""
    facets = proposed.get("relationships")
    if isinstance(facets, list) and facets:
        return facets
    return [{
        "label": proposed.get("relationship", "background-mention"),
        "confidence": proposed.get("confidence", 0.5),
        "justification": proposed.get("justification", ""),
        "quotes": top_level_quotes,
    }]


def _append_facet_quotes(lines: list[str], quotes: list[dict[str, Any]]) -> None:
    """Append a "### Supporting Passages" block (or its empty-state
    fallback) for one facet's quotes to *lines* in place. Shared by
    _render_dossier_markdown's single-facet and multi-facet rendering
    paths so the passage formatting stays identical either way."""
    if quotes:
        lines.append("### Supporting Passages")
        lines.append("")
        for q in quotes:
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
    from .classify import _normalize_relationships

    seed_id = seed_work.get("openalex_id", "")
    citing_id = citing_work.get("openalex_id", "")
    title = citing_work.get("title") or "Unknown"
    doi = citing_work.get("doi")
    resource = doi and f"https://doi.org/{doi}" or citing_work.get("url") or f"https://openalex.org/{citing_id}"

    provisional_facets = _normalize_relationships(finding["provisional"])
    proposed_facets = _normalize_proposed_relationships(finding["proposed"], finding.get("quotes", []))
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
    lines.append(f"verification_status: {verification_status}")
    # One entry per facet per phase, listed in the same order as displayed
    # below (see classify.py's MAX_FACETS -- almost always 1, occasionally
    # 2, rarely 3 facets per phase).
    provisional_list = ", ".join(f["label"] for f in provisional_facets)
    proposed_list = ", ".join(f["label"] for f in proposed_facets)
    lines.append(f"provisional_relationships: [{provisional_list}]")
    lines.append(f"proposed_relationships: [{proposed_list}]")
    if author_overlap:
        lines.append("author_overlap: true")
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
    if len(provisional_facets) == 1:
        f = provisional_facets[0]
        lines.append(f"> *{f['label']}* (confidence: {f['confidence']:.2f}) — {f['justification'] or '(no justification recorded)'}")
    else:
        for f in provisional_facets:
            lines.append(f"### {f['label']} (confidence: {f['confidence']:.2f})")
            lines.append("")
            lines.append(f"> {f['justification'] or '(no justification recorded)'}")
            lines.append("")
    lines.append("")
    lines.append(
        "This was produced from title/abstract/venue alone, without reading "
        "the paper — treat it as a placeholder guess, not a finding."
    )
    lines.append("")

    lines.append("## Full-Text Reading (proposed — pending human review)")
    lines.append("")
    proposed = finding["proposed"]
    provisional_labels = {f["label"] for f in provisional_facets}
    agree_note = (
        "confirms the provisional guess" if proposed["agrees_with_provisional"]
        else f"differs from the provisional guess (was: *{provisional_rel}*)"
    )
    if len(proposed_facets) == 1:
        lines.append(
            f"> *{proposed_rel}* (confidence: {proposed['confidence']:.2f}) — {proposed['justification']}"
        )
        lines.append(f"> ({agree_note})")
        lines.append("")
        _append_facet_quotes(lines, proposed_facets[0]["quotes"])
    else:
        lines.append(f"*({agree_note})*")
        lines.append("")
        for f in proposed_facets:
            lines.append(f"### {f['label']} (confidence: {f['confidence']:.2f})")
            lines.append("")
            lines.append(f"> {f['justification']}")
            if f["label"] in provisional_labels:
                lines.append(">")
                lines.append("> (confirms one of the provisional guesses)")
            lines.append("")
            _append_facet_quotes(lines, f["quotes"])

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
    (wake-out/<seed>/pdfs/<citing-id>.pdf.json) regardless of force, so anyone
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

    wd = evidence_dir(seed_id, base)
    wd.mkdir(parents=True, exist_ok=True)
    md_path = dossier_path(seed_id, citing_id, base)
    json_path = dossier_json_path(seed_id, citing_id, base)

    # JSON is canonical; the .md is a deterministic render derived from it
    # (see rerender_dossier_md(), which always reads the .json as source
    # of truth and never the .md) -- so JSON is written first. If the
    # process is interrupted between the two writes below, the result is
    # a .json with no .md yet, which `wake evidence --rerender-all` or
    # `wake rebuild` (see build.py) can regenerate purely from the JSON
    # with no LLM call. The reverse order (a .md with no .json backing
    # it) is not recoverable the same way, since every rebuild_*/
    # rerender_* function in evidence_wiki.py/evidence.py treats the
    # .json sidecars as the sole source of truth and globs *.json, never
    # *.md.
    #
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
    EvidenceDossier.validate_or_raise(json_payload, context=f"evidence dossier {citing_id!r}")
    atomic_write_json(json_path, json_payload)

    md_text = _render_dossier_markdown(
        seed_work, citing_work, finding,
        pdf_path=Path(pdf_path_str), pdf_source=pdf_source,
        extracted_text_path_str=extracted_text_path_str,
        base=base,
    )
    atomic_write_text(md_path, md_text)

    if verbose:
        print(f"[wake] Dossier written: {md_path}", file=sys.stderr)

    from .evidence_wiki import append_log_entry, rebuild_index, rebuild_wiki_orientation
    event = "dossier_rebuilt" if force else "dossier_built"
    append_log_entry(
        seed_id, event=event, citing_id=citing_id,
        detail=f"proposed: {finding['proposed']['relationship']} ({len(finding['quotes'])} quotes)",
        seed_title=seed_work.get("title"), base=base,
    )
    rebuild_index(seed_id, seed_title=seed_work.get("title"), base=base)
    rebuild_wiki_orientation(seed_id, seed_work, base=base)

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
        EvidenceDossier.validate_or_raise(normalized, context=f"evidence dossier {citing_id!r}")
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
