# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Seed-paper PDF acquisition and text extraction (Pass 1 -- acquire and
store only; no downstream consumers wired in this pass).

The seed paper's PDF lives at wake-out/<seed>/seed.pdf, distinct from
pdfs/ which holds citing-work PDFs only. Extracted text lives alongside
it at wake-out/<seed>/seed.pdf.json, following the same sibling-caching
convention as citing-work PDFs.

Two paths to getting the seed PDF:
  - Automatic: the configured fetch chain (OSTI, S2, Unpaywall, Springer,
    arXiv, CORE) is tried at wake resolve time. Silently skips on failure
    and records the attempt in seed.json and evidence/log.md.
  - Manual: `wake seed fetch-pdf <seed> --from-pdf PATH` with the same
    three-signal metadata check as `wake evidence --from-pdf`.

On success or failure, seed.json gains a "seed_pdf" sub-object:
  success: {"path": "...", "extracted_text_path": "...", "source": "...", "fetched_at": "..."}
  failure: {"path": null, "extracted_text_path": null, "source": null,
            "attempted_at": "...", "tried": [...], "fallback_links": {...}}
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .io import atomic_write_json, now_iso
from .pdf_fetch import fallback_links, fetch_seed_pdf, seed_pdf_path
from .seed import load_seed, work_dir


def seed_extracted_text_path(seed_id: str, base: Path | None = None) -> Path:
    return seed_pdf_path(seed_id, base).with_suffix(".pdf.json")


def _extract_seed_text(seed_pdf: Path, *, verbose: bool = False) -> str | None:
    """Extract full text from the seed PDF. Returns None if extraction
    fails (scanned PDF, no text layer) -- not fatal, PDF is still cached."""
    try:
        from .sources.pdf_fulltext import extract_full_text_from_pages, extract_pages_cached
        pages = extract_pages_cached(str(seed_pdf))
        text = extract_full_text_from_pages(pages)
        return text if text.strip() else None
    except Exception as exc:
        if verbose:
            print(f"[wake] WARN: seed PDF text extraction failed: {exc}", file=sys.stderr)
        return None


def _update_seed_json(seed_id: str, seed_pdf_info: dict[str, Any], base: Path | None) -> None:
    """Persist the seed_pdf sub-object into seed.json."""
    cached = load_seed(seed_id, base) or {}
    cached["seed_pdf"] = seed_pdf_info
    p = work_dir(seed_id, base) / "seed.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, cached)


def acquire_seed_pdf(
    seed_work: dict[str, Any],
    *,
    base: Path | None = None,
    force: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Fetch the seed paper's PDF and extract its text. Updates seed.json
    with a seed_pdf sub-object recording the result.

    Returns a result dict:
      {"ok": True, "path": "...", "extracted_text_path": "...", "source": "..."}
    or
      {"ok": False, "tried": [...], "fallback_links": {...}}
    """
    seed_id = seed_work["openalex_id"]
    result = fetch_seed_pdf(seed_work, base=base, force=force, verbose=verbose)

    if result["ok"]:
        pdf_p = Path(result["path"])
        if verbose:
            print(f"[wake] Extracting seed PDF text: {pdf_p}", file=sys.stderr)
        text = _extract_seed_text(pdf_p, verbose=verbose)
        ext_path = seed_extracted_text_path(seed_id, base)
        extracted_text_path_str = str(ext_path) if text is not None else None
        if text is None and verbose:
            print("[wake] WARN: could not extract text from seed PDF (scanned?). "
                  "PDF is still cached.", file=sys.stderr)

        seed_pdf_info = {
            "path": result["path"],
            "extracted_text_path": extracted_text_path_str,
            "source": result["source"],
            "fetched_at": now_iso(),
        }
        _update_seed_json(seed_id, seed_pdf_info, base)

        return {
            "ok": True,
            "path": result["path"],
            "extracted_text_path": extracted_text_path_str,
            "source": result["source"],
        }

    else:
        seed_pdf_info = {
            "path": None,
            "extracted_text_path": None,
            "source": None,
            "attempted_at": now_iso(),
            "tried": result.get("tried", []),
            "fallback_links": result.get("fallback_links", {}),
        }
        _update_seed_json(seed_id, seed_pdf_info, base)

        return {
            "ok": False,
            "tried": result.get("tried", []),
            "fallback_links": result.get("fallback_links", {}),
        }


def acquire_seed_pdf_from_path(
    seed_work: dict[str, Any],
    supplied_path: str | Path,
    *,
    base: Path | None = None,
    force: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Validate and ingest a human-supplied seed PDF. Uses the same three-
    signal metadata check as `wake evidence --from-pdf`. On match, copies
    to seed.pdf and extracts text. On mismatch, refuses unless --force
    (mismatch is always logged).

    Returns the same result shape as acquire_seed_pdf.
    """
    import shutil
    from .evidence_wiki import append_log_entry
    from .pdf_verify import check_pdf_metadata
    from .sources.pdf_abstract import extract_lead_text

    seed_id = seed_work["openalex_id"]
    supplied = Path(supplied_path).expanduser().resolve()
    if not supplied.exists():
        raise FileNotFoundError(f"PDF not found: {supplied}")

    if verbose:
        print(f"[wake] Extracting lead text for metadata check: {supplied}", file=sys.stderr)
    lead_text = extract_lead_text(supplied, max_pages=3)
    check = check_pdf_metadata(seed_work, lead_text)

    log_event = "seed_pdf_supplied_verified" if check["ok"] else "seed_pdf_supplied_mismatch"
    if not check["ok"] and force:
        log_event = "seed_pdf_forced_despite_mismatch"
    append_log_entry(
        seed_id, event=log_event, citing_id=seed_id,
        detail=(
            f"title_sim={check['title_similarity']:.2f} "
            f"author={check['author_matched']} "
            f"doi={check['doi_found']}"
        ),
        seed_title=seed_work.get("title"), base=base,
    )

    if not check["ok"] and not force:
        raise ValueError(check["message"])

    dest = seed_pdf_path(seed_id, base)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(supplied, dest)
    if verbose:
        print(f"[wake] Seed PDF copied to: {dest}", file=sys.stderr)
        if not check["ok"]:
            print(f"[wake] WARN: metadata mismatch overridden (--force): {check['message']}", file=sys.stderr)

    if verbose:
        print(f"[wake] Extracting seed PDF text: {dest}", file=sys.stderr)
    text = _extract_seed_text(dest, verbose=verbose)
    ext_path = seed_extracted_text_path(seed_id, base)
    extracted_text_path_str = str(ext_path) if text is not None else None

    seed_pdf_info = {
        "path": str(dest),
        "extracted_text_path": extracted_text_path_str,
        "source": "supplied",
        "fetched_at": now_iso(),
    }
    _update_seed_json(seed_id, seed_pdf_info, base)

    return {
        "ok": True,
        "path": str(dest),
        "extracted_text_path": extracted_text_path_str,
        "source": "supplied",
    }
