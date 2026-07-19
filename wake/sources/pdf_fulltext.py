# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Extract full-document text from a local PDF, tagged by page number.

Used by wake evidence (full-text verification of a provisional
classification) — unlike sources/pdf_abstract.py, this reads the *entire*
document, not just the first few pages, since a supporting passage could
be anywhere (methods, results, even just a citation-list entry).

Deliberately page-level, not paragraph/line-level: this is wake's existing
lightweight-extraction design (pypdf/pdfplumber, no MinerU) applied to the
whole document. Multi-column academic PDF layouts interleave text
unreliably at extraction time (confirmed on our test fixture — pdfplumber
and pypdf both merge column text into a jumbled single stream per page),
so precise mechanical paragraph-boundary detection is not reliable here.
Instead, wake asks the verification LLM to quote a full paragraph's worth
of context around any supporting passage it identifies (see
evidence.py) — the model handles minor reading-order jumbling far better
than a mechanical paragraph splitter would, while we still get a real
page number for the citation.

Extraction is cached (extract_pages_cached / extracted_text_path) next to
the PDF itself, keyed by the PDF file's sha256. This exists so anyone
diagnosing an unexpected `wake evidence` finding can distinguish "the
extraction was garbled" from "the model reasoned poorly" by reading the
cache file directly, without needing to know anything about the evidence/
dossier that produced the finding, and without re-running extraction to
see what the LLM actually saw. A human can open the cache file in a text
editor or with `jq`; an agent debugging a surprising finding on the
human's behalf should read it too before assuming the model is at fault.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def extract_pages(path: Path | str) -> list[str]:
    """Return a list of per-page extracted text (index 0 = page 1).

    Raises FileNotFoundError if the path doesn't exist. A page that
    yields no extractable text (e.g. a scanned image page with no OCR
    layer) is represented as an empty string, not skipped — callers that
    report page numbers should keep this 1:1 with physical pages.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    pages = _try_pypdf(path)
    if not pages or not any(p.strip() for p in pages):
        pages = _try_pdfplumber(path)
    return pages


def extract_full_text(path: Path | str) -> str:
    """Return the whole document's text, with page markers, as one string.

    Convenience wrapper around extract_pages() for callers (e.g. the LLM
    prompt in evidence.py) that want a single string with page boundaries
    marked inline rather than a list. Not cached — see
    extract_pages_cached() for the cached equivalent, used by wake evidence.
    """
    return extract_full_text_from_pages(extract_pages(path))


def _try_pypdf(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    try:
        reader = PdfReader(str(path))
        return [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception:
        return []


def _try_pdfplumber(path: Path) -> list[str]:
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "PDF extraction requires pypdf or pdfplumber. "
            "Install with: pip install 'wake[pdf]'"
        )
    with pdfplumber.open(str(path)) as pdf:
        return [(page.extract_text() or "").strip() for page in pdf.pages]


def _extract_pages_with_extractor_name(path: Path) -> tuple[list[str], str]:
    """Like extract_pages(), but also reports which extractor actually
    produced the result — recorded in the cache file so a human or agent
    inspecting it later knows whether pypdf or the pdfplumber fallback
    was used (relevant since the two occasionally differ on garbled
    multi-column layouts)."""
    pages = _try_pypdf(path)
    if pages and any(p.strip() for p in pages):
        return pages, "pypdf"
    pages = _try_pdfplumber(path)
    return pages, "pdfplumber"


def extracted_text_path(pdf_path: Path | str) -> Path:
    """Return the cache file path for a given PDF's extracted text —
    always a sibling of the PDF itself (same directory, same stem, .json
    extension), e.g. wake-out/<seed>/pdfs/<citing-id>.pdf ->
    wake-out/<seed>/pdfs/<citing-id>.json. Deliberately co-located with
    the PDF rather than under evidence/: extraction is a property of the
    PDF file, not of any particular dossier, so any future caller (e.g. a
    DOE-signals reader, or a re-verification under a different prompt)
    can reuse it without depending on wake evidence's output layout.
    """
    p = Path(pdf_path)
    return p.with_suffix(".json")


def extract_pages_cached(
    pdf_path: Path | str,
    *,
    force: bool = False,
) -> list[str]:
    """Like extract_pages(), but caches the result next to the PDF
    (see extracted_text_path()), keyed by the PDF file's sha256.

    If a valid cache exists (same PDF content, i.e. sha256 matches) and
    force=False, returns the cached pages without touching pypdf/pdfplumber
    at all. If the PDF has changed since the cache was written (e.g. a
    fresh `wake fetch-pdf --force` swapped in a different file), the
    mismatch is detected automatically and extraction re-runs — no
    separate invalidation step needed. force=True always re-extracts
    (e.g. to recover from a bad extraction even when the PDF itself is
    unchanged).
    """
    from ..io import atomic_write_json, now_iso, read_json, sha256_bytes

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    pdf_bytes = path.read_bytes()
    pdf_sha256 = sha256_bytes(pdf_bytes)
    cache_path = extracted_text_path(path)

    if not force and cache_path.exists():
        try:
            cached: dict[str, Any] = read_json(cache_path)
        except (ValueError, OSError):
            cached = {}
        if cached.get("pdf_sha256") == pdf_sha256 and isinstance(cached.get("pages"), list):
            return cached["pages"]

    pages, extractor = _extract_pages_with_extractor_name(path)

    atomic_write_json(cache_path, {
        "pdf_path": str(path),
        "pdf_sha256": pdf_sha256,
        "extracted_at": now_iso(),
        "extractor": extractor,
        "pages": pages,
    })

    return pages


def extract_full_text_from_pages(pages: list[str]) -> str:
    """Join a list of per-page texts (e.g. from extract_pages_cached())
    into a single string with inline [page N] markers — the same format
    extract_full_text() produces, but operating on an already-extracted
    pages list rather than re-reading the PDF."""
    parts = []
    for i, text in enumerate(pages, start=1):
        if text.strip():
            parts.append(f"[page {i}]\n{text.strip()}")
    return "\n\n".join(parts)
