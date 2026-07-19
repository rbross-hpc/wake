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
"""
from __future__ import annotations

from pathlib import Path


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
    marked inline rather than a list.
    """
    pages = extract_pages(path)
    parts = []
    for i, text in enumerate(pages, start=1):
        if text.strip():
            parts.append(f"[page {i}]\n{text.strip()}")
    return "\n\n".join(parts)


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
