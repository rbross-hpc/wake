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

## Build Order (completed)

1. Scaffold: pyproject.toml, LICENSE, config, vendored _http/errors/similarity/io/state
2. sources/openalex.py + seed.py + wake resolve
3. citing.py + wake citing
4. llm/openai_client.py + describe.py + wake describe
5. classify.py + wake classify (resumable)
6. report.py + wake brief + wake show
7. Bundled skill + wake skill
8. Tests + README + PLAN.md

## Verification (v0.1)

```bash
# Offline
pytest tests/ -m 'not network'

# Live end-to-end
wake brief 10.1145/1048935.1050189
# → inspect wake-out/W2156077349/impact.md
```

---

# v0.2 — Agent-First, Explore-First

## Reframe

`wake` is not a standalone CLI a human types commands into — it's an
analysis instrument an agent (e.g. Claude via opencode) wields on the
human's behalf. The human explores through the agent (resolve → confirm →
sample → classify a handful → check cost → decide) before committing to a
full LLM run. This changes the design center of gravity from "one pipeline
command" to "a set of dependable, JSON-emitting primitives + a workflow
playbook (SKILL.md) that tells the agent how to sequence them and where to
pause for the human."

## Decisions Locked

- **Thin primitives + rich SKILL.md** — the CLI does not decide strategy;
  the agent does, guided by the bundled skill's workflow.
- **Explore-first is the primary mode** — sample before you spend.
- **`wake brief` removed** — no one-shot autopilot. Its two jobs split:
  orchestration moves to the agent; artifact assembly becomes `wake render`.
- **Cost telemetry: estimate-only** — char-count-based token heuristic
  logged per-call to `.cost.jsonl`; unpriced models report `0.0` +
  `unpriced: true` rather than guessing. No dependency on the upstream
  endpoint returning usage data.
- **Prompt-as-editable-file iteration: parked** — not built in this pass;
  `prompt_version` in config remains the cache-invalidation mechanism.

## New/Changed Command Surface

| Command | Status | Notes |
|---|---|---|
| `resolve` | unchanged | now supports global `--json`/`--work-dir` |
| `status` | **new** | cached-artifact counts, pending count, estimated remaining classify cost — the explore-first dashboard |
| `citing` | changed | added `--sort {cited-by,recent,oldest,random}` |
| `sample` | **new** | representative slice for human review; free, no LLM calls |
| `describe` | changed | now records cost; respects verbose/quiet |
| `classify` | changed | added `--ids`, `--limit`, `--sort`, `--dry-run`; scoped runs now correctly preserve prior classifications outside the current selection (see Bug Found below) |
| `render` | **new** (replaces half of `brief`) | assembles impact.md/json from whatever is classified; notes partial coverage; applies `.overrides.jsonl` |
| `override` | **new** | human-in-the-loop relationship correction, wins over LLM in render |
| `cost` | **new** | reads `.cost.jsonl`, sums by stage |
| `brief` | **removed** | replaced by agent composing `citing` → `describe` → `classify` → `render` |
| `show` | unchanged | brief/metrics/top |

Global flags added: `--json`, `--work-dir DIR` (falls back to
`WAKE_WORK_DIR` env, then cwd), `--verbose` (keep progress banners under
`--json`).

## Architecture Additions

```
wake/
  cli/
    emit.py     # NEW — JSON envelope (emit/emit_error) + is_quiet/progress
  cost.py       # NEW — estimate_tokens, estimate_cost_usd, record_call,
                #        read_log, summarize, estimate_remaining_classify_cost
  citing.py     # + sort_works, sample_works; filter_works gained `sort=`
  classify.py   # + select_for_classification, ids/limit/sort/dry_run on
                #   classify_all; classify_one takes seed_id/base/record_cost
                #   for cost-sink wiring
  report.py     # + overrides_path/load_overrides/add_override/apply_overrides;
                #   build_metrics now takes the full citing set (not just
                #   classified) and reports `classified_count`/`coverage`;
                #   build_and_save renamed render_and_save
  llm/openai_client.py  # chat_json/chat_text gained optional cost_sink callback
  seed.py       # work_dir() now resolves WAKE_WORK_DIR env as a fallback root
  skills/impact-analysis/SKILL.md  # REWRITTEN as an 8-step workflow playbook
                # with explicit human-checkpoint instructions, not a command list
```

