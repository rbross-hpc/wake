# wake

Evidence-backed citation-impact analysis for research papers — designed
to be driven by an agent (e.g. Claude via opencode) on a human's behalf,
not run as a one-shot autopilot.

Given a seed paper (DOI, arXiv ID, OpenAlex ID, or title), `wake` helps
an agent build a self-contained wiki at `wake-out/<seed>/` describing
*who cites this paper and how* — with an explicit distinction between
what an LLM guessed from a citing work's abstract and what has actually
been checked against the paper's full text.

The wiki grows as the workflow progresses. At each stage the agent
pauses so the human can confirm the seed, spot-check a sample of
classifications, and approve LLM spend before scaling up:

- **classify** — LLM tags every citing work with its relationship to
  the seed (`extends`, `uses-method-from`, `uses-data-from`,
  `applies-to-domain`, `benchmarks`, `related`, or
  `cites`), read only from title/abstract. **Every
  classification starts life as `provisional` — a placeholder guess,
  not a finding.**
- **evidence** — for a specific high-signal citing work, fetch its PDF,
  extract the text, and re-classify against the *actual body of the
  paper* — with the specific passages quoted, page-numbered, and
  written to a dossier. This produces a `proposed` finding; `wake
  override` then records the human's sign-off to make it `verified`.
- **theme** — synthesize multiple verified dossiers into a
  combined-evidence thematic document.
- **narrative** — draft prose grounded in the confirmed themes, with
  per-sentence citations back to the underlying evidence.

Throughout, `wake bake` re-aggregates whatever's currently on disk into
an impact brief (`impact.md`) — reach metrics, citation trends, and a
ranked evidence table, with every unverified row explicitly tagged
`[PROVISIONAL]` so a reader can't confuse a guess with a finding. It's
cheap and idempotent — rerun it any time a new verified finding,
confirmed theme, or narrative section is added.

There is no single "run everything" command. `wake` provides thin,
JSON-emitting primitives that an agent composes into this workflow;
see [`wake/skills/impact-analysis/SKILL.md`](wake/skills/impact-analysis/SKILL.md)
for the full recommended sequence — this is the primary way the tool
is meant to be used. See [`docs/`](docs/) for the full topic breakdown.

The wiki itself is designed to be opened directly (in Obsidian, on
GitHub, or in a plain editor) once wake is done — a `README.md` in the
output folder orients a human, and a companion `AGENTS.md` orients any
downstream agent handed just the folder. See
[`wake/skills/impact-analysis/references/output-layout.md`](wake/skills/impact-analysis/references/output-layout.md)
for the full directory layout.

## Getting Started

You'll mostly interact with `wake` by asking your agent to run it, not
by running it yourself.

### 1. Install wake

In your agent harness (opencode, Claude Code, or similar), ask:

> Please install wake from GitHub and export its bundled Agent Skill
> into this project so you know how to use it.

The agent should run something equivalent to:

```bash
pip install "wake[pdf] @ git+https://github.com/rbross-hpc/wake.git"
wake skill export .opencode/skills/wake
```

(`[pdf]` enables PDF-based abstract recovery. For opencode the
destination is `.opencode/skills/wake`; other harnesses — e.g. Claude
Code — use their own skills directory, so ask your agent to check its
documentation for the right path.)

`wake skill export` copies wake's bundled `SKILL.md` and reference
docs into your agent's skill directory. Without this, the agent has
the CLI available but no sense of *when* to sample vs. scale up, when
to check cost, or when to check in with you — the whole explore-first
workflow lives in that skill.

### 2. Set your credentials

Wake needs an LLM endpoint. Set these in whatever mechanism your
harness uses (`.env`, MCP config, shell profile) so wake's subprocess
inherits them:

- `OPENAI_API_KEY` — LLM API key (required)
- `OPENAI_BASE_URL` — API endpoint URL (required)
- `OPENALEX_MAILTO` — your email, for OpenAlex/Unpaywall's polite pool
  (recommended — faster, more reliable)

