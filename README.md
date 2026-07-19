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
| `wake render <seed>` | Assemble `impact.md` + `impact.json` from whatever is classified so far |
| `wake override <seed> <id>` | Record a human-reviewed relationship correction |
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

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM API key (required for describe/classify) |
| `OPENAI_BASE_URL` | API endpoint URL |
| `OPENALEX_MAILTO` | Email for OpenAlex polite pool (recommended) |
| `WAKE_WORK_DIR` | Default root for `wake-out/` cache (default: cwd) |

## Tests

```bash
# Offline only
pytest tests/ -m 'not network'

# Including live network tests
pytest tests/
```

## License

BSD 3-Clause. Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