## Bug Found & Fixed During Implementation

`classify_all`'s selection logic (`--ids`/`--limit`) originally built its
merge dict (`by_id`) only from the *current* input `citing_works` list
without first loading prior sidecar classifications for works **outside**
the current selection. A scoped run would silently regress previously
classified works when the caller saved the result via `save_classified`
(only the just-classified subset would show `relationship`, dropping
earlier work). Fixed by seeding `by_id` with every citing work's existing
sidecar classification (if current) before applying the new selection's
results. Caught by an end-to-end offline smoke test exercising exactly this
sequence (`classify --limit 5` then `classify --ids <other>`), and pinned
with a regression test:
`tests/test_classify.py::test_classify_all_scoped_run_preserves_prior_classifications`.

## Verification (v0.2)

- Offline: `pytest tests/ -m 'not network'` — 80 tests (43 original + 37 new:
  `test_cost.py`, `test_emit.py`, `test_sample.py`, `test_overrides.py`,
  regression + partial-coverage additions to `test_classify.py`/`test_report.py`).
- Library-level smoke test (`/tmp/opencode/wake-smoke/smoke.py`, not
  committed): resolve → citing → sample → describe → classify (dry-run,
  scoped, resumed, `--ids`) → render (partial coverage) → override → render
  again, against mocked OpenAlex + LLM calls.
- CLI-level smoke test (`/tmp/opencode/wake-smoke/cli_smoke.py`, not
  committed): every command invoked via `wake.cli.main.main()` with
  `--json`, asserting envelope shape (`wake_version`/`command`/`ok`/`data`)
  end-to-end, plus one human-readable (non-`--json`) sanity check.
- Live: not yet re-run against the real OpenAlex/Argo endpoints for v0.2
  (network tests in `tests/` marked `network` remain from v0.1 and still
  apply to `sources/openalex.py`, which is unchanged in this pass).

## Build Order (v0.2, completed)

1. `cli/emit.py` — JSON envelope + progress routing
2. `cost.py` — token estimate + `.cost.jsonl`
3. `seed.py` — `WAKE_WORK_DIR`/`--work-dir` support
4. `citing.py` — `sort_works`/`sample_works`, `--sort` on `filter_works`
5. `classify.py` — `ids`/`limit`/`sort`/`dry_run` + cost integration (+ bug fix above)
6. `report.py` — `.overrides.jsonl`, `render_and_save`, partial-coverage note
7. `cli/main.py` — `status`/`sample`/`render`/`override`/`cost` commands, `brief` removed, global flags
8. `SKILL.md` rewritten as workflow playbook
9. Tests: `test_cost.py`, `test_emit.py`, `test_sample.py`, `test_overrides.py` + updates to `test_classify.py`/`test_report.py`
10. README/PLAN updated; full offline suite + two smoke scripts green

---

## v0.2.1 — Live-Testing Fixes

Running the explore-first workflow live against the real Argo endpoint
surfaced two integration bugs, fixed together:

1. **Streaming required**: the Argo endpoint rejects non-streaming chat
   completions with a 500 error. Fixed `llm/openai_client.py` to always
   stream and accumulate — this had been silently failing every
   `describe`/`classify` call, masked by the error-swallowing fallback to
   a fake low-confidence `background-mention` classification.
2. **Wrong default model**: `"Claude Sonnet 4.7"` doesn't exist on this
   Argo endpoint. Fixed default to `"Claude Sonnet 4.6"` in both
   `openai_client._model()` and `config.yaml`.
3. **Prompt drift**: the model invented an off-schema relationship label
   (`related_infrastructure`) for genuinely complementary tooling (e.g.
   PLFS, NCO relative to PnetCDF). Rather than force these into
   `background-mention`, added `related-infrastructure` as a real seventh
   relationship class and tightened the prompt against inventing further
   labels.
