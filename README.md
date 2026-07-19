# wake

Evidence-backed impact analysis for research papers.

Given a seed paper (DOI, arXiv ID, OpenAlex ID, or title), `wake`:

1. Resolves the seed to a canonical [OpenAlex](https://openalex.org) record.
2. Fetches every work that cites the seed (via `filter=cites:<id>`).
3. Generates a one-paragraph LLM description of the seed's contribution.
4. LLM-classifies each citing work's relationship to the seed.
5. Renders a Markdown impact brief with reach metrics, citation trends, and ranked evidence.

## Install

```bash
pip install -e ".[dev]"
```

## Quick Start

```bash
# Set up environment
export OPENAI_API_KEY=your-key
export OPENAI_BASE_URL=https://apps-stage.inside.anl.gov/argoapi/v1
export OPENALEX_MAILTO=you@example.com

# Full pipeline: Parallel netCDF (2003)
wake brief 10.1145/1048935.1050189

# Output: wake-out/W2156077349/impact.md
```

## Commands

| Command | Purpose |
|---------|---------|
| `wake resolve <seed>` | Resolve seed → canonical OpenAlex work |
| `wake citing <seed>` | Fetch & cache all citing works |
| `wake describe <seed>` | LLM one-paragraph contribution description |
| `wake classify <seed>` | LLM relationship classification (resumable) |
| `wake brief <seed>` | Full pipeline → `wake-out/<id>/impact.md` |
| `wake show brief <seed>` | Print cached impact.md |
| `wake show metrics <seed>` | Print cached impact.json |
| `wake show top <seed>` | Top-evidence table |
| `wake config show` | Show resolved configuration |
| `wake config validate` | Validate config + environment |
| `wake config init` | Create starter `wake.config.yaml` |
| `wake skill show` | Print bundled Agent Skill |
| `wake skill export <path>` | Export skill to a directory |

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
  .classify/       — per-work classification sidecars (resumable)
```

## Relationship Classes

| Class | Meaning |
|-------|---------|
| `extends` | Directly extends the method/framework of the seed |
| `builds-on` | Builds a new system/tool on top of the seed |
| `uses-as-tool` | Uses the seed's software/tool/dataset as-is |
| `benchmarks` | Benchmarks against the seed as a baseline |
| `applies-to-domain` | Applies the seed's approach to a new domain |
| `background-mention` | Cites as background/related work |

## Configuration

Create `wake.config.yaml` in your working directory (or run `wake config init`):

```yaml
models:
  describe: "Claude Sonnet 4.7"
  classify: "Claude Sonnet 4.7"

openalex:
  rate_limit_s: 1.0
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM API key (required for describe/classify) |
| `OPENAI_BASE_URL` | API endpoint URL |
| `OPENALEX_MAILTO` | Email for OpenAlex polite pool (recommended) |

## Tests

```bash
# Offline only
pytest tests/ -m 'not network'

# Including live network tests
pytest tests/
```

## License

BSD 3-Clause. Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
