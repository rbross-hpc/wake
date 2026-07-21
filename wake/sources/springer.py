# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Springer direct-PDF URL construction.

Unlike the other sources in wake's PDF acquisition chain, this is not an
API lookup — Springer serves PDFs for its DOIs at a predictable URL:

    https://link.springer.com/content/pdf/<DOI>.pdf

No search, no API key, no rate-limited lookup call. When it works, it's
often the fastest and most reliable source for Springer-published
conference proceedings and book chapters (LNCS, Springer journals) that
Unpaywall/Semantic Scholar/OSTI don't index — this fixed-URL trick was
confirmed to work for several older PnetCDF-citing LNCS chapters during a
2026 evidence-gathering session that Unpaywall/OSTI/S2/arXiv all missed.

Not every Springer DOI resolves this way (paywalled content returns an
HTML paywall/login page instead of a PDF — `pdf_fetch.py`'s
`_looks_like_pdf` check catches this and the chain falls through to the
next source), and this only applies to Springer's own DOI prefix
(10.1007) — other publishers' DOIs are never attempted.

Page-count / file-size note: page counts reported by external tools
(curl --head Content-Length, pdfinfo, etc.) for Springer PDFs can be
misleading -- a valid Springer PDF may report a smaller byte count at
the HTTP layer than its actual content (observed during a 2026 session
when a real LNCS chapter PDF was dismissed based on a curl-reported
page count that didn't match the rendered document). wake does not add
a page-count validation step for Springer specifically; the existing
`_looks_like_pdf` (magic bytes) + `min_valid_pdf_bytes` checks in
`pdf_fetch._download` are sufficient. Do not add a page-count gate
based on external tool output for Springer URLs.
"""
from __future__ import annotations

import re

_SPRINGER_DOI_PREFIX = "10.1007/"


def _normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi or None


def get_fulltext_pdf_url_by_doi(doi: str) -> str | None:
    """Return the predictable Springer PDF URL for *doi*, or None if *doi*
    isn't a Springer DOI (prefix 10.1007).

    No network call is made here — this only constructs a URL to try; the
    caller (pdf_fetch.py) is responsible for downloading and validating
    it's actually a PDF (paywalled content serves an HTML page instead).
    """
    norm = _normalize_doi(doi)
    if not norm or not norm.lower().startswith(_SPRINGER_DOI_PREFIX):
        return None
    return f"https://link.springer.com/content/pdf/{norm}.pdf"