4. Failed classify calls no longer cache a fake classification — they're
   surfaced (`error`/`error_at` fields, `error_count` in CLI output) but
   leave no `relationship` key, so they're excluded from coverage and
   retried on the next run.

## v0.2.2 — Lazy Abstract Backfill (OSTI + Semantic Scholar)

Live testing found 87/408 (21%) of Parallel netCDF's citing works lack an
OpenAlex abstract. Checked Unpaywall (PDF links only, no abstracts —
would require full-text extraction), Crossref (0% abstract recovery on a
5-work sample), Semantic Scholar (~33% recovery), and OSTI (~27% recovery,
DOE-funded work only, via its `description` field). OSTI and Semantic
Scholar barely overlap, so combined they recover ~50% of missing
abstracts on a 30-work sample — no PDF dependency, both free/unauthenticated.

- `sources/osti.py`, `sources/semanticscholar.py` — abstract-only lookup
  by DOI (adapted from ref-checker's fuller bibliographic modules).
- `backfill.py` — tries sources in config order (`osti`, then
  `semanticscholar`), lazily, only for works actually selected for
  classification (wired into `classify.py`'s `classify_all` loop right
  before each LLM call). A hit sets `abstract` + `abstract_source`; a miss
  falls through unchanged to existing title/venue-only classification.
- `report.py`: `backfilled_abstract_count` metric, noted in the brief's
  Reach section.
- `config.yaml`: `abstract_backfill.{enabled,sources,rate_limit_s}`.

Verified live: classifying 5 real no-abstract works recovered 2/5 via
Semantic Scholar, raising classification confidence from ~0.3-0.4 to
0.6-0.75 and producing visibly more specific justifications. One
backfilled work (netCDF Operators vs. PnetCDF) correctly triggered the new
`related-infrastructure` class.

## v0.2.3 — Human-Escalation Path for Remaining High-Value Gaps (`gaps` / `fill-abstract`)

Automatic backfill still leaves roughly half of the no-abstract works
unresolved. Most are low-value (rarely-cited background mentions) and are
fine to classify from title+venue alone — but a minority are themselves
highly-cited, consequential citing works where a better abstract would
meaningfully improve classification confidence and evidence quality.
Rather than silently accept the lower-confidence classification for these,
surface them and offer two explicit, human-driven escalation paths.

Design constraint (confirmed with the user): if the abstract isn't in the
first ~3 pages of a PDF, it isn't there — no need to extract or pass a
full paper to an LLM. This keeps both extraction and the cleanup LLM call
cheap (a few hundred words, not a full paper).

- `wake gaps <seed>` — ranks no-abstract citing works by their own
  `cited_by_count` (config `gaps.min_cited_by_count` threshold, default
  20), re-checking automatic backfill first (so it never surfaces a work
  that OSTI/Semantic Scholar would resolve anyway) before reporting true
  gaps.
- `wake fill-abstract <seed> <citing-id> --from-pdf <path>` — extracts the
  first few pages of a **locally-downloaded** PDF (`sources/pdf_abstract.py`,
  pypdf with pdfplumber fallback — both permissively licensed BSD-3/MIT;
  deliberately not PyMuPDF, which is AGPL and would create a licensing
  conflict for a BSD-3 project) and asks a small, targeted LLM call
  (`abstract_extract.py`) to locate and clean the abstract from that
  lead-page text — never summarizes the full paper. The model is
  instructed to report "not found" rather than fabricate an abstract if
  one genuinely isn't in the extracted window.
- `wake fill-abstract <seed> <citing-id> --text "..."` — the human pastes
  the abstract directly; no LLM call at all.
- Both paths write to a new `.manual_abstracts.jsonl` sidecar (same
  append-only, last-write-wins pattern as `.overrides.jsonl`), applied in
  `classify.py` before backfill/classification on every subsequent run —
  a human-supplied abstract always takes precedence and is never
  re-fetched from OSTI/Semantic Scholar.
- New optional dependency group: `wake[pdf]` (`pypdf`, `pdfplumber`) — not
  a hard dependency, since PDF extraction is an opt-in escalation path,
  not part of the core pipeline.

### Test Fixture

Committed `tests/fixtures/osti_1343551_netcdf_bigdata.pdf` — a real,
public-domain (17 U.S.C. 105, U.S. government work) conference paper
hosted by OSTI: Devarakonda, Wei & Thornton, "Accessing and Distributing
Large Volumes of NetCDF Data," 2016 IEEE Big Data (DOI
10.1109/BigData.2016.7841077, OSTI ID 1343551). Chosen specifically
because OSTI's own metadata record has *no* `description` field for this
DOI (automatic backfill would miss it), but the PDF itself has a clean,
extractable "Abstract-" section on page 1 — exactly the scenario
`fill-abstract --from-pdf` exists to solve. The paper's real abstract is
used as a fixed ground-truth string in test assertions.

