# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Surface and resolve high-value citing works with no recoverable abstract.

Automatic backfill (backfill.py: OSTI, then Semantic Scholar) recovers
roughly half of missing abstracts for free. What's left is a smaller set of
"gaps" — citing works with no abstract from any automatic source. Most of
these are low-value (rarely-cited background mentions) and are fine to
classify from title+venue alone. A minority are themselves highly-cited,
consequential works where a better abstract would meaningfully improve
classification confidence and evidence quality — those are worth surfacing
to a human for manual resolution.

Two escalation paths, both explicit and human-driven (never automatic):
  1. `wake fill-abstract <seed> <id> --from-pdf <path>` — extract the first
     few pages of a locally-downloaded PDF and ask an LLM to pull out just
     the abstract (see abstract_extract.py / sources/pdf_abstract.py).
  2. `wake fill-abstract <seed> <id> --text "..."` — the human pastes the
     abstract directly (cheapest possible path, no LLM call at all).

Manually-filled abstracts are stored in a `.manual_abstracts.jsonl` sidecar
(same append-only, last-write-wins pattern as report.py's overrides) so
they survive re-fetching citing.json and are picked up by classify.py on
the next run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config
from .backfill import is_enabled as _backfill_enabled, backfill_one
from .io import atomic_write_text, now_iso, read_json
from .seed import work_dir

_MANUAL_ABSTRACTS_FILE = ".manual_abstracts.jsonl"


def manual_abstracts_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / _MANUAL_ABSTRACTS_FILE


def load_manual_abstracts(seed_id: str, base: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load human-supplied abstracts, keyed by citing OpenAlex ID.

    Later entries for the same ID win (append-only log; last write wins) —
    same pattern as report.py's overrides.
    """
    p = manual_abstracts_path(seed_id, base)
    if not p.exists():
        return {}
    entries: dict[str, dict[str, Any]] = {}
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
                entries[cid] = entry
    return entries


def add_manual_abstract(
    seed_id: str,
    citing_id: str,
    *,
    abstract: str,
    source: str,
    base: Path | None = None,
) -> dict[str, Any]:
    """Append a manually-resolved abstract for a citing work.

    *source* records provenance: 'human-text' (pasted directly) or
    'pdf-extract' (via wake fill-abstract --from-pdf).
    """
    entry = {
        "citing_id": citing_id,
        "abstract": abstract,
        "abstract_source": source,
        "filled_at": now_iso(),
    }
    p = manual_abstracts_path(seed_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def apply_manual_abstracts(
    works: list[dict[str, Any]],
    manual: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge human-supplied abstracts into citing works; they win over
    whatever (if anything) is already present, since a human resolved
    this specifically because automatic sources failed.
    """
    if not manual:
        return works
    result = []
    for w in works:
        wid = w.get("openalex_id")
        if wid in manual:
            entry = manual[wid]
            result.append({
                **w,
                "abstract": entry["abstract"],
                "abstract_source": entry["abstract_source"],
            })
        else:
            result.append(w)
    return result


def find_gaps(
    citing_works: list[dict[str, Any]],
    *,
    seed_id: str | None = None,
    base: Path | None = None,
    min_cited_by_count: int | None = None,
    limit: int | None = None,
    try_auto_backfill: bool = True,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Return high-value citing works with no recoverable abstract, ranked
    by their own cited_by_count (most consequential first).

    A work only counts as a "gap" if:
      - it has no OpenAlex abstract,
      - it isn't already resolved via a manual abstract,
      - (if try_auto_backfill) OSTI/Semantic Scholar also can't recover one
        (this does incur network calls — same cost as classify's lazy
        backfill — but only for works that would otherwise be candidates),
      - its own cited_by_count meets min_cited_by_count.
    """
    cfg = config.gaps_cfg()
    if min_cited_by_count is None:
        min_cited_by_count = cfg.get("min_cited_by_count", 20)
    if limit is None:
        limit = cfg.get("default_limit", 10)

    manual = load_manual_abstracts(seed_id, base) if seed_id else {}

    candidates = [
        w for w in citing_works
        if not w.get("abstract")
        and w.get("openalex_id") not in manual
        and (w.get("cited_by_count") or 0) >= min_cited_by_count
    ]
    candidates.sort(key=lambda w: -(w.get("cited_by_count") or 0))

    if limit is not None:
        candidates = candidates[: limit * 3 if try_auto_backfill else limit]

    gaps: list[dict[str, Any]] = []
    for w in candidates:
        if try_auto_backfill and _backfill_enabled():
            filled = backfill_one(w, verbose=verbose)
            if filled.get("abstract"):
                continue  # auto-backfill resolved it; not a gap
        gaps.append(w)
        if limit is not None and len(gaps) >= limit:
            break

    return gaps


def resolve_pdf_path(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"PDF not found: {p}")
    return p


def fill_from_pdf(
    seed_id: str,
    citing_id: str,
    pdf_path: str | Path,
    *,
    title_hint: str | None = None,
    base: Path | None = None,
) -> dict[str, Any]:
    """Extract an abstract from a local PDF's lead pages and record it.

    Extraction is deliberately limited to the first few pages
    (config.pdf_extract.max_pages, default 3) — if the abstract isn't in
    the front matter, it isn't in the paper. Raises ValueError if no
    abstract could be found in that window (extraction failure or
    genuinely absent); the citing work is left unresolved in that case.
    """
    from .abstract_extract import extract_abstract_from_lead_text
    from .sources.pdf_abstract import extract_lead_text

    cfg = config.pdf_extract_cfg()
    max_pages = cfg.get("max_pages", 3)

    p = resolve_pdf_path(pdf_path)
    lead_text = extract_lead_text(p, max_pages=max_pages)
    if not lead_text.strip():
        raise ValueError(
            f"Could not extract any text from the first {max_pages} page(s) of {p} "
            "(possibly a scanned PDF with no text layer)."
        )

    abstract = extract_abstract_from_lead_text(
        lead_text, title=title_hint, n_pages=max_pages,
        seed_id=seed_id, base=base,
    )
    if not abstract:
        raise ValueError(
            f"No abstract found in the first {max_pages} page(s) of {p}. "
            "Try increasing pdf_extract.max_pages in config, or supply the "
            "abstract directly with --text."
        )

    return add_manual_abstract(seed_id, citing_id, abstract=abstract, source="pdf-extract", base=base)


def fill_from_text(
    seed_id: str,
    citing_id: str,
    text: str,
    *,
    base: Path | None = None,
) -> dict[str, Any]:
    """Record a human-pasted abstract directly — no LLM call, no PDF."""
    text = text.strip()
    if not text:
        raise ValueError("Provided text is empty.")
    return add_manual_abstract(seed_id, citing_id, abstract=text, source="human-text", base=base)
