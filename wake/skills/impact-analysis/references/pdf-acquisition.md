# PDF Acquisition Chain (`wake fetch-pdf`)

Tried in order, mostly API-based (no scraping publisher landing pages, no
sci-hub-style sources):

1. **OSTI** — direct `fulltext` link (DOE-funded work, no auth wall)
2. **Semantic Scholar** — `openAccessPdf.url` (often a repository/arXiv copy)
3. **Unpaywall** — best-OA-location PDF URL (frequently blocked by
   publisher sites; still worth attempting)
4. **Springer** — predictable `link.springer.com/content/pdf/<DOI>.pdf` URL
   for Springer DOIs; no API call. Often succeeds for older LNCS
   conference chapters the other sources miss; a no-op otherwise.
5. **arXiv** — title-search match (always freely downloadable when found)
6. **CORE.ac.uk** — optional, requires `CORE_API_KEY`, silently skipped if unset

A downloaded file that isn't a valid PDF (e.g. a paywall HTML page saved
with a `.pdf` extension) is rejected and the chain falls through. On total
failure, returns human-actionable links: Unpaywall lookup page, Google
Scholar search for the title, publisher DOI link, CORE.ac.uk search URL.

Every real attempt (not a cache hit) is logged to `evidence/log.md` with
event `pdf_fetched` (success) or `pdf_fetch_failed` (all sources exhausted),
so `wake missing-pdfs` can later reconstruct which sources were tried and
whether any succeeded.

## Seed paper PDF (`wake seed fetch-pdf`)

The same source chain also acquires the seed paper's own PDF, tried
automatically every time `wake resolve` runs (silently on failure --
resolve is never blocked). The seed PDF lives at
`wake-out/<seed>/seed.pdf` (distinct from `pdfs/` which is citing works
only); extracted text at `wake-out/<seed>/seed.pdf.json`.

```bash
wake --json seed fetch-pdf "<seed>"
```

Response on success: `{"ok": true, "data": {"ok": true, "path": "...", "extracted_text_path": "...", "source": "osti"}}`.
Response on failure: `{"ok": false, "data": {"ok": false, "tried": [...], "fallback_links": {...}}}`.

If the automatic chain can't find it (e.g. the paper is behind a paywall
not covered by any configured source), the human will have a copy or can
get one. Once they do:

```bash
wake --json seed fetch-pdf "<seed>" --from-pdf /path/to/paper.pdf
```

Same three-signal metadata check as `wake evidence --from-pdf` (title
similarity, author surname, DOI in text). `--force` bypasses the
refusal on mismatch but still logs it. `wake status` shows whether the
seed PDF is cached.

The seed PDF is not yet wired into any command's LLM prompts (Pass 1 --
acquire and store only). Future passes will feed it into `wake describe`,
`wake evidence`, and eventually `wake narrative section audit`.

## Finding works still missing a PDF: `wake missing-pdfs`

`wake missing-pdfs <seed>` response shape:
```json
{
  "ok": true,
  "data": {
    "count": 3,
    "missing": [
      {
        "citing_id": "W111",
        "title": "...",
        "year": 2018,
        "cited_by_count": 42,
        "doi": "10.1234/...",
        "fetch_state": "exhausted",
        "last_attempted": "2026-07-20T05:00:00+00:00",
        "sources_tried": ["osti", "semanticscholar", "unpaywall", "springer"]
      }
    ]
  }
}
```
`fetch_state` is one of:
  - `"never-attempted"` — `wake fetch-pdf` has never been run for this work.
  - `"exhausted"` — tried and all sources failed; `sources_tried` lists what was attempted.
  - `"fetched-but-gone"` — the PDF was acquired at some point but the cached
    file is no longer on disk (e.g. manually deleted).

Filters applied: works with a cached PDF, excluded works, confirmed
duplicates, and works that already have a completed evidence dossier are all
excluded from the report. Optional `--min-cited-by N` / `--limit N`.
