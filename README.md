# wake

Evidence-backed impact analysis for research papers — designed to be driven
by an agent (e.g. Claude via opencode) on a human's behalf, not run as a
one-shot autopilot.

Given a seed paper (DOI, arXiv ID, OpenAlex ID, or title), `wake`:

1. Resolves the seed to a canonical [OpenAlex](https://openalex.org) record.
2. Fetches every work that cites the seed (via `filter=cites:<id>`).
3. Generates a one-paragraph LLM description of the seed's contribution.
4. LLM-classifies each citing work's relationship to the seed.
5. Renders a Markdown impact brief with reach metrics, citation trends, and ranked evidence.

## Design: explore-first, not autopilot

There is no single "run everything" command. `wake` provides thin,
JSON-emitting primitives — `resolve`, `citing`, `sample`, `describe`,
`classify`, `render`, `status`, `cost`, `override` — that an agent composes
into a workflow: resolve and confirm the seed, sample a handful of citing
works, classify the sample and check with the human, review the estimated
cost to finish, then scale up. See
[`wake/skills/impact-analysis/SKILL.md`](wake/skills/impact-analysis/SKILL.md)
for the full recommended workflow — this is the primary way the tool is
meant to be used.

## Install

```bash
pip install -e ".[dev]"

# Optional: PDF abstract extraction (wake fill-abstract --from-pdf)
pip install -e ".[dev,pdf]"
```

## Quick Start (as an agent would run it)

```bash
export OPENAI_API_KEY=your-key
export OPENAI_BASE_URL=https://apps-stage.inside.anl.gov/argoapi/v1
export OPENALEX_MAILTO=you@example.com

wake --json resolve "10.1145/1048935.1050189"          # confirm the seed
wake --json citing "10.1145/1048935.1050189" --sort cited-by
wake --json sample "10.1145/1048935.1050189" -n 10     # free — no LLM calls
wake --json classify "10.1145/1048935.1050189" --limit 10 --sort cited-by
wake --json status "10.1145/1048935.1050189"           # check cost before scaling
wake --json classify "10.1145/1048935.1050189"         # classify everything
wake --json render "10.1145/1048935.1050189"

# Output: wake-out/W2156077349/impact.md
```

Every command supports `--json` for machine-readable output (a stable
envelope: `{"wake_version", "command", "ok", "data"}` or `{"ok": false,
"error": {...}}`), and human-readable text otherwise.

## Commands

| Command | Purpose |
|---------|---------|
| `wake resolve <seed>` | Resolve seed → canonical OpenAlex work |
| `wake status <seed>` | Cached-artifact counts + estimated remaining cost — start here |
| `wake citing <seed>` | Fetch & cache all citing works (`--sort`, `--min-year`, `--limit`) |
| `wake sample <seed>` | Representative slice of citing works for review (free, no LLM) |
| `wake describe <seed>` | LLM one-paragraph contribution description |
| `wake classify <seed>` | LLM relationship classification (`--ids`, `--limit`, `--sort`, `--dry-run`, resumable) |
| `wake gaps <seed>` | Surface high-value citing works with no recoverable abstract |
| `wake fill-abstract <seed> <id>` | Manually resolve one via `--from-pdf` or `--text` |
| `wake fetch-pdf <seed> <id>` | Try to automatically acquire a PDF (OSTI, Semantic Scholar, Unpaywall, arXiv, optional CORE) |
| `wake evidence <seed> <id>` | Full-text verification: reads the whole PDF, proposes a relationship with quoted, page-cited passages |
| `wake render <seed>` | Assemble `impact.md` + `impact.json` from whatever is classified so far |
| `wake override <seed> <id>` | Record a human-reviewed relationship correction (`--verification-source human-judgment\|evidence-dossier`) |
| `wake cost <seed>` | Estimated LLM token/cost usage so far |
| `wake show brief <seed>` | Print cached impact.md |
| `wake show metrics <seed>` | Print cached impact.json |
| `wake show top <seed>` | Top-evidence table |
| `wake config show/validate/init` | Configuration plumbing |
| `wake skill show/export` | Bundled Agent Skill |

Global flags: `--json`, `--work-dir DIR` (or `WAKE_WORK_DIR` env var),
`--verbose` (keep progress banners under `--json`).

## Seed ID Formats

| Format | Example |
|--------|---------|
| DOI | `10.1145/1048935.1050189` |
| arXiv ID | `2301.04567` |
| OpenAlex ID | `W2156077349` |
| Paper title | `"Parallel netCDF: A High-Performance Scientific I/O Interface"` |

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
  pdfs/                   — locally-cached PDFs (wake fetch-pdf / wake evidence)
    <citing-id>.pdf         — the PDF itself
    <citing-id>.json        — its extracted text, cached (see below)
  evidence/               — full-text verification dossiers (wake evidence)
    <citing-id>.md          — human/agent-readable OKF concept document
    <citing-id>.json        — same finding, structured
```

## Relationship Classes

| Class | Meaning |
|-------|---------|
| `extends` | Directly extends the method/framework of the seed |
| `builds-on` | Builds a new system/tool on top of the seed |
| `uses-as-tool` | Uses the seed's software/tool/dataset as-is |
| `benchmarks` | Benchmarks against the seed as a baseline |
| `applies-to-domain` | Applies the seed's approach to a new domain |
| `related-infrastructure` | Complementary tooling in the same ecosystem, no direct dependency |
| `background-mention` | Cites as background/related work |

## Abstract Recovery

~20% of citing works typically lack an OpenAlex abstract, forcing lower-
confidence title/venue-only classification. `wake` recovers most of these
automatically and lazily (only for works actually selected for
classification, never eagerly for the full citing set):

1. **Automatic backfill** (`classify` does this transparently): tries
   [OSTI](https://www.osti.gov) (DOE-funded work, via its `description`
   field), then [Semantic Scholar](https://www.semanticscholar.org)
   (broader coverage). Free, unauthenticated, no PDF dependency.
2. **Manual escalation** for high-value works that step 1 couldn't resolve:
   ```bash
   wake gaps <seed>                          # surface candidates, ranked by influence
   wake fill-abstract <seed> <id> --from-pdf paper.pdf   # extract from PDF lead pages + LLM cleanup
   wake fill-abstract <seed> <id> --text "..."           # or paste the abstract directly
   wake classify <seed> --ids <id> --force   # re-classify with the recovered abstract
   ```
   `--from-pdf` only ever reads the first few pages (config
   `pdf_extract.max_pages`, default 3) — if the abstract isn't in the front
   matter, it isn't reported as found. Requires the `pdf` extra
   (`pip install 'wake[pdf]'`).

Recovered abstracts are tagged with their source (`abstract_source`:
`osti`, `semanticscholar`, `pdf-extract`, or `human-text`) and the count is
shown in the brief's Reach section.

## PDF Acquisition

```bash
wake fetch-pdf <seed> <citing-id>
```

Tries a chain of open-access sources, all API-based (no scraping publisher
landing pages, no sci-hub-style sources), and saves the first valid PDF to
`wake-out/<seed>/pdfs/<citing-id>.pdf`:

1. **OSTI** — direct `fulltext` link (DOE-funded work, no auth wall)
2. **Semantic Scholar** — `openAccessPdf.url` (often a repository/arXiv copy)
3. **Unpaywall** — best-OA-location PDF URL (frequently blocked by
   publisher sites — still worth attempting)
4. **arXiv** — title-search match (always freely downloadable when found)
5. **CORE.ac.uk** — optional, requires `CORE_API_KEY`, silently skipped if unset

A downloaded file that isn't a valid PDF (e.g. a paywall HTML page saved
with a `.pdf` extension) is rejected and the chain falls through to the
next source. If every source fails, `fetch-pdf` returns human-actionable
links instead of giving up silently: an Unpaywall lookup page, a Google
Scholar search for the title, the publisher's DOI link, and a CORE.ac.uk
search URL.

Reusable on its own (e.g. before `wake fill-abstract --from-pdf`, to skip
a manual download step) and cached — re-running is a no-op unless `--force`
is passed.

## Verification Lifecycle (provisional → proposed → verified)

`classify` only ever reads a citing work's title/abstract/venue — never
the actual paper — so every classification it produces is labeled
`"verification_status": "provisional"`: a placeholder guess, not a
finding, regardless of how high its confidence score looks.

```bash
wake evidence <seed> <citing-id>
```

`wake evidence` fetches a PDF (same chain as `fetch-pdf`), reads the
*entire* document, and independently judges the relationship — quoting
full paragraphs verbatim, with page numbers, for every claim it makes. It
never fabricates a passage: if the seed paper isn't actually discussed in
the text, it says so and returns an empty quote list rather than
inventing evidence. The result is a `"proposed"` finding, written to an
OKF-style dossier (`wake-out/<seed>/evidence/<citing-id>.md`) — but it is
**never auto-applied**. Only a human-approved `wake override` call
promotes a finding to `"verified"`:

```bash
wake override <seed> <citing-id> --relationship extends \
  --justification "<quoted evidence>" --verification-source evidence-dossier
```

The rendered brief tags every entry accordingly:
`[PROVISIONAL — abstract-only, not yet checked against full text]`,
`[VERIFIED via full-text reading]`, or `[VERIFIED via human judgment]`
(a plain override with no dossier behind it), plus a one-line
provisional/verified count summary in "Nature of Impact."

This tool never asks a human to run a CLI command themselves — an agent
using `wake` always presents a `wake evidence` finding (pasting the
literal quoted passages, in context) and runs the resulting `override`
call on the human's behalf. See `SKILL.md` for the full workflow.

Full-text extraction is page-level only (no MinerU, no paragraph-boundary
detection — multi-column academic layouts don't extract reliably enough
for that); the LLM is asked to quote the full containing paragraph
verbatim around any passage it relies on. Requires the `pdf` extra
(`pip install 'wake[pdf]'`), same as `fill-abstract --from-pdf`.

### Inspecting what the model actually read

Every extraction is cached next to the PDF it came from:
`wake-out/<seed>/pdfs/<citing-id>.json` (a sibling of `<citing-id>.pdf`),
keyed by the PDF file's sha256 so a re-fetched PDF invalidates it
automatically. If a `wake evidence` finding looks wrong, you can open
this file directly — no need to re-run anything — and check whether the
extraction itself was garbled (a common failure mode with multi-column
academic layouts) before concluding the model's *reasoning* was at
fault. The dossier's "Source" section always links to this file. `wake
evidence --force` re-runs extraction too (not just the LLM verification
pass), so a bad extraction can be retried even when the PDF itself
hasn't changed.

## Cost Telemetry (estimate-only)

`wake` does not depend on the LLM endpoint reporting token usage. Every
`describe`/`classify` call records a char-count-based token estimate to
`.cost.jsonl`. Unpriced models (no rate configured) report `cost_usd_est:
0.0` with `unpriced: true` rather than guessing. Add real rates under
`cost.rates_per_1k_usd` in config as they become known.

## Configuration

Create `wake.config.yaml` in your working directory (or run `wake config init`):

```yaml
models:
  describe: "Claude Sonnet 4.6"
  classify: "Claude Sonnet 4.6"

openalex:
  rate_limit_s: 1.0

cost:
  rates_per_1k_usd:
    "Claude Sonnet 4.6": {in: 0.003, out: 0.015}
```

## Environment Variables

Run `wake config validate` (or `wake --json config validate` for
structured output) to check these — required vars are blocking; missing
recommended/optional vars are surfaced but never fail validation.

| Tier | Variable | Purpose |
|------|----------|---------|
| Required | `OPENAI_API_KEY` | LLM API key (required for describe/classify) |
| Required | `OPENAI_BASE_URL` | API endpoint URL |
| Recommended | `OPENALEX_MAILTO` | Email for OpenAlex/Unpaywall/OSTI polite pool (faster, more reliable) |
| Optional | `SEMANTICSCHOLAR_API_KEY` | Raises Semantic Scholar's unauthenticated rate limit (~100 req/5min without one) |
| Optional | `CORE_API_KEY` | Enables CORE.ac.uk as a `wake fetch-pdf` source (free key at core.ac.uk/services/api) |
| Optional | `WAKE_WORK_DIR` | Default root for `wake-out/` cache (else cwd, or per-call `--work-dir`) |

## Tests

```bash
# Offline only
pytest tests/ -m 'not network'

# Including live network tests
pytest tests/
```

## License

BSD 3-Clause. Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
