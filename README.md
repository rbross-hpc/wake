# wake

Evidence-backed impact analysis for research papers — designed to be driven
by an agent (e.g. Claude via opencode) on a human's behalf, not run as a
one-shot autopilot.

Given a seed paper (DOI, arXiv ID, OpenAlex ID, or title), `wake`:

1. Resolves the seed to a canonical [OpenAlex](https://openalex.org) record.
2. Fetches every work that cites the seed (via `filter=cites:<id>`).
3. Generates a one-paragraph LLM description of the seed's contribution.
4. LLM-classifies each citing work's relationship to the seed.
5. Bakes a Markdown impact brief with reach metrics, citation trends, and ranked evidence.

Beyond the brief, `wake` also supports deeper, evidence-backed work: full-
text verification of a specific finding (`wake evidence`), combined-
evidence thematic synthesis (`wake theme`), and narrative drafting from
confirmed themes with per-sentence source references (`wake narrative`).
See [`docs/`](docs/) for the full topic breakdown.

## Design: explore-first, not autopilot

There is no single "run everything" command. `wake` provides thin,
JSON-emitting primitives that an agent composes into a workflow: resolve
and confirm the seed, sample a handful of citing works, classify the
sample and check with the human, review the estimated cost to finish,
then scale up. See
[`wake/skills/impact-analysis/SKILL.md`](wake/skills/impact-analysis/SKILL.md)
for the full recommended workflow — this is the primary way the tool is
meant to be used.

## Install

```bash
pip install -e ".[dev]"

# Optional: PDF abstract extraction (wake fill-abstract --from-pdf)
pip install -e ".[dev,pdf]"
```

## Quick Start

```bash
export OPENAI_API_KEY=your-key
export OPENAI_BASE_URL=https://apps-stage.inside.anl.gov/argoapi/v1
export OPENALEX_MAILTO=you@example.com

wake --json config validate                   # setup check — run once per session
wake --json resolve "10.1145/1048935.1050189" # confirm the seed
wake --json citing "10.1145/1048935.1050189" --sort cited-by
wake --json sample "10.1145/1048935.1050189" -n 10   # free — no LLM calls
wake --json classify "10.1145/1048935.1050189" --limit 10 --sort cited-by
wake --json status "10.1145/1048935.1050189"  # check cost before scaling
wake --json classify "10.1145/1048935.1050189"
wake --json bake "10.1145/1048935.1050189"

# Output: wake-out/W2156077349/impact.md
```

See [`docs/workflow.md`](docs/workflow.md) for the full command list
(including abstract-gap escalation, full-text verification, themes, and
narrative drafting) and the recommended step-by-step sequence.

Every command supports `--json` for machine-readable output (a stable
envelope: `{"wake_version", "command", "ok", "data"}` or `{"ok": false,
"error": {...}}`), and human-readable text otherwise. Global flags:
`--json`, `--work-dir DIR` (or `WAKE_WORK_DIR` env var), `--verbose`.

## Documentation

| Doc | Covers |
|---|---|
| [`docs/workflow.md`](docs/workflow.md) | Full command list, quick-start walkthrough, seed ID formats, relationship classes |
| [`docs/abstract-recovery.md`](docs/abstract-recovery.md) | Automatic + manual OpenAlex abstract backfill |
| [`docs/pdf-sources.md`](docs/pdf-sources.md) | The `wake fetch-pdf` source chain |
| [`docs/evidence.md`](docs/evidence.md) | Provisional → proposed → verified lifecycle, the evidence wiki |
| [`docs/themes.md`](docs/themes.md) | Combined-evidence thematic synthesis (`wake theme`) |
| [`docs/narrative.md`](docs/narrative.md) | Narrative drafting from confirmed themes (`wake narrative`) |
| [`wake/skills/impact-analysis/SKILL.md`](wake/skills/impact-analysis/SKILL.md) | The agent-facing workflow guide (primary way this tool is meant to be used) |
| [`BACKLOG.md`](BACKLOG.md) | Roadmap, design decisions, and open questions |

## Configuration

Create `wake.config.yaml` in your working directory (or run `wake config init`):

```yaml
models:
  describe: "Claude Sonnet 4.6"
  classify: "Claude Sonnet 4.6"
  pdf_abstract_extract: "Claude Sonnet 4.6"
  evidence: "Claude Sonnet 4.6"

openalex:
  rate_limit_s: 1.0

cost:
  rates_per_1k_usd:
    "Claude Sonnet 4.6": {in: 0.003, out: 0.015}
```

Run `wake config show` to see the full resolved configuration, including
sections not shown above (`abstract_backfill`, `gaps`, `pdf_extract`,
`pdf_fetch`, `evidence`, `classify`, `report`).

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

## Output Layout

See [`wake/skills/impact-analysis/references/output-layout.md`](wake/skills/impact-analysis/references/output-layout.md)
for the full `wake-out/<seed>/` directory tree.

## Tests

```bash
# Offline only
pytest tests/ -m 'not network'

# Including live network tests
pytest tests/
```

## License

BSD 3-Clause. Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