Offline tests exercise real PDF extraction (pypdf) against this fixture
with the LLM call mocked; `@pytest.mark.network` tests run the same flow
against the real Argo endpoint and confirm the model recovers the
abstract nearly verbatim from noisy lead-page text without fabricating
content.

## Verification (v0.2.1 – v0.2.3)

- Offline: 117 tests passing (`pytest tests/ -m 'not network'`) — 94 prior
  + 14 (`test_gaps.py`) + 9 (`test_pdf_abstract.py`).
- Live (`pytest tests/ -m network` and manual CLI runs against the real
  Argo + OpenAlex + OSTI + Semantic Scholar endpoints):
  - Streaming fix confirmed: single/batch/sample classify calls succeed
    with parseable JSON, zero errors.
  - Backfill confirmed: 2/5 real no-abstract works recovered via Semantic
    Scholar, visible confidence/specificity improvement.
  - `wake gaps` confirmed: correctly surfaces exactly the 2 real works
    (WIND Toolkit, grid-generation paper) that live-testing had already
    shown neither OSTI nor Semantic Scholar could resolve.
  - `wake fill-abstract --text` confirmed: manually-supplied abstract
    flows through to classification (confidence 0.35 → 0.85, justification
    became specific and accurate).
  - `wake fill-abstract --from-pdf` confirmed end-to-end against the real
    committed fixture: extraction → LLM cleanup → `.manual_abstracts.jsonl`
    → available for the next classify run.
  - Full rendered `impact.md` inspected and judged genuinely useful even
    at low (1-2%) coverage.

---

# Phase 2 — Evidence, Narrative & Wiki (see BACKLOG.md)

After a full live run (all 408 Parallel netCDF citing works classified,
zero errors, real `impact.md` reviewed end-to-end — see BACKLOG.md intro),
planning turned to a substantial follow-on: per-reference evidence
dossiers, DOE-relevance signal extraction, an OKF-compliant knowledge wiki,
author-overlap tagging, and (deferred) narrative-drafting/timeline/
non-publication-evidence tools. Full theme breakdown, design decisions,
and sequencing live in `BACKLOG.md`.

## v0.3.0 — PDF Acquisition (`wake fetch-pdf`) — BACKLOG Theme A

Standalone, reusable primitive for automatically acquiring a PDF for one
citing work — not just an internal helper for the (not-yet-built) evidence
dossier tool (BACKLOG Theme A2). Also directly usable to streamline
`wake fill-abstract --from-pdf` (skip the manual-download step whenever
the chain succeeds).

Source chain, tried in order (config `pdf_fetch.sources`), all API-based —
no scraping publisher landing pages, no sci-hub-style sources:

1. **OSTI** (`sources/osti.py`, extended) — direct `fulltext` link
   relation on the existing DOI-lookup record (DOE-funded work, no auth
   wall, zero cost/rate-limit).
2. **Semantic Scholar** (`sources/semanticscholar.py`, extended) —
   `openAccessPdf.url` field, distinct from and complementary to
   Unpaywall's OA discovery; frequently a repository/arXiv copy.
3. **Unpaywall** (`sources/unpaywall.py`, new) — `best_oa_location`'s PDF
   URL. No abstract capability (that problem was already solved via
   OSTI/Semantic Scholar in Phase 1's `backfill.py`) — this module exists
   solely for PDF location. Frequently points at publisher "author
   manuscript" pages that reject bot downloads (confirmed live:
   ScienceDirect 403 on the WIND Toolkit paper) — attempted anyway since
   it sometimes succeeds, and the download validator (below) rejects the
   failure cleanly rather than saving garbage.
