# Agent Skill: wake — Impact Analysis

## Purpose

Use the `wake` CLI to produce evidence-backed impact briefs for research papers.
Given a seed paper (DOI, arXiv ID, OpenAlex ID, or title), wake:

1. Resolves the seed to a canonical OpenAlex record.
2. Fetches every work that cites the seed (via OpenAlex `filter=cites:<id>`).
3. Generates a one-paragraph LLM description of the seed's contribution.
4. LLM-classifies each citing work's relationship to the seed (extends / builds-on / uses-as-tool / benchmarks / applies-to-domain / background-mention).
5. Renders a Markdown impact brief with reach metrics, citation trends, and ranked evidence.

## Commands

```bash
# Full pipeline — recommended entry point
wake brief <seed>

# Individual stages
wake resolve <seed>          # Resolve seed → canonical OpenAlex work
wake citing  <seed>          # Fetch & cache all citing works
wake describe <seed>         # LLM contribution paragraph
wake classify <seed>         # LLM relationship classification (resumable)

# Inspect cached results
wake show brief   <seed>     # Print impact.md
wake show metrics <seed>     # Print impact.json
wake show top     <seed>     # Top-evidence table

# Config & plumbing
wake config show
wake config validate
wake config init
```

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
  seed.json        — resolved seed + LLM description
  citing.json      — all citing works (paginated, cached)
  classified.json  — per-citing-work relationship + evidence
  impact.json      — aggregated metrics
  impact.md        — the impact brief
  .state.json      — version/cache keys
  .classify/       — per-work sidecar (resumable)
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM API key (required for describe/classify) |
| `OPENAI_BASE_URL` | API endpoint (e.g. Argo: `https://apps-stage.inside.anl.gov/argoapi/v1`) |
| `OPENALEX_MAILTO` | Your email for OpenAlex polite pool (recommended) |

## Tips for Agents

- **Always run `wake resolve <seed>` first** to confirm the seed is found and note the OpenAlex ID.
- **`wake brief` is idempotent** — re-running skips cached stages.
- **`wake classify` is resumable** — safe to Ctrl-C and re-run; already-classified works are skipped.
- If `OPENALEX_MAILTO` is not set, a warning is printed but the tool continues.
- The `impact.md` brief is the primary deliverable; share it directly or summarize it.
