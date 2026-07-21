# PDF Acquisition

```bash
wake fetch-pdf <seed> <citing-id>
```

Tries a chain of open-access sources, mostly API-based (no scraping
publisher landing pages, no sci-hub-style sources), and saves the first
valid PDF to `wake-out/<seed>/pdfs/<citing-id>.pdf`:

1. **OSTI** — direct `fulltext` link (DOE-funded work, no auth wall)
2. **Semantic Scholar** — `openAccessPdf.url` (often a repository/arXiv copy)
3. **Unpaywall** — best-OA-location PDF URL (frequently blocked by
   publisher sites — still worth attempting)
4. **Springer** — predictable `link.springer.com/content/pdf/<DOI>.pdf`
   URL for Springer DOIs; no API call, just a direct download attempt.
   Often succeeds for older LNCS conference chapters that Unpaywall/OSTI/S2
   don't index; a no-op for non-Springer DOIs.
5. **arXiv** — title-search match (always freely downloadable when found)
6. **CORE.ac.uk** — optional, requires `CORE_API_KEY`, silently skipped if unset

A downloaded file that isn't a valid PDF (e.g. a paywall HTML page saved
with a `.pdf` extension) is rejected and the chain falls through to the
next source. If every source fails, `fetch-pdf` returns human-actionable
links instead of giving up silently: an Unpaywall lookup page, a Google
Scholar search for the title, the publisher's DOI link, and a CORE.ac.uk
search URL.

Reusable on its own (e.g. before `wake fill-abstract --from-pdf`, to skip
a manual download step) and cached — re-running is a no-op unless `--force`
is passed.

**Springer PDF validation note:** page counts or file sizes reported by
external tools (curl `--head`, `pdfinfo`, etc.) for Springer PDFs can be
misleading — a valid Springer LNCS PDF may report a smaller byte count at
the HTTP layer than its actual rendered content. wake's own validation
(magic bytes + minimum file size) is reliable for Springer; do not dismiss
a Springer PDF solely because an external tool reports a suspicious page or
byte count.