4. **arXiv** (`sources/arxiv_fetch.py`, new, adapted from ref-checker's
   `sources/arxiv.py`) — title-search match via the arXiv Atom API
   (`title_ratio` similarity, 0.90 threshold); arXiv PDFs are always
   freely downloadable with no bot-blocking.
5. **CORE.ac.uk** (`sources/core.py`, new) — optional, gated behind
   `CORE_API_KEY` (silently returns None/skipped if unset, same pattern as
   `SEMANTICSCHOLAR_API_KEY`). Not live-tested in this session (no API key
   available) — request shape follows CORE API v3's documented
   search-by-DOI convention; verify against a real key before relying on
   it in production.

Orchestrator (`pdf_fetch.py`): tries sources in order, validates each
candidate download (`_download`: rejects non-200 responses, content not
starting with `%PDF-` magic bytes, and files below
`pdf_fetch.min_valid_pdf_bytes` — catches paywall/error HTML pages saved
with a `.pdf` extension) before accepting it, falls through to the next
source on any failure (bad URL, download validation failure, or an
exception from the source lookup itself). Caches to
`wake-out/<seed>/pdfs/<citing-id>.pdf`; a cache hit short-circuits before
any network call unless `--force`.

On total failure (every source exhausted or inapplicable), returns
human-actionable links rather than giving up silently — per explicit user
request, **always attempt automatically first**, and always include a
Google Scholar search URL alongside Unpaywall's lookup page, the
publisher's DOI link, and a CORE.ac.uk search URL.

### Agent Skill restructuring