The agent's first move in any session should be
`wake --json config validate`, which tells it exactly what's missing.
See [Environment Variables](#environment-variables) below for the
full list, including optional ones.

### 3. Hand your agent a seed paper

Ask something like:

> Analyze the citation impact of doi:10.1145/1048935.1050189 using wake.

or

> Use wake to analyze who cites "Parallel netCDF" and how.

A DOI, arXiv ID, OpenAlex ID, or paper title all work as the seed.

### 4. Stay in the loop

Because the Agent Skill teaches wake's explore-first discipline, your
agent should pause and check in with you at natural decision points —
after resolving the seed, after classifying a sample of ~10 works
before scaling to hundreds, before running expensive full-text reads,
before confirming a theme, before stitching a narrative. Answer its
questions as they come.

When it's done, open `wake-out/<seed>/README.md` in Obsidian, GitHub,
or your editor of choice — the folder is self-describing.

## Documentation

| Doc | Covers |
|---|---|
| [`docs/workflow.md`](docs/workflow.md) | Full command list, quick-start walkthrough, seed ID formats, relationship classes |
| [`docs/abstract-recovery.md`](docs/abstract-recovery.md) | Automatic + manual OpenAlex abstract backfill |
| [`docs/pdf-sources.md`](docs/pdf-sources.md) | The `wake fetch-pdf` source chain |
| [`docs/evidence.md`](docs/evidence.md) | Provisional → proposed → verified lifecycle, the evidence wiki |
| [`docs/themes.md`](docs/themes.md) | Combined-evidence thematic synthesis (`wake theme`) |
| [`docs/narrative.md`](docs/narrative.md) | Narrative drafting from confirmed themes (`wake narrative`) |
| [`docs/timeline.md`](docs/timeline.md) | Curated timeline of key developments over time (`wake timeline`) |
| [`docs/trust-model.md`](docs/trust-model.md) | Where LLM output enters the workflow, and how it's contained before reaching a human as a settled claim |
| [`wake/skills/impact-analysis/SKILL.md`](wake/skills/impact-analysis/SKILL.md) | The agent-facing workflow guide (primary way this tool is meant to be used) |
| [`BACKLOG.md`](BACKLOG.md) | Open roadmap: deferred features, held designs, not-yet-built items |
| [`PLAN.md`](PLAN.md) | Design charter + current forward-looking plan |
| [`docs/build-log.md`](docs/build-log.md) | Append-only engineering build log (every shipped version, what/why/how verified) |
| [`docs/design/backlog-built-history.md`](docs/design/backlog-built-history.md) | Design rationale for already-shipped BACKLOG product themes |

## Configuration

Create `wake.config.yaml` in your working directory (or run `wake config init`):

```yaml
models:
  describe: "Claude Sonnet 4.6"
  classify: "Claude Haiku 4.5"
  pdf_abstract_extract: "Claude Sonnet 4.6"
  evidence: "Claude Sonnet 4.6"

openalex:
  rate_limit_s: 1.0

cost:
  rates_per_1k_usd:
    "Claude Sonnet 4.6": {in: 0.003, out: 0.015}
```

`classify` (abstract/title-only, always-`provisional` labels) defaults to
the cheaper/faster Claude Haiku 4.5; `describe`/`pdf_abstract_extract`/
`evidence` (full-text-grounded, produces the non-provisional `proposed`/
`verified` finding) stay on Claude Sonnet 4.6 — see `wake/config.yaml`'s
comment above `models:` for the live A/B data behind that split.

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

## Development

```bash
pip install -e ".[dev,pdf]"

ruff check wake/ tests/   # lint
mypy                      # typecheck (wake/ package only)
pytest tests/ -m 'not network'
```

CI (`.github/workflows/ci.yml`) runs all three across Python 3.10–3.13 on
every push/PR to `main`.

## License

BSD 3-Clause. Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
