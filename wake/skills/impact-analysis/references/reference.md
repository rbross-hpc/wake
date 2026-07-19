# wake — Command & Output Reference

Detailed reference material for the `wake` CLI, split out from `SKILL.md`
(which stays focused on the explore-first workflow). See `SKILL.md` first
for how and when to use these.

## Seed ID Formats

| Format | Example |
|--------|---------|
| DOI | `10.1145/1048935.1050189` |
| arXiv ID | `2301.04567` |
| OpenAlex ID | `W2156077349` |
| Paper title | `"Parallel netCDF: A High-Performance Scientific I/O Interface"` |

## Full Command List

```bash
# Explore-first pipeline (see SKILL.md for sequencing/guidance)
wake --json resolve "<seed>"
wake --json citing "<seed>" [--sort cited-by|recent|oldest|random] [--min-year Y] [--limit N]
wake --json sample "<seed>" [-n N] [--sort ...]
wake --json classify "<seed>" [--ids ID,ID,...] [--limit N] [--sort ...] [--dry-run] [--force]
wake --json gaps "<seed>" [--min-cited-by N] [--no-auto-backfill-check]
wake --json fetch-pdf "<seed>" <citing-id> [--force]
wake --json fill-abstract "<seed>" <citing-id> --from-pdf PATH | --text TEXT
wake --json render "<seed>"
wake --json override "<seed>" <citing-id> --relationship <class> --justification "..."

# Standalone
wake --json describe "<seed>"      # LLM contribution paragraph (independent of classify)
wake --json cost "<seed>"          # cumulative estimated token/cost usage
wake --json show brief "<seed>"    # re-print cached impact.md
wake --json show metrics "<seed>"  # re-print cached impact.json
wake --json show top "<seed>" -n N # top-evidence table only
wake config show / validate / init
wake skill show / export PATH
```

Note: `--json` must appear before the subcommand (global flag), e.g.
`wake --json classify "<seed>"`, not `wake classify "<seed>" --json`.

Global flags: `--json`, `--work-dir DIR` (or `WAKE_WORK_DIR` env var, falls
back to cwd), `--verbose` (keep progress banners on stderr even under `--json`).

## Relationship Classes

Ordered by strength, strongest first:

| Class | Meaning |
|-------|---------|
| `extends` | Directly extends the method/framework/theory of the seed |
| `builds-on` | Builds a new system/tool that depends on the seed |
| `uses-as-tool` | Uses the seed's software/tool/dataset as-is |
| `benchmarks` | Benchmarks against the seed as a baseline |
| `applies-to-domain` | Applies the seed's approach to a new domain |
| `related-infrastructure` | Complementary tooling in the same ecosystem, no direct dependency |
| `background-mention` | Cites only as background/related work (including unclear/indirect relationships) |

## PDF Acquisition Chain (`wake fetch-pdf`)

Tried in order, all API-based (no scraping publisher landing pages, no
sci-hub-style sources):

1. **OSTI** — direct `fulltext` link (DOE-funded work, no auth wall)
2. **Semantic Scholar** — `openAccessPdf.url` (often a repository/arXiv copy)
3. **Unpaywall** — best-OA-location PDF URL (frequently blocked by
   publisher sites; still worth attempting)
4. **arXiv** — title-search match (always freely downloadable when found)
5. **CORE.ac.uk** — optional, requires `CORE_API_KEY`, silently skipped if unset

A downloaded file that isn't a valid PDF (e.g. a paywall HTML page saved
with a `.pdf` extension) is rejected and the chain falls through. On total
failure, returns human-actionable links: Unpaywall lookup page, Google
Scholar search for the title, publisher DOI link, CORE.ac.uk search URL.

## Output Layout

```
wake-out/<OpenAlex-ID>/
  seed.json               — resolved seed + LLM description
  citing.json             — all citing works (paginated, cached)
  classified.json         — per-citing-work relationship + evidence
  impact.json             — aggregated metrics
  impact.md               — the impact brief (notes coverage if partial)
  .state.json             — stage cache keys
  .classify/              — per-work classification sidecars (resumable)
  .cost.jsonl             — per-LLM-call estimated token/cost log
  .overrides.jsonl        — human-reviewed relationship overrides
  .manual_abstracts.jsonl — human/PDF-recovered abstracts (wake fill-abstract)
  pdfs/                   — locally-cached PDFs (wake fetch-pdf)
```

Use `--work-dir DIR` (or `WAKE_WORK_DIR` env var) to control where
`wake-out/` is created — useful when running from a scratch directory.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM API key (required for describe/classify) |
| `OPENAI_BASE_URL` | API endpoint (e.g. Argo) |
| `OPENALEX_MAILTO` | Your email for OpenAlex/Unpaywall polite pool (recommended) |
| `WAKE_WORK_DIR` | Default root for `wake-out/` cache |
| `SEMANTICSCHOLAR_API_KEY` | Optional — raises Semantic Scholar's rate limit |
| `CORE_API_KEY` | Optional — enables CORE.ac.uk in `wake fetch-pdf` (free key at core.ac.uk/services/api) |