`SKILL.md` had grown to 237 lines across this and prior sessions, mixing
workflow guidance with reference material (full command list, output
layout, environment variables, relationship-class table). Split following
ref-checker's existing convention (`skills/reference-checking/references/
schema.md`): `SKILL.md` now covers only the numbered workflow + agent
principles (182 lines); `skills/impact-analysis/references/reference.md`
(new) holds the command list, PDF-acquisition chain summary, output
layout, environment variables, and relationship-class table. `SKILL.md`
points to it once, at the top. `wake skill export` already used
`shutil.copytree` on the whole skill directory, so the new `references/`
subdirectory is included automatically — verified live.

### Tests

+39 offline (163 total, up from 124): `test_pdf_sources.py` (21 —
per-source unit tests: OSTI fulltext-link parsing, Semantic Scholar
openAccessPdf, Unpaywall mailto-gating, arXiv title-similarity matching/
threshold, CORE key-gating + an empty-`sourceFulltextUrls`-list regression
guard) and `test_pdf_fetch.py` (18 — orchestrator: cache hit/bypass,
first-hit-wins ordering, fall-through on non-PDF content and on a source
raising an exception, all-sources-exhausted fallback-links shape,
arXiv/CORE properly skipped when inapplicable, `_download`'s
content-type/size/status validation).

### Live verification

- `wake fetch-pdf` on W2107546711 (FLASH architecture paper, no direct
  fulltext OpenAlex link): resolved via Semantic Scholar's
  `openAccessPdf` -> a real, valid 33-page arXiv-hosted PDF (366KB,
  confirmed via `file`).
- Direct `fetch_pdf()` call against a known OSTI DOI (10.2172/10129297,
  the 1994 netCDF calculator technical report used in Phase 1's PDF-abstract
  fixture research): resolved via OSTI's `fulltext` link, confirming OSTI
  is correctly tried and hit first in the chain when available.
- `wake fetch-pdf` on W326249748 (WIND Toolkit — already known from Phase
  1 live testing to have no recoverable abstract from any automatic
  source): Semantic Scholar and Unpaywall both returned the same
  ScienceDirect "author manuscript" URL; the download validator correctly
  rejected it (non-PDF content), the chain fell through all 4 applicable
  sources (CORE skipped, no key configured), and returned the full
  fallback-links set including a working Google Scholar search URL.
- Cache-hit path confirmed: re-running `fetch-pdf` on the already-acquired
  FLASH PDF returned instantly with `"source": "cache"`, no network calls.
- `wake skill export` confirmed to include the new `references/` file.

## v0.3.1 — Setup Check (env-var registry + config JSON output)

User request: develop questions to ask the human early in a session to
catch missing env vars / set preferences, rather than discovering gaps
mid-analysis. Landed as an extension of the existing `wake config`
machinery (no new interactive wizard command) plus a documented "Step 0"
in `SKILL.md` — consistent with wake's "thin CLI, agent orchestrates"
philosophy.

- `config.py`: env-var registry extended from two tiers to three
  (`required`, `recommended`, `optional`). Confirmed via audit that
  `SEMANTICSCHOLAR_API_KEY`, `CORE_API_KEY`, and `WAKE_WORK_DIR` were read
  by the code (`sources/semanticscholar.py`, `sources/core.py`,
  `seed.py`) but never surfaced by `config.show()`/`validate()` —
  genuinely undocumented gaps, now in the `optional` tier.
- New `config.env_status()` — structured set/unset + description per var,
  grouped by tier; never leaks sensitive (`*KEY*`) values, only whether
  they're set.
- New `config.validate_report()` — `{"ok", "errors", "env": env_status()}`,
  for `--json` consumers. `validate()` itself unchanged (required-only,
  list of error strings) — recommended/optional gaps are never blocking.
- `cli/main.py::run_config` rewritten to use `emit`/`emit_error` like
  every other command — `wake config show/validate/init` now all honor
  the global `--json` flag (previously all three ignored it unconditionally).
- **Bug fix, found during the env-var audit**: three different hardcoded
  model-name defaults were live in the codebase simultaneously —
  `config.yaml` said `"Claude Sonnet 4.6"` (correct, fixed in v0.2.1's
  streaming fix), but `config.init_local()`'s starter template and the
  in-code fallback defaults in `classify.py`/`describe.py` still said the
  stale `"Claude Sonnet 4.7"` (only `llm/openai_client.py`'s fallback had
  been fixed). A user running `wake config init` today would get a
  starter file with a model name that doesn't exist on the Argo endpoint.
  Fixed all three to `"Claude Sonnet 4.6"`. Also fixed `classify.py`'s
  `_prompt_version()` fallback (`"classify-1"` — stale from before the
  classify-2 prompt-tightening fix in v0.2.1) to `"classify-2"`.
- `SKILL.md`: new "Step 0: Setup check" before "1. Resolve and confirm" —
  tells the agent to run `wake --json config validate` once per session
  and how to react per tier: **required** missing -> stop, don't proceed;
  **recommended** (`OPENALEX_MAILTO`) missing -> ask once, briefly, before
  racking up unauthenticated API calls; **optional** vars -> never ask
  upfront, only mention `SEMANTICSCHOLAR_API_KEY` if the analysis is
  large-scale (step 4), `CORE_API_KEY` right before `fetch-pdf`/`gaps`
  (step 7) as an FYI, and `WAKE_WORK_DIR`/`--work-dir` once before the
  first cache write (step 2) if the human hasn't stated a preference.
- `references/reference.md` and `README.md`: env-var tables restructured
  by tier; added the `wake config validate --json` response shape as a
  documented example.

### Tests

+15 offline (178 total): `test_config.py` — three-tier registry shape,
sensitive-value masking (API keys never leak into `env_status()`/`show()`
output even when set), `validate()`'s required-only blocking behavior
(recommended/optional gaps never fail validation), `validate_report()`
shape for both pass/fail, and two regression guards: `show()`/
`init_local()` must never emit the stale `"Claude Sonnet 4.7"` string.

### Live verification

- `wake --json config validate` confirmed to return the full 3-tier
  structured breakdown with real env state.
- `wake config show`/`config init` confirmed to display/write
  `"Claude Sonnet 4.6"` consistently (previously would've shown 4.6 in
  `show()`'s packaged-config dump but written 4.7 into a fresh
  `wake.config.yaml` via `init`).
- End-to-end `describe` call against the real Argo endpoint succeeded
  with the corrected model defaults.
