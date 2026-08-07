# PLAN — wake

## Goal

Given a seed paper (DOI, arXiv ID, OpenAlex ID, or title), produce an evidence-backed impact brief:
describe what the paper contributes, fetch every work that cites it, use an LLM to classify how
each citing work uses the paper, surface the strongest evidence of real impact, and render a
Markdown report.

## Motivation

OpenAlex `filter=cites:<work_id>` returns all citing works with metadata (year, venue, type, own
`cited_by_count`, and ~68% have abstracts via inverted index). Neither existing sibling repo
(ref-checker, pub-analysis) traverses this. Verified working against "Parallel netCDF" (2003),
W2156077349, 408 citing works.

## What We Reuse (vendored, self-contained)

From **ref-checker**:
- `sources/openalex.py` → adapted & extended with citing-works traversal (the new core)
- `sources/_http.py`, `errors.py`, `similarity.py` → copied as-is
- CLI argparse structure & polite-pool rate limiter pattern → template for wake's CLI
- Skill scaffolding → bundled agent skill pattern

From **pub-analysis**:
- `config.py` + `config.yaml` → adapted
- `llm/openai_client.py` (chat_json/chat_text with tenacity retries) → copied
- `state.py` + `io.py` (atomic writes, sha/version cache keying) → adapted for seed-id keying
- Prompt-runner pattern → template for classification & narrative prompts

## New Capability

`sources/openalex.py::iter_citing_works` — cursor-paginated traversal of all citing works,
rate-limited, with per-page=200 for efficiency.

## Architecture

```
wake/
  __init__.py        # __version__
  __main__.py
  config.py          # packaged + local override (wake.config.yaml)
  config.yaml        # packaged defaults
  errors.py          # RateLimited, SeedNotFound, OpenAlexError
  similarity.py      # title_ratio (vendored)
  io.py              # atomic writes, sha256, now_iso
  state.py           # .state.json per-seed cache management
  sources/
    _http.py         # raise_for_rate_limit, parse_retry_after
    openalex.py      # resolve seed + cited_by cursor traversal (NEW)
  seed.py            # resolve + cache seed → seed.json
  citing.py          # fetch + cache all citing works → citing.json
  describe.py        # LLM contribution paragraph → seed.json (description field)
  classify.py        # LLM per-citing-work relationship → .classify/ sidecars + classified.json
  report.py          # assemble impact.md + impact.json
  llm/
    openai_client.py # chat_json / chat_text with tenacity
  cli/
    main.py          # argparse dispatcher
    skill.py         # skill subcommand
  skills/
    impact-analysis/
      SKILL.md       # bundled agent skill
tests/
  conftest.py        # shared fixtures (offline work dicts)
  test_similarity.py
  test_io.py
  test_state.py
  test_seed.py
  test_classify.py
  test_report.py
  test_openalex.py
pyproject.toml
README.md
PLAN.md
LICENSE
```

## Design Decisions

- **Rate limiting**: time.sleep between OpenAlex pages (configurable via `openalex.rate_limit_s`).
- **Resumability**: classification writes an atomic JSON sidecar per work in `.classify/` —
  safe Ctrl-C, re-run skips done works.
- **Graceful degradation**: works lacking abstracts are classified from title+venue only;
  confidence is set ≤ 0.5.
- **Caching**: `.state.json` keyed by seed_id + prompt_version + tool_version + model.
- **No PDF/MinerU**: seed metadata & abstract come from OpenAlex (lightweight).
- **Output dir**: `wake-out/<work-id>/` (avoids name collision with the `wake` package).

## Ranking (Top Evidence)

Score = relationship_strength × log(1 + downstream_cited_by_count)

Relationship strengths (highest to lowest):
  extends (6) > builds-on (5) > uses-as-tool (4) > benchmarks (3) >
  applies-to-domain (2) > background-mention (1)

---

## Build history moved

Per-version build history (v0.2 through the present) — what was built,
why, bugs found and fixed, and how each phase was verified — now lives
in [`docs/build-log.md`](docs/build-log.md), an append-only engineering
journal. This file (`PLAN.md`) stays a short, current design charter
plus the active forward-looking plan (below); it does not accumulate
retrospective entries.

Existing code/config comments citing `PLAN.md "Phase N"` or `PLAN.md
v0.4.x` refer to entries now in `docs/build-log.md` — heading text and
version numbers are unchanged, so those references still resolve there.

For the open product/engineering roadmap (deferred features, held
designs, not-yet-built items), see [`BACKLOG.md`](BACKLOG.md). For the
design rationale behind already-shipped BACKLOG-tracked product themes,
see
[`docs/design/backlog-built-history.md`](docs/design/backlog-built-history.md).

---

## Current Plan — What's Next

The Structural Hardening effort (`docs/build-log.md`, "Phase 3") closed
its six original phases plus a four-phase migration-story follow-on
(v0.4.0–v0.4.12): CI/lint/typecheck, explicit Pydantic domain models,
`WakeContext`, a centralized build layer (`wake rebuild`), the
`cli/main.py` split, LLM retry-policy hardening, and schema-versioning
(with migration) across all five persisted artifact families (dossiers,
themes, narrative outline+sections, classification, overrides).

**Next phase:** formalize the remaining `_normalize_*`/legacy-shape
functions using the migration-chain pattern established across those
five families — some (the bare-list `classified.json` shape,
absolute/relative dossier paths) are already formalized as explicit
migration steps; the rest are candidates for the same treatment.

**Deferred, real, not forgotten** (see `BACKLOG.md`'s "Open / Not Yet
Built" section for the full list and current sequencing):
- Full `WakeContext` threading through the ~90 existing `base:`-taking
  domain functions.
- A persisted dirty/revision manifest for `wake rebuild`, tracking
  staleness *between* calls.
- Product features: Theme B (DOE-relevance signals), Theme G (timeline
  generation), Theme H (non-publication evidence search), Theme K Pass 2
  (wiring seed-PDF consumers).

Explicitly **not** planned: replacing the filesystem-artifact model with
a database. Both the original external assessment and independent
review agree file-first is a real strength of wake's design, not a
symptom needing a fix.
