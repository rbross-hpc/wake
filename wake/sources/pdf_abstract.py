# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Extract an abstract from the first few pages of a local PDF.

Used only as a human-driven escalation path (wake fill-abstract --from-pdf)
for high-value citing works that OSTI/Semantic Scholar backfill couldn't
recover an abstract for. Never runs automatically or in bulk.

If the abstract isn't in the first few pages, it isn't in the paper's
front matter at all — so we deliberately extract only a small page window
(default: 3) rather than the full document. This keeps both the extraction
and the downstream LLM cleanup call cheap (a few hundred words, not a
full paper).

Uses pypdf with a pdfplumber fallback (same pattern as ref-checker's
pdf.py), both permissively licensed (BSD-3 / MIT) — no PyMuPDF (AGPL) or
heavyweight ML-based PDF parsers.
"""
from __future__ import annotations

from pathlib import Path


def extract_lead_text(path: Path | str, max_pages: int = 3) -> str:
    """Return the text of the first *max_pages* pages of the PDF at *path*.

    Raises FileNotFoundError if the path doesn't exist. Returns an empty
    string if neither pypdf nor pdfplumber can extract usable text (e.g.
    a scanned PDF with no text layer at all) — callers should treat an
    empty result as "extraction failed", not "no abstract present".
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    text = _try_pypdf(path, max_pages)
    if not text or len(text.strip()) < 100:
        text = _try_pdfplumber(path, max_pages)
    return text


def _try_pypdf(path: Path, max_pages: int) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages[:max_pages]:
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages.append(page_text.strip())
        return "\n\n".join(pages)
    except Exception:
        return ""


def _try_pdfplumber(path: Path, max_pages: int) -> str:
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "PDF extraction requires pypdf or pdfplumber. "
            "Install with: pip install 'wake[pdf]'"
        )
    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages[:max_pages]:
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages.append(page_text.strip())
    return "\n\n".join(pages)
