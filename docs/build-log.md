# wake — Build Log

> **This is an append-only engineering journal, not a forward plan.**
> Every entry below is a historical, past-tense record of a shipped
> version: what was built, why, what bugs were found and fixed, what was
> deliberately scoped out, and how it was verified. Entries are never
> rewritten once landed — only appended to.
>
> - For the current forward-looking plan, see [`PLAN.md`](../PLAN.md).
> - For the open roadmap and deferred/not-yet-built items, see
>   [`BACKLOG.md`](../BACKLOG.md).
> - For the design rationale behind already-shipped BACKLOG themes
>   (product features, not the structural-hardening work recorded here),
>   see
>   [`docs/design/backlog-built-history.md`](design/backlog-built-history.md).
>
> Existing code/config comments citing `PLAN.md "Phase N"` or `PLAN.md
> v0.4.x` refer to entries in this file — the heading text and version
> numbers below are unchanged from when they lived in `PLAN.md`, so those
> references still resolve here.

---

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

## v0.3.2 — Full-Text Verification (`wake evidence`) — BACKLOG Theme A2

Every classification `classify.py` produces is an abstract-only guess —
it never reads the citing paper itself. This was previously presented in
the brief with an ordinary confidence score, indistinguishable from a
real finding. `wake evidence` closes that gap: it reads a citing work's
*entire* PDF and proposes an independently-judged relationship backed by
quoted, page-cited passages, without ever silently overwriting the
record — only a human-approved `wake override` call can do that.

### Lifecycle: provisional → proposed → verified

Reframed mid-design at the user's explicit direction: the abstract-only
classification is not a baseline that full-text reading either confirms
or contradicts — it's inherently weak evidence from the start, and the
full-text reading is the substantive assessment, pending human sign-off.

- `classify.py`: every result now carries `"verification_status":
  "provisional"`, unconditionally — this is true for *all* classified
  works, not just ones that later get a dossier. No back-compat shim (per
  user instruction): old cached `classified.json`/test fixtures were
  hand-corrected to include the field rather than defaulting a missing one.
- `report.py::add_override()`: gains `verification_status: "verified"` +
  `verification_source` (`"human-judgment"` default, or
  `"evidence-dossier"` when the override follows a `wake evidence`
  finding the human accepted). This is the *only* path to `"verified"`.
- `render_markdown()`: every "Strongest Evidence" entry is tagged inline
  — `[PROVISIONAL — abstract-only, not yet checked against full text]`,
  `[VERIFIED via full-text reading]`, or `[VERIFIED via human judgment]`.
  "Nature of Impact" gains a one-line provisional/verified count summary.

### `wake evidence <seed> <citing-id>` pipeline

1. `fetch-pdf` (reused as-is, including its negative-result... actually
   its existing cache-then-chain behavior) acquires a local PDF.
2. `sources/pdf_fulltext.py` (new) extracts the *entire* document,
   page-tagged — not just the first few pages like `pdf_abstract.py`.
   Deliberately page-level only: multi-column academic PDF layouts
   interleave text unreliably at extraction time (confirmed live on the
   existing OSTI test fixture — both pypdf and pdfplumber merge column
   text into a jumbled per-page stream), so mechanical paragraph-boundary
   detection isn't reliable. Per user's explicit requirement ("I want the
   human to see the literal text supporting the claim, in context"), the
   LLM prompt instead asks for the full containing paragraph verbatim
   around any supporting passage — the model handles minor reading-order
   jumbling far better than a mechanical splitter would, while wake still
   attaches a real page number.
3. `evidence.py::verify_full_text()` — one LLM call given the seed, the
   provisional guess (explicitly framed as unverified), and the full
   text; asked to form an independent judgment, quoting complete
   paragraphs with page numbers for every claim, and to say honestly if
   the seed isn't discussed in the text at all rather than fabricating
   a passage.
4. Renders an OKF concept document (`wake-out/<seed>/evidence/<citing-id>.md`
   + a `.json` sidecar for programmatic reuse) with the provisional guess,
   the proposed full-text reading, and the quotes — explicitly framed as
   "pending your review," not a correction.
5. Cached: a second `build_dossier()` call for the same citing work is a
   no-op (no LLM call) unless `--force`.

**Never auto-applies.** `wake evidence` only ever proposes; a human must
review it and an agent must run `wake override` (now accepting
`--verification-source evidence-dossier`) to promote a finding to
`verified`. Per explicit user direction, the human is never asked to run
that command themselves — SKILL.md step 9 spells out two agent-driven
paths (human reviews independently and reports back; or the agent walks
them through it) that both end with the agent invoking `override`. In the
second path, the agent must paste the literal quoted paragraph(s) from
the `quotes` field into the conversation verbatim, in context — not a
paraphrase — so the human judges the paper's actual words.

### Robustness fix (shared, not evidence-specific)

Live testing surfaced a real bug in the shared LLM client: `chat_json`
occasionally received a response with reasoning prose *before* the JSON
object (e.g. "Looking at the text, I find no mention of X... {...}"),
despite explicit "respond with ONLY JSON" instructions — observed with
`evidence`'s long full-text prompt specifically, but the failure mode is
generic. Fixed centrally in `llm/openai_client.py`: a new
`_extract_json_object()` (string-aware, brace-depth-counting scan for the
first balanced `{...}` span) is tried as a fallback whenever the initial
`json.loads()` fails, rather than failing outright. Also tightened the
`evidence` prompt itself to explicitly forbid preamble/commentary.

### DOE-relevance signals (BACKLOG Theme B) — explicitly deferred

Raised and resolved as a separate design discussion mid-session: Theme A2
(this work) is general-purpose and contains zero domain-specific logic.
Theme B (author affiliations, DOE compute-resource acknowledgments,
funding language, OSTI cross-check) was explicitly scoped by the user as
something *they* want but a general wake user might not — it will be a
separate, off-by-default module (e.g. `signals_doe.py`, gated by a config
flag + a `wake evidence --with-doe-signals` override), not built in this
pass.

### Tests

+37 offline (216 total):
- `test_pdf_fulltext.py` (6) — real extraction against the committed OSTI
  fixture: page count, content, `[page N]` markers and ordering.
- `test_evidence.py` (12) — `verify_full_text()`'s label validation/empty-
  quote filtering, `build_dossier()`'s no-PDF failure path, end-to-end
  dossier generation against the real fixture PDF (LLM mocked), dossier
  caching + `--force` bypass, and a verbatim-full-paragraph-quote
  assertion. Plus 1 live (`@pytest.mark.network`) test.
- `test_openai_client.py` (9, new file — no prior direct test coverage of
  this shared module) — `_extract_json_object()` unit tests (balanced
  braces, braces inside quoted strings, no-object passthrough, trailing
  text after the object) and a `chat_json` regression test pinning the
  prefixed-prose recovery behavior found live.
- `test_classify.py` (+2), `test_report.py` (+9), `test_overrides.py`
  (+1 assertion) — provisional-by-default on every `classify_one`/
  `classify_all` result; `verified_count` in `build_metrics`; per-entry
  `verification_status`/`verification_source` in `top_evidence`;
  `render_markdown`'s three status tags and summary line;
  `add_override()`'s new fields and both `verification_source` values.

### Live verification

- Full lifecycle exercised end-to-end against real citing works of
  Parallel netCDF (W2156077349): classified the FLASH architecture paper
  (W2107546711) — provisional `uses-as-tool` (confidence 0.6, abstract-only)
  — then ran `wake evidence`, which fetched the same real 33-page arXiv
  PDF from the earlier `fetch-pdf` session, read the entire document, and
  proposed `uses-as-tool` (confidence 0.85, agrees with provisional) with
  a real page-21 quote: *"FLASH is one of the relatively few applications
  codes that have support for multiple IO libraries, such as HDF5 and
  parallel netCDF, where all processors can write data to a single shared
  file."* Ran `wake override ... --verification-source evidence-dossier`
  and confirmed `wake render` shows `[VERIFIED via full-text reading]`
  with confidence bumped to 1.0, and the Nature-of-Impact summary line
  correctly reads "9 classification(s) are provisional ... 1 have been
  verified."
- Separately confirmed honest non-fabrication behavior: ran full-text
  verification against the *other* committed test fixture (the
  Devarakonda/Daymet OSTI paper, chosen for the abstract-extraction tests
  and never a real citing work of Parallel netCDF) with a deliberately
  implausible provisional guess (`extends`) — the model correctly
  determined the seed paper is not discussed anywhere in the text or
  reference list, returned `background-mention` with `quotes: []`, and
  did not fabricate a supporting passage. This is what surfaced the
  prefixed-prose JSON bug (fixed above), so the fix is validated by the
  same live run that motivated it.

## v0.3.3 — Cached PDF Text Extraction

User question: is extracted PDF text saved consistently, in case a
`wake evidence` finding needs debugging or a re-run needs auditing?
Previously, no — `evidence.py::build_dossier()` re-extracted text fresh
on every call and discarded it once the LLM verification pass consumed
it. Only the dossier's *quoted excerpts* (the LLM's selective output) were
persisted, not the actual text the model was given as input — no way to
tell "bogus extraction" from "bad reasoning" without re-running anything.

- `sources/pdf_fulltext.py`: new `extract_pages_cached(pdf_path, force=)`
  + `extracted_text_path(pdf_path)`. Cache file is always a sibling of the
  PDF (`wake-out/<seed>/pdfs/<citing-id>.pdf` ->
  `wake-out/<seed>/pdfs/<citing-id>.json`) — deliberately co-located with
  the PDF rather than under `evidence/`, since extraction is a property
  of the PDF file, not of any particular dossier; a future consumer (e.g.
  a DOE-signals reader, or re-verification under a different prompt)
  can reuse it without depending on wake evidence's output layout.
  Keyed by the PDF file's sha256 (via `io.sha256_bytes`, previously
  unused in the codebase) — a changed PDF (e.g. after `fetch-pdf --force`
  swaps in a different file) is detected automatically and triggers
  silent re-extraction, no separate invalidation flag needed.
  `force=True` always re-extracts regardless of the hash match, so a
  bad/garbled extraction can be fixed even when the underlying PDF hasn't
  changed. Cache file also records which extractor actually produced the
  result (`"pypdf"` or `"pdfplumber"`) and a timestamp. The existing pure
  `extract_pages()`/`extract_full_text()` functions are untouched (still
  independently testable); a new `extract_full_text_from_pages()` helper
  joins an already-extracted pages list with `[page N]` markers, shared
  by both the cached and uncached paths.
- `evidence.py::build_dossier()`: extraction call site swapped to the
  cached variant, with `force` threaded through so `wake evidence --force`
  bypasses both the dossier cache *and* the extraction cache. The dossier
  (both `.md` and `.json`) now records `extracted_text_path`, and the
  rendered dossier's "Source" section links to it directly.

### Actor clarity in docs/prompts

Mid-design clarification: "you can open the file" was ambiguous between
the human and the agent. Resolved by writing each doc in the voice of its
actual reader rather than a generic "you": code docstrings use third
person ("a human or agent can inspect..."); `SKILL.md` (agent-facing)
uses "you" to mean the agent explicitly, with a new numbered principle
("before blaming the model's reasoning, check the extraction") and an
addition to step 9's workflow text; `README.md` (human-facing) uses "you"
to mean the person reading the README.

### Tests

+10 offline (226 total): `test_pdf_fulltext.py` (+8) — cache-file shape,
cache-hit skips re-extraction entirely (asserted via mocking the
extractors and confirming zero calls), sha256-mismatch triggers automatic
re-extraction, `force=True` bypasses a valid cache, corrupt cache file
falls back to fresh extraction rather than crashing, plus two new tests
for the extracted `extract_full_text_from_pages()` join helper.
`test_evidence.py` (+2) — end-to-end dossier build asserts the extraction
cache file exists and `extracted_text_path` is correctly threaded through
the result and into the rendered markdown; a dedicated test confirms
`--force` re-invokes extraction (not just the LLM call) even with no PDF
change.

**Test-hygiene fix found along the way**: several existing `test_evidence.py`
tests mocked `fetch_pdf` to return the path to the *committed, shared*
fixture PDF directly (`tests/fixtures/osti_1343551_netcdf_bigdata.pdf`)
rather than a per-test copy. Since `extract_pages_cached()` now writes a
`.json` cache file next to whatever PDF path it's given, running these
tests was silently writing a generated cache file into the committed
fixtures directory on every test run — confirmed by finding a stray
`osti_1343551_netcdf_bigdata.json` after the first test run with the new
code. Fixed by adding a `_copy_fixture_pdf(tmp_path)` helper and updating
every `build_dossier`-exercising test to use a `tmp_path` copy of the
fixture instead of the shared file in place.

### Live verification

- `wake evidence` on a real citing work (W2107546711, FLASH architecture
  paper) confirmed `extracted_text_path` correctly points at
  `wake-out/<seed>/pdfs/W2107546711.json`, sibling to the PDF; the cache
  file contains all 33 real pages, a real sha256, `extractor: "pypdf"`,
  and a timestamp; the rendered dossier's "Source" section links to it.
- Re-running the same `wake evidence` call (no `--force`) returned in
  ~0.5s vs. ~10.7s for the first run — confirmed the dossier-level cache
  short-circuits before extraction is ever touched.
- `wake evidence ... --force` re-ran extraction even with the PDF file
  unchanged (cache file mtime updated, ~7s taken for a real re-extraction
  + re-verification), confirming `force` propagates through both caches
  as designed.

---

# Phase 3 — Structural Hardening

An external static assessment of `main` (source, docs, tests only — no
runtime execution) judged wake's product architecture — epistemic-state
tracking (provisional/proposed/verified), thin agent-facing primitives,
file-first artifacts, source-adapter boundaries — sound, but flagged the
implementation as outgrowing its current shape: a 2,000+-line CLI dispatch
module, an implicit dict-based domain model with no schema versioning,
dependency rebuilding done via bidirectional dynamic imports between
`evidence`/`evidence_wiki`/`themes`/`narrative`, non-transactional JSON+MD
dual writes, process-global config/state, a weakly-typed LLM boundary
(broad retry wraps `json.loads`), and no CI or static tooling. Verified
independently against the real source (2,029-line `cli/main.py`, 167
in-function imports, ~180 `dict[str, Any]` annotations, zero dataclass/
Pydantic/TypedDict usage, no `schema_version` in any artifact, no
`.github/workflows`) before agreeing to act on it. The 651-test offline
suite (`pytest tests/ -m 'not network'`, ~4 min) passing cleanly on `main`
throughout this review is the safety net the whole plan leans on.

Five-phase refactor, one branch per phase, `--no-ff` merge to `main`
before starting the next, offline suite kept green throughout:

0. `chore/ci-and-tooling` — CI + lint/typecheck (this entry)
1. `refactor/domain-models` — explicit Pydantic models + `schema_version`
2. `refactor/wake-context` — `WakeContext` + artifact repository, remove
   `Path.cwd()`/`lru_cache` globals
3. `refactor/build-layer` — JSON canonical / MD+indexes derived,
   centralized rebuild graph, `wake rebuild`
4. `refactor/cli-split` — `cli/commands/<family>.py`, `main.py` reduced to
   context-build + register + dispatch
5. `refactor/llm-boundary` — provider-neutral client, typed per-operation
   response schemas, split retry policy (transport / rate-limit / invalid
   output)

Not adopted: replacing the filesystem-artifact model with a database —
both the assessment and this review agree file-first is a real strength
of the current design, not a symptom to fix.

## v0.4.0 — CI, ruff, mypy (`chore/ci-and-tooling`)

Guardrails first, before any structural change, so every later phase has
a cheap, fast signal if it breaks something the 651-test suite doesn't
directly cover (import cycles, unused code, type confusion at `Any`/`None`
boundaries).

- `pyproject.toml`: `[tool.ruff]` (`target-version = "py310"`,
  `line-length = 100`, `select = ["E", "F", "I", "UP", "B"]`, `E501`
  ignored — prompts/URLs routinely exceed a hard line-length limit and
  wrapping them buys nothing) and `[tool.mypy]` (scoped to `files =
  ["wake"]` only — tests are exercised for correctness by pytest, not by
  mypy; adding type-checking across `tests/` surfaced 560+ pre-existing
  errors and is a separate, much larger, lower-value cleanup). mypy
  baseline is intentionally lenient (`disallow_untyped_defs = false`) —
  wake's domain model is still dict-based (see `refactor/domain-models`
  below), so strict mode would immediately drown in noise instead of
  catching real bugs; tighten incrementally as typed models land.
  `dev` extras gained `ruff`, `mypy`, `pytest-cov`.
- `.github/workflows/ci.yml`: three jobs (`test` matrixed over Python
  3.10–3.13 running the offline suite, `lint` running `ruff check`,
  `typecheck` running `mypy`), on push/PR to `main`.
- Fixed everything ruff's default+`B`/`UP` rule set flagged in `wake/` and
  `tests/` (124 issues, 122 auto-fixable: unsorted imports, unused
  imports, unused variables/loop vars, missing `zip(..., strict=)`,
  deprecated typing imports) plus 5 issues needing a manual read
  (`raise ... from err` in `sources/pdf_abstract.py`/`sources/
  pdf_fulltext.py`'s `ImportError` handlers; a genuinely-dead
  `selected_ids` binding in `classify.py`). No behavior change — verified
  by re-running the full offline suite after each batch of fixes.
- Fixed the 18 real mypy errors surfaced against `wake/` (import-cycle-
  and `Optional`-narrowing gaps, not schema issues): `sources/
  arxiv_fetch.py`'s `params` dict widened to `dict[str, str]`-compatible
  values; `config.py`'s packaged-config path now a concrete `Path` instead
  of an `importlib.resources.Traversable` (`.exists()`/`open()` aren't
  guaranteed on the abstract type even though they always work in
  practice for a real installed package); `pdf_fetch.py`'s per-source
  dispatch narrowed with explicit `assert`s matching the guards already
  enforced a few lines above; `exclude.is_excluded()` widened to accept
  `citing_id: str | None` (several call sites pass a possibly-missing
  `openalex_id` and a `None` id can never be excluded, so `None` is a
  legitimate, meaningful input, not a bug to suppress); `classify.py`/
  `themes.py`/`evidence_wiki.py`/`report.py` — half a dozen
  `dict.get(key)` / dict-comprehension sites where a work's
  `openalex_id`/relationship `label`/OpenAlex `type` is typed as
  `Any | None` at the dict-literal boundary; each fixed by filtering out
  the falsy/non-`str` case inline (walrus-in-comprehension or an explicit
  `if not isinstance(...): return "unknown"` guard) rather than suppressing
  the check, since a missing id/label was already being silently skipped
  or defaulted at runtime — mypy was catching real (if currently harmless)
  looseness, not a false positive.
- `README.md`: new "Development" section documenting `ruff check`/`mypy`/
  `pytest` as the standard pre-commit gate, pointing at the new CI
  workflow.

### Verification

- `ruff check wake/ tests/` — clean.
- `mypy` — clean (46 source files under `wake/`).
- `pytest tests/ -m 'not network'` — 651 passed, 14 deselected, run
  immediately after the ruff auto-fix batch, after the manual ruff fixes,
  and again after all mypy fixes — no regression at any checkpoint.
- CI workflow not yet exercised on GitHub Actions itself (no push access
  from this session) — its three jobs replicate exactly the local
  `pip install -e ".[dev,pdf]"` + `ruff check` + `mypy` + `pytest`
  sequence verified above, across the four supported Python versions
  declared in `pyproject.toml`'s `requires-python = ">=3.10"`.

## v0.4.1 — Explicit domain models (`refactor/domain-models`)

Before writing any model code, ran a research pass (Task agent, no code
changes) inventorying the *actual* runtime shapes of every dict-based
"domain object" — `Work`, classification results, evidence dossiers,
themes, narrative outlines/sections, overrides, and the `[ref:ID]`
reference-marker family — across `classify.py`, `evidence.py`,
`evidence_wiki.py`, `themes.py`, `narrative.py`, and `report.py`. Found
15 distinct legacy-shape normalization functions (classify-2/classify-3
and evidence-1/evidence-2 dual LLM response shapes, `.classify`/
`.overrides.jsonl`/`.manual_abstracts.jsonl` dotfile-rename migrations,
relative-vs-absolute `pdf_path` duality) and confirmed wake has never
written a literal `schema_version` field anywhere — every existing
"version" signal is per-LLM-stage (`prompt_version`+`model`) or
`.state.json`'s own `tool_version`. Given that surface area, scoped this
phase deliberately narrow rather than attempting a full rip-and-replace
of every dict call site in one pass: an additive schema layer plus
write-time validation at the real persistence boundaries, leaving every
function's existing dict-based signature and return type untouched.
Later phases (`refactor/wake-context`, `refactor/build-layer`) can adopt
the models more deeply once this foundation is in place.

- `pyproject.toml`: added `pydantic>=2.0` to core `dependencies` (not
  `dev` — the models are meant to be used by the library itself, not
  just by tests).
- New `wake/models.py`: `Work`, `RelationshipFacet`, `ClassificationResult`,
  `EvidenceQuote`, `EvidenceDossier`, `ThemeWork`, `Theme`,
  `NarrativeComponent`, `NarrativeOutline`, `NarrativeSection`,
  `Override`, and `ArtifactReference` (the `[ref:ID]` marker family,
  modeled as `{kind: "seed"|"citing_work", id: str}` — see the module's
  own docstring for why the *rendered* forms of a reference, e.g. `[Rn]`
  links or relative frontmatter paths, stay presentation logic, not part
  of the model). Every model:
  - carries a new `schema_version` field (`SCHEMA_VERSION = 1`),
    defaulted so a pre-existing, pre-model artifact on disk (no
    `schema_version` key at all) still validates -- non-breaking for
    every wake-out/ packet that predates this change;
  - is `extra="allow"` (tolerant of fields this pass hasn't modeled,
    e.g. `EvidenceDossier.provisional`/`.proposed` stay `dict[str, Any]`
    rather than fully nested models -- the multi-facet-vs-legacy-scalar
    shape duality documented in the research pass is exactly the kind of
    thing better handled by a future explicit migration than by
    encoding both shapes into a strict schema right now);
  - exposes `.to_json_dict()` (excludes unset optionals, matching
    today's dict-based writers, which omit e.g. `human_verification`
    entirely rather than writing it `null`) and a shared
    `validate_or_raise(data, context=...)` classmethod that wraps
    pydantic's `ValidationError` in a plain `ValueError` naming the
    model and the call site, so callers never need to import pydantic.
  - Deliberately duplicates `CANONICAL_RELATIONSHIPS` from classify.py
    rather than importing it, and imports nothing from the rest of wake
    at all -- a hard constraint (mechanically enforced by an AST-walking
    test in test_models.py, not just a docstring claim) so `models.py`
    can be adopted by any other module without circular-import risk.
- Wired `validate_or_raise` into every real write site for these five
  artifact types, immediately before the `atomic_write_json`/
  `atomic_write_text` call, so a future shape regression fails loudly at
  the point of writing rather than surfacing later as a confusing read-
  side KeyError: `classify.py::_write_sidecar` (`ClassificationResult`);
  `evidence.py::build_dossier` and `evidence.py::rerender_dossier_md`'s
  opportunistic path-migration branch, plus `evidence_wiki.py::
  mark_verified`/`mark_pending` (`EvidenceDossier`, 4 call sites total —
  every place a dossier JSON sidecar is written or patched);
  `themes.py::create_theme` and `confirm_theme` (`Theme`, 2 sites);
  `narrative.py::create_outline`, `create_section`, and `confirm_section`
  (`NarrativeOutline`/`NarrativeSection`, 3 sites); `report.py::
  add_override` (`Override`, 1 site). No behavior change to any
  function's inputs, outputs, or the on-disk JSON shape itself — the
  guard only ever raises on a payload that was already wrong.
- One real (if narrow) bug caught immediately by wiring the guard in:
  `tests/test_classify.py::test_write_sidecar_migrates_legacy_dotfile_dir_in_place`
  called `_write_sidecar` with a bare `{"relationship": "extends"}` --
  missing `confidence`/`justification`/`relationships` entirely. It
  happened to work before only because nothing downstream of that
  specific migration-focused test ever read those fields back. Fixed the
  test to use a realistic payload rather than loosening the model.

### Tests

+25 in new `tests/test_models.py`:
- Round-trips every model against a *real* function call (mocked
  LLM/network, same fixtures/patterns as each module's own tests), not
  just synthetic dicts: `classify_one`'s return value and
  `classify_all`'s sidecar shape, `build_dossier`'s JSON sidecar before
  and after a real `add_override(..., verification_source=
  "evidence-dossier")` call (proving `EvidenceDossier` validates both
  the pending-review and verified shapes), `create_theme`'s sidecar,
  `create_outline`'s and `create_section`'s sidecars, and
  `add_override`'s `overrides.jsonl` entry via `load_overrides`.
- Confirms non-breaking adoption directly: a real on-disk dossier
  sidecar (predating this change, no `schema_version` key at all) parses
  with `schema_version == SCHEMA_VERSION` filled in by the model's
  default, and `"schema_version" not in <the raw sidecar>` is asserted
  in the same test to make the "old data, new model" claim concrete
  rather than assumed.
- Rejection-path tests: unknown relationship label, empty `relationships`
  list, invalid theme/section slug shape -- each via `pydantic.
  ValidationError` directly against the model.
- Contract tests for the `validate_or_raise` write-guard itself (not the
  models in isolation): confirms it raises a plain `ValueError` (never a
  raw `pydantic.ValidationError`) naming both the model class and the
  caller-supplied context string; exercises the *actual* write-site
  guards in `classify.py::_write_sidecar` and `report.py::add_override`
  with a genuinely malformed payload and confirms nothing was written to
  disk (`load_overrides(...) == {}`, no `wake-out/` directory created).
- `test_models_module_has_no_wake_imports` -- an AST-based test walking
  `wake/models.py`'s own import statements, mechanically enforcing the
  "no dependency on the rest of wake" design constraint rather than
  leaving it as a docstring claim a future edit could quietly violate.
- `test_canonical_relationships_matches_classify_module` -- pins
  `models.py`'s deliberately-duplicated `CANONICAL_RELATIONSHIPS` tuple
  identical to `classify.py`'s own source-of-truth copy.

### Verification

- `ruff check wake/ tests/` — clean.
- `mypy` — clean (47 source files under `wake/`, up from 46 with the new
  `models.py`).
- `pytest tests/ -m 'not network'` — 676 passed, 14 deselected (up from
  651 at the start of this phase: +25 in `test_models.py` covering the
  new module, including 5 tests exercising the real write-site guards in
  `classify.py`/`report.py`/`themes.py`), run after every write-site
  wiring change (classify, evidence, evidence_wiki, themes, narrative,
  report) with zero regressions at any checkpoint.
- Not yet done, left for a later pass once real `wake-out/` packets exist
  again in a working session: a golden-fixture test that loads a
  packet built by pre-`refactor/domain-models` wake (i.e. a real
  `classified.json`/dossier/theme/section/`overrides.jsonl` with no
  `schema_version` key anywhere) and confirms every model in
  `models.py` parses every relevant file in it without modification --
  the in-test coverage above proves this at the unit level (see the
  "non-breaking adoption" bullet), a full-packet-level golden test is
  the natural next-step reinforcement, called out explicitly in
  BACKLOG.md Theme L rather than silently dropped.

## v0.4.2 — WakeContext, and fixing two real process-global bugs (`refactor/wake-context`)

Before writing any code, checked how invasive a full "thread WakeContext
through every domain function" rewrite would actually be: ~90 existing
call sites already take an optional `base: Path | None = None` parameter
(seed.py::work_dir() resolves it against `$WAKE_WORK_DIR`/cwd when
omitted), and 11 modules call one of `config.py`'s per-section accessors
(`config.classify_cfg()`, `config.models()`, etc.) directly. Rewriting
all of that in one pass to take an injected context object instead would
be the single largest-blast-radius change in the whole "Structural
Hardening" plan -- scoped this phase the same way as Phase 1 (`refactor/
domain-models`): fix the two concrete, verifiable bugs the assessment's
"too process-global" complaint was actually about, and land `WakeContext`
as a real, tested, constructible object with one canonical construction
point, rather than force a mechanical signature rewrite across every
domain module in the same pass that introduces the type.

**Bug 1 (confirmed live before fixing): `config.load()`'s cache masked a
real cwd change.** `@lru_cache(maxsize=1)` cached against zero arguments,
so the *first* call in a process pinned the merged config forever --
running wake as a library against two different working directories
(each with a different `wake.config.yaml`) in the same process silently
returned the first directory's config for both. Reproduced directly:
`cd dir1; config.load()` then `cd dir2` (with a different
`wake.config.yaml`) then `config.load()` returned dir1's config both
times. Fixed by keying the cache on the *resolved* local-config path
(`_load_cached(local_config_path: str)`, `@functools.cache`) rather than
a bare zero-arg slot: each distinct `wake.config.yaml` still only reads/
merges from disk once per process (no perf regression for the CLI's
normal one-process-one-cwd case), but a genuinely different cwd/config
is never masked. Re-verified the exact repro now returns the correct
per-directory config both times. `reload()` (used by `wake config init`
and tests) updated to call `_load_cached.cache_clear()`.

**Bug 2: malformed `.state.json` was silently indistinguishable from
missing state.** `load_state()` returned `{}` for both "brand new seed,
nothing has run yet" (normal, expected, silent) and "the state file
exists but is corrupt JSON" (e.g. a process killed mid-write before
`atomic_write_json`'s `os.replace` landed, or hand-editing gone wrong) --
identical silent behavior for two very different situations. `{}` is
still the *correct* fail-safe return value in both cases (every consumer
only ever uses this for cache-invalidation via `is_stage_current` --
"assume nothing has completed, re-run the stage" is safe either way),
but the *visibility* now differs: a malformed file triggers a stderr
warning naming the exact path and error, and the unreadable file is
quarantined (renamed to `.state.json.corrupt-<timestamp>`) so the warning
doesn't repeat on every subsequent call in the same session, and a human/
agent debugging a work_dir later can find the quarantined file and see
exactly what went wrong instead of it having vanished.

**New `wake/context.py`: `WakeContext`.** A dataclass bundling
`workspace` (aliased as `.base`, exactly the `Path | None` every existing
domain function's `base=` parameter already accepts -- `ctx.base` is a
drop-in value for any of those ~90 call sites today), `settings`
(defaults to `config.load()`'s process-wide resolved config if unset),
and two forward-looking, currently-trivial extension points
(`llm_client_factory`, `source_registry`) that later phases can wire in
without another dataclass-shape change. `WakeContext.from_cli_args(args)`
is the one canonical construction point, wired into `cli/main.py`'s
`_work_dir_base()` helper (every one of the CLI's ~40 `run_*()` handlers
already calls `_work_dir_base(args)`, so this is a one-line internal
change with identical external behavior, not a rewrite of every command
handler). Explicitly scoped as additive: constructing `WakeContext()`
with no arguments reproduces today's implicit cwd/`$WAKE_WORK_DIR`/
`config.load()` behavior exactly -- nothing downstream breaks, and the
module's own docstring states plainly that full domain-function-level
adoption (passing `ctx` instead of `base=`/direct `config.*_cfg()` calls
throughout `classify.py`/`evidence.py`/etc.) is deferred to a follow-on
pass, tracked in BACKLOG.md Theme L.

### Tests

+12: `tests/test_context.py` (9) -- default-context behavior, `.base`/
`.workspace` aliasing, `settings_or_default()`'s explicit-vs-fallback
behavior, `from_cli_args()`'s work-dir resolution (explicit, absent,
attribute-missing-entirely), the actual `cli/main.py::_work_dir_base`
delegation (not just the context class in isolation), and a direct
drop-in-compatibility check against `seed.work_dir()`. `tests/
test_state.py` (+3) -- malformed-state returns `{}` and warns (path and
"malformed" both asserted in the captured stderr), the corrupt file is
actually quarantined and its original bytes preserved, and a second
`load_state()` call on the same work_dir doesn't repeat the warning
(the corrupt file has already been renamed aside, so the second call
just sees an ordinary missing file).

### Verification

- `ruff check wake/ tests/` — clean (one incidental fix along the way:
  `@lru_cache(maxsize=None)` → `@functools.cache`, ruff's UP033).
- `mypy` — clean (48 source files under `wake/`, up from 47 with the new
  `context.py`).
- `pytest tests/ -m 'not network'` — 688 passed, 14 deselected (up from
  676 at the start of this phase: +9 `test_context.py`, +3
  `test_state.py`).
- Both bugs reproduced live (via a standalone script exercising the real
  module, not just inferred from reading the source) before fixing, and
  re-verified fixed with the same repro after.

## v0.4.3 — Centralized build layer + `wake rebuild` (`refactor/build-layer`)

Before writing any code, ran a research pass (Task agent, no code
changes) mapping every `rebuild_*`/`rerender_*`/`mark_verified`/
`mark_pending`/`append_log_entry`/`_refresh_*` function's reads, writes,
callers (module-level vs. in-function imports), and trigger conditions,
plus a call-graph table of which of the 13 functions each real write
operation (`wake evidence`, `wake override`, `wake unverify`, `wake
theme create/confirm`, `wake narrative outline/section create/confirm`,
`wake exclude`/`unexclude`, `wake dedup confirm`/`reject`) triggers,
directly or transitively. Confirmed several concrete things the
assessment predicted, plus some it didn't call out specifically:

- **JSON+MD writes are never one atomic transaction** (confirmed, as
  expected) -- every site is two independent `atomic_write_text`/
  `atomic_write_json` calls. But the research also found the *ordering*
  is inconsistent across the codebase: `themes.py`/`narrative.py`/
  `evidence_wiki.py`'s `mark_verified`/`mark_pending` all write JSON
  before MD (safer -- every `rerender_*` function treats JSON as ground
  truth, so a crash mid-write leaves a recoverable `.json`-only state).
  `evidence.py::build_dossier()` did the *opposite* -- MD before JSON --
  which is the riskier order (a crash leaves an orphan `.md` with no
  `.json` backing it at all, and every index/orientation function globs
  `*.json`, never `*.md`, so that orphan wouldn't even be counted
  anywhere). Fixed by reordering `build_dossier()` to write JSON first,
  matching the safer convention already used everywhere else.
- **Two derived artifacts had no standalone rebuild entry point at
  all**: `evidence_wiki.rebuild_index()` (evidence/index.md) and
  `evidence_wiki.rebuild_themes_index()` (evidence/themes/index.md) were
  only ever reachable as an implicit side effect of `build_dossier`/
  `add_override`/`unverify_work` or `create_theme`/`confirm_theme`
  respectively -- if a human deleted or hand-edited one of those index
  files directly, there was no command that could regenerate it without
  re-running an unrelated write operation.
- **The two existing bulk "rerender-all" commands don't call the index
  rebuild they logically feed**: `wake theme rerender-all` re-renders
  every theme's own `.md` but never calls `rebuild_themes_index`; `wake
  narrative section rerender-all` re-renders every section's `.md` but
  never calls `_refresh_outline_md`, so `outline.md`'s live per-component
  status column can go stale even right after running it.
- **No single "rebuild everything for this seed" entry point existed**
  (confirmed via exhaustive grep -- no `rebuild_all`/`resync`/
  `rebuild_seed`/`rebuild_everything` anywhere). `AGENTS.md`'s own
  "Regenerating derived files" section (the wiki's self-documentation)
  listed 4 commands but not `wake narrative section rerender-all`, and
  even running all 4 in the listed order still leaves `evidence/
  index.md`/`evidence/themes/index.md` stale per the point above.
- Every derived artifact this project's docs describe as regeneratable
  (dossiers, theme docs, outline, sections, narrative.md, impact.md,
  README.md, AGENTS.md) does have a pure, LLM-free, JSON-sidecar-driven
  render function -- except `evidence/log.md`, which is fundamentally
  append-only (no `log.json` exists; past events can only be appended
  to, never reconstructed from other JSON).

**New `wake/build.py::rebuild_seed(seed_work, base=, verbose=)`.** A
single, explicit entry point that walks every derived artifact type
*that currently has JSON backing on disk for this seed* (skipping any
type with none, same "no-op if nothing to do" convention every
individual `rerender_*` already follows), in dependency order: dossiers
→ evidence/index.md → theme docs → themes/index.md → narrative sections
→ outline.md → narrative.md → impact.md → README.md/AGENTS.md (last,
since the orientation counts summarize everything rebuilt above it).
No LLM or network call anywhere in this path -- verified directly by a
test that monkeypatches `chat_json`/`chat_text` to raise if called at
all during a full rebuild. Returns a structured per-step summary
(`{"step": "...", "rebuilt": [...] | bool}`) so a caller (CLI or agent)
can see exactly what was and wasn't touched, closing both of the
"orphaned rebuild function" and "no single entry point" gaps found in
the research pass. Deliberately does **not** call `mark_verified`/
`mark_pending`/`unverify_work` -- those represent a human verification
decision, not a re-render of already-decided data, and are out of scope
for a pure rebuild.

**New `wake rebuild <seed>` CLI command** (`cli/main.py`), following the
same `--json`/human-output/`_work_dir_base` conventions as every other
command. Documented in `docs/workflow.md`'s command table, the SKILL's
`references/reference.md` full command list, and — most importantly —
`AGENTS.md`'s own "Regenerating derived files" section (the file wake
writes *into every packet*, read by whatever agent picks up the folder
next), rewritten to lead with `wake rebuild` as the one-call answer
while keeping the individual `--rerender-all`/`stitch`/`bake` verbs
documented for a narrower, targeted re-render.

### Tests

+11 in new `tests/test_build.py`, reusing `test_wiki_invariants.py`'s
`_build_full_wiki` fixture (a complete real packet: dossiers, a
confirmed theme, a stitched narrative, a baked impact brief) rather than
reimplementing multi-stage setup: empty-packet no-op behavior, every
populated artifact type actually gets touched, a deleted dossier `.md`
is restored purely from its still-present `.json` sidecar, the two
previously-orphaned index files (`evidence/index.md`, `evidence/themes/
index.md`) are restored after manual deletion, a hand-edited section
JSON's status change is reflected in a refreshed `outline.md` (closing
the "rerender-all doesn't refresh outline.md" gap directly), the
`impact` step's `citing.json` precondition (mirrors `wake bake`'s own
requirement) both when absent and when present, the never-calls-an-LLM
guarantee, and a full wiki-invariants pass (frontmatter/link validity)
after a rebuild to confirm rebuilding never degrades output quality
relative to the original write path. +2 CLI-level tests (`wake rebuild`
via `wake.cli.main.main()`, both `--json` and human-output modes),
following `test_show_verbs.py`'s existing end-to-end CLI-test convention.

### Verification

- `ruff check wake/ tests/` — clean.
- `mypy` — clean (49 source files under `wake/`, up from 48 with the new
  `build.py`).
- `pytest tests/ -m 'not network'` — 699 passed, 14 deselected (up from
  688 at the start of this phase: +11 `test_build.py`).
- The `build_dossier()` MD/JSON write-order fix was verified against the
  full evidence test suite (`test_evidence.py`, `test_evidence_wiki.py`,
  `test_multi_facet_evidence.py`, `test_models.py`,
  `test_wiki_invariants.py`) immediately after the change, before moving
  on to `build.py` itself, to isolate any regression to that one change.

## v0.4.4 — Split `cli/main.py` by command family (`refactor/cli-split`)

`cli/main.py` had grown to 2,073 lines across ~90 functions (26
`_build_*_parser` argparse builders + ~64 `run_*` handlers), the exact
"god module" the external assessment flagged first. Sequenced
deliberately last among the four completed phases, per the assessment's
own recommended order ("split the CLI after the context/repository
interfaces exist, so the split creates real boundaries rather than
merely more files") -- `WakeContext`/`_work_dir_base` (Phase 2) and
`wake/build.py` (Phase 3) already existed by the time this phase
started, so the split didn't have to invent those boundaries itself.

**Mechanical extraction, not a rewrite.** Every function's line range
was mapped programmatically first (a script walking `def name(` at
column 0 to get exact start/end boundaries for all 83 top-level
functions), verified to partition the file completely (every function
assigned to exactly one of 13 command-family groups, zero missed, zero
duplicated) before any file was written, then each group's functions
were extracted into `wake/cli/commands/<family>.py` byte-for-byte from
the original source -- no logic was retyped by hand, eliminating the
main risk of a large manual split (a transcription slip silently
changing behavior). The one genuinely manual step was fixing relative
import depth: every function's in-function `from ..module import x`
became a `wake.cli.module` reference once literally copy-pasted one
directory deeper (`cli/main.py` -> `cli/commands/<family>.py`), so every
occurrence needed promoting to `from ...module import x` to still reach
top-level `wake/*.py` modules -- done via a second script matching
against the known set of top-level module names (to avoid
over-promoting the handful of genuinely `wake.cli.*`-relative imports:
`..emit`, `..main_helpers`, and `misc.py`'s `from ..skill import
run_skill`), then hand-verified via `ruff`'s `F821` (undefined name)
check, which caught exactly one real cross-module dependency the
mechanical split didn't handle: `evidence.py`'s `_find_classified_work`
called a private helper (`_find_citing_work`) that had been extracted
into `pdf.py` instead. Moved that helper into the new
`main_helpers.py` (alongside `_work_dir_base`/`_resolve_seed_to_work`,
the two helpers already shared cross-module) rather than leaving it
duplicated or awkwardly cross-imported between two command modules.

**Final shape:**
```
wake/cli/
  main.py            # 141 lines (from 2,073): _build_parser() delegating
                      # to each family's _build_*_parser, a dict-based
                      # _DISPATCH (command name -> run_* handler) replacing
                      # the old ~50-branch if/elif chain, KeyboardInterrupt
                      # handling. _work_dir_base re-exported for
                      # backward compat (tests/other modules imported it
                      # directly from wake.cli.main before this split).
  main_helpers.py     # _work_dir_base, _resolve_seed_to_work,
                      # _find_citing_work -- shared across command
                      # modules, living outside main.py to avoid a
                      # circular import (every commands/*.py imports
                      # from main_helpers, not from main.py itself).
  commands/
    resolve.py        # wake resolve / wake status (108 lines)
    citing.py         # wake citing / sample / describe (92 lines)
    classify.py        # wake classify (91 lines)
    gaps.py            # wake gaps / missing-pdfs (150 lines)
    dedup.py           # wake dedup candidates/confirm/reject (138 lines)
    posters.py         # wake posters candidates/keep (94 lines)
    pdf.py              # wake fill-abstract / fetch-pdf (110 lines)
    evidence.py         # wake evidence (231 lines)
    theme.py            # wake theme create/confirm/queue/show/rerender-all (188 lines)
    narrative.py        # wake narrative outline/section/stitch/refs-check/show (377 lines)
    report.py           # wake bake / rebuild / override (126 lines)
    exclude.py          # wake exclude/unexclude/unverify (161 lines)
    misc.py             # wake cost/show/seed/config/skill (250 lines)
```
Every module follows the same shape: a module docstring naming its
command family and pointing at this PLAN.md entry, `_build_*_parser`
functions first, `run_*` handlers after, in the same order they
appeared in the original file (no reordering beyond grouping, to keep
the diff-against-history reviewable).

**No behavior change anywhere** -- confirmed by: `wake --help`'s output
byte-identical in command list/help text to before the split (all 26
subcommands, same help strings, same argument definitions); the full
699-test offline suite passing unchanged; and every existing CLI-level
integration test (`test_show_verbs.py`, `test_evidence_rendering.py`,
`test_missing_pdfs.py`, `test_pdf_verify.py`, `test_seed_fetch_pdf.py`,
`test_cli_skill.py`, `test_build.py` -- all of which invoke the real
`wake.cli.main.main()` via `sys.argv`, not a mock) passing without any
test-side changes, since `from wake.cli.main import main` and
`from wake.cli.main import _work_dir_base` both still resolve exactly
as before.

New `wake/cli/commands/__init__.py` (empty, matching the existing
`wake/cli/__init__.py`/`wake/sources/__init__.py` convention) --
confirmed `wake.cli.commands` is picked up by
`pyproject.toml`'s existing `[tool.setuptools.packages.find]`
(`include = ["wake*"]`, which recurses into any matching subpackage) with
no config change needed.

### Verification

- `ruff check wake/ tests/` — clean (one real fix along the way: a
  second pass normalizing inconsistent single-vs-double blank lines
  between top-level functions left over from the mechanical
  concatenation, plus the expected batch of now-unused `emit_error`/
  `sys`/`Path` imports per module once each module only used a subset of
  the original file's shared imports).
- `mypy` — clean (64 source files under `wake/`, up from 49 — 13 new
  command modules + `main_helpers.py` + the new `commands/` package).
- `pytest tests/ -m 'not network'` — 699 passed, 14 deselected,
  unchanged from the end of Phase 3 (this phase added no new tests by
  design -- it is a pure internal reorganization with an existing,
  already-comprehensive CLI-level test suite as its safety net, not a
  new capability needing new coverage).
- `wake --help` and every subcommand's own `--help` manually diffed
  against the pre-split output — identical.

## v0.4.5 — Split LLM retry policy by failure class (`refactor/llm-boundary`)

Final phase of the structural-hardening plan. Confirmed the assessment's
concrete complaint live before fixing it: `wake/llm/openai_client.py`'s
single `@retry(stop=stop_after_attempt(3), wait=wait_exponential(...))`
decorator on `chat_json`/`chat_text` retried *every* `openai.*Error`
subclass identically -- a genuinely transient failure (rate limit,
timeout, connection error, 5xx) and a permanent one (bad API key,
malformed request, unknown model, 4xx) both got the same 3-attempt,
~4s-of-backoff treatment. Reproduced directly: mocking a bad-API-key
`AuthenticationError` cost 3 calls and ~4.0s before this fix, 1 call and
~0.13s after.

Scoped narrower than a full "provider-neutral client interface +
per-operation typed response schemas" rewrite, for a concrete reason
found while investigating the second half of that ask: `classify.py`'s
`_parse_relationships_response` (and evidence.py's analogous
`_parse_proposed_relationships`) already deliberately treat a
malformed/off-schema LLM response as *recoverable*, not an error --
unknown labels are dropped, missing/unparseable confidence defaults to
0.5, and a response with nothing usable left falls back to a safe
`background-mention` facet rather than raising. Adding strict schema
validation "immediately after generation" as originally proposed would
have been a regression against that deliberate graceful-degradation
design, which is a real strength of wake's classify/evidence pipeline
(a single malformed classification during a 400-work batch run should
degrade to a low-confidence guess, not abort the whole run). Only 4 real
call sites exist across the whole codebase (`classify.py`, `evidence.py`
via `chat_json`; `describe.py`, `abstract_extract.py` via `chat_text`),
each already wrapping its own call in caller-appropriate error handling
(`classify_all`'s broad `except Exception` records `error`/`error_at`
and continues the batch, rather than crashing it) -- so a provider-
neutral abstraction layer on top of a single already-thin OpenAI-
compatible wrapper had no concrete problem left to solve once the
retry-policy split and error-type clarity below were in place.

**What was built:**

- **Retry policy split by failure class.** New `_is_transient_openai_error()`
  classifies an `openai.OpenAIError` as retry-worthy (`APIConnectionError`,
  `APITimeoutError`, `RateLimitError`, `InternalServerError`) or not
  (`AuthenticationError`, `BadRequestError`, `NotFoundError`,
  `PermissionDeniedError`, `UnprocessableEntityError`, `ConflictError`,
  or any non-OpenAI exception). `_stream_completion()`'s `@retry` decorator
  now uses `retry_if_exception(_is_transient_openai_error)` instead of
  retrying unconditionally -- a permanent failure raises immediately
  instead of being retried into the same guaranteed failure 3 times.
- **New `LLMInvalidRequestError`** -- raised (wrapping the original
  `openai.*Error` as `__cause__`, never discarded) for a request that
  cannot succeed regardless of retry count. Distinguishable by type from
  a transient failure that exhausted its retries (`tenacity.RetryError`,
  unchanged for that case).
- **New `LLMResponseError`**, and the JSON-parsing retry pulled out of
  `chat_json` into a separate `_parse_json_response()` helper -- a
  malformed response body (valid HTTP response, invalid JSON even after
  the existing prefixed-prose recovery pass) is a distinct failure class
  from a transport failure: re-sending the identical request is unlikely
  to help, since the model already produced a complete response that
  simply wasn't valid JSON. Previously this surfaced as tenacity's opaque
  `RetryError` wrapping a `json.JSONDecodeError` (the whole
  network-retry-with-backoff machinery ran again for a failure a retry
  could never fix); now it's a single, clearly-labeled
  `LLMResponseError` raised on the first and only parse attempt.
- **`cli/main.py`'s top-level dispatch** now catches
  `LLMInvalidRequestError`/`LLMResponseError` and emits a clean
  `emit_error` (matching every command's own convention) instead of an
  uncaught traceback -- these are now well-defined, nameable failure
  modes rather than an arbitrary `openai.*Error`/`RetryError` bubbling
  to the top uncaught.
- `classify_all`'s existing broad `except Exception` (records
  `error`/`error_at` per work, continues the batch) needed no change --
  it already catches these new, more specific exception types
  transparently, and now reports a clearer `str(exc)` message
  (`"AuthenticationError: ... -- not retrying, this request cannot
  succeed..."` instead of a bare `RetryError` repr) in the per-work
  error sidecar and CLI warning line.

### Tests

+14 in `tests/test_openai_client.py`: `_is_transient_openai_error`
classification for every `_PERMANENT_OPENAI_ERRORS` member, both
transient error types, and a non-OpenAI exception; the core regression
fix itself (`test_chat_json_fails_fast_on_permanent_error_no_retry_no_backoff`
-- asserts exactly 1 call and <1s elapsed for an `AuthenticationError`,
pinning the bug this phase fixes so it can't silently regress); the
complementary case (`test_chat_json_retries_transient_error_with_backoff`
-- a `RateLimitError` still gets the full 3-attempt treatment, confirming
the fix didn't accidentally stop retrying errors worth retrying);
`__cause__` preservation on `LLMInvalidRequestError`; the updated
JSON-parse-failure test (`LLMResponseError`, replacing the old
`tenacity.RetryError` assertion -- a deliberate, documented behavior
improvement, not an incidental test change); and one CLI-level
end-to-end test (`wake describe` via the real `wake.cli.main.main()`,
with the OpenAI client mocked to raise `AuthenticationError`) confirming
`main()`'s new top-level catch emits a clean `--json` error envelope
(`{"ok": false, "error": {"type": "LLMInvalidRequestError", ...}}`)
rather than propagating an uncaught traceback.

### Verification

- `ruff check wake/ tests/` — clean.
- `mypy` — clean (64 source files under `wake/`, unchanged count --
  this phase modified `llm/openai_client.py` and `cli/main.py` in
  place, no new modules).
- `pytest tests/ -m 'not network'` — 713 passed, 14 deselected (up from
  699 at the start of this phase: +14 `test_openai_client.py`).
- The core fix (1 call / <1s for a permanent error, vs. 3 calls / ~4s
  before) was reproduced live with a standalone script before writing
  any test, then re-verified via the same repro after, matching the
  verification discipline used throughout every phase of this plan.

---

This closes out the six-phase "Structural Hardening" plan (chore/
ci-and-tooling through refactor/llm-boundary) opened by the external
assessment reviewed at the start of this effort. Summary of what
changed across all six phases: CI + lint/typecheck (v0.4.0); explicit
Pydantic domain models with write-time validation (v0.4.1); WakeContext
plus two confirmed-live process-global bugs fixed (v0.4.2); a
centralized `wake rebuild` closing three real derived-artifact-rebuild
gaps (v0.4.3); `cli/main.py` split from 2,073 lines/~90 functions into
13 command modules with zero behavior change (v0.4.4); LLM retry policy
split by failure class (v0.4.5); and dossier versioning made real
(v0.4.6). Offline test count grew from 651 (pre-effort baseline) to
722, entirely additive. Remaining follow-on work identified but
deliberately deferred, all tracked in BACKLOG.md Theme L: a
whole-packet golden-fixture test on a real OSTI packet (deferred for an
interactive session), replacing the 15 catalogued legacy-shape
normalization functions with explicit versioned migrations for the other
artifact families (themes, narrative, classification, overrides), full
`WakeContext` threading through all ~90 existing `base:`-taking domain
functions, and a persisted dirty/revision manifest for `wake rebuild`.

## v0.4.6 — Dossier versioning: make schema_version real (`refactor/dossier-versioning`)

**Second-look assessment driver:** The assessment (20260806-wake-assessment-2.md) confirmed
that every write site called `Model.validate_or_raise(payload)` then `atomic_write_json(path,
payload)` -- discarding the validated model and writing the raw dict. This meant `schema_version`
was checked but never persisted, `extra="allow"` on the write model accepted misspelled fields
into canonical state, and the path-normalization migration in `rerender_dossier_md` only ran on
rerender, not on every load. The assessment described this as converting the schema layer from
advisory to genuine persistent format management.

**Scoped to dossiers only** -- a proven pattern to replicate for the other four artifact families
(themes, narrative, classification, overrides) in future passes, once a real golden-packet
acceptance test is in hand.

### What changed

**`wake/models.py`**

- `EVIDENCE_DOSSIER_VERSION = 2` -- the current on-disk version for newly written dossiers.
- `EvidenceDossierWrite(EvidenceDossier)` -- strict write subclass with `extra="forbid"`;
  `EvidenceDossier` (read model) keeps `extra="allow"` so old or forward-versioned JSON is always
  tolerated at read boundaries (index rebuilds in evidence_wiki.py, etc.).
- `migrate_dossier(raw, *, sidecar_dir=None) -> dict` -- explicit v0→v1→v2 migration chain:
  - v0→v1: add `schema_version: 1` (makes implicit default explicit, no shape change).
  - v1→v2: normalize legacy absolute `pdf_path`/`extracted_text_path` to relative-from-sidecar
    form (previously done only opportunistically in `rerender_dossier_md`; now happens at every
    read through `load_dossier`). Bump `schema_version` to 2.
  - When `sidecar_dir=None` (unit tests without filesystem), path normalization is skipped.
  - Idempotent: calling on an already-current dict is a no-op.

**`wake/evidence.py`**

- `load_dossier()` now calls `migrate_dossier(raw, sidecar_dir=p.parent)` before returning,
  making every load path version-aware (not only rerenders).
- `build_dossier()` write site: payload now includes `"schema_version": 2` explicitly; write
  uses `EvidenceDossierWrite.validate_or_raise(...).to_json_dict()` rather than the raw dict --
  the first time a validated model's canonical shape (not the caller's raw dict) is what lands
  on disk.
- `rerender_dossier_md()` opportunistic-migration block: replaced the manual absolute-path diff
  with a schema-version check; if the on-disk file pre-dates the migration, the already-migrated
  (post-`load_dossier`) payload is persisted via `EvidenceDossierWrite`.

### Tests

9 new tests (713→722 offline passing), split between `tests/test_models.py` and
`tests/test_build.py`:

- `test_migrate_dossier_v0_no_sidecar_dir` -- v0 dict gets `schema_version=2`, absolute paths
  untouched when no sidecar_dir.
- `test_migrate_dossier_v0_with_sidecar_dir` -- absolute paths become relative.
- `test_migrate_dossier_already_current` -- no-op on a v2 dict.
- `test_migrate_dossier_idempotent` -- calling twice returns equal result.
- `test_old_unversioned_dossier_round_trips_through_load_dossier` -- a pre-v0 JSON file on disk
  is returned with `schema_version=2` and relative paths by `load_dossier`.
- `test_new_dossier_persists_schema_version_on_disk` -- the file on disk has `schema_version=2`
  after `build_dossier` (the specific gap the assessment named).
- `test_evidence_dossier_write_rejects_unknown_field` -- `EvidenceDossierWrite` raises on
  misspelled fields.
- `test_evidence_dossier_read_model_accepts_unknown_field` -- `EvidenceDossier` (read model)
  accepts an unknown field (forward-compat guarantee).
- `test_rebuild_seed_over_pre_migration_dossier` -- `rebuild_seed` succeeds on a wiki whose
  dossier JSON has `schema_version` stripped out; the JSON is upgraded to v2 in place.

### Updated existing test

`test_evidence_dossier_validates_real_build_dossier_json_sidecar` in `test_models.py` previously
asserted `"schema_version" not in sidecar` (the old advisory-only behavior). Updated to assert
`sidecar["schema_version"] == EVIDENCE_DOSSIER_VERSION`.

### Explicitly deferred

- Replicating the strict-write / permissive-read split and migration chain to the other four
  artifact families (themes, narrative, classification, overrides): same pattern, deferred until
  the golden-packet acceptance test is in hand.
- Moving the path-normalization migration to a `rerender_dossier_md` post-write is now
  unnecessary (migration happens at load time); the rerender path persists the upgraded form as
  a side effect.

### Verification

ruff, mypy, 722/722 offline tests passing.

## v0.4.7 — Single source of truth for relationship vocabulary + WakeContext cleanup (`refactor/domain-vocabulary`)

**Assessment drivers:** (1) `CANONICAL_RELATIONSHIPS` was duplicated between `models.py` and
`classify.py` -- two sources of truth kept identical only by an equality assertion test.  (2)
`WakeContext.source_registry` was a never-consumed extension point; the assessment said "avoid
adding more unused context fields until there is a real consumer."

**Changes:**

**`wake/vocabulary.py`** (new, dependency-free)

Single source of truth for the relationship vocabulary:

- `CANONICAL_RELATIONSHIPS: tuple[str, ...]`
- `RelationshipLabel` (the corresponding `Literal` type)

No dependencies on any other wake module.  `models.py` and `classify.py` both import from here.

**`wake/models.py`**

Removed the duplicated `CANONICAL_RELATIONSHIPS` tuple and `RelationshipLabel` alias.  Replaced
with `from wake.vocabulary import CANONICAL_RELATIONSHIPS, RelationshipLabel`.  Re-exported with
`# noqa: F401` for backward compatibility (any existing `from wake.models import
CANONICAL_RELATIONSHIPS` keeps working).

**`wake/classify.py`**

Replaced the local `CANONICAL_RELATIONSHIPS = (...)` tuple definition with `from
.vocabulary import CANONICAL_RELATIONSHIPS`.  No behavior change -- the tuple value is
identical.

**`wake/context.py`**

Removed `source_registry: dict[str, Any]` field (zero consumers; second-look assessment
explicitly named it as an unused extension point to remove).  Updated module docstring to
reflect current fields.  Removed unused `field` import from `dataclasses`.

**`tests/test_models.py`**

Replaced `test_canonical_relationships_matches_classify_module` (equality assertion, two-source
workaround) with two tests:

- `test_canonical_relationships_is_single_source` -- confirms `models.CANONICAL_RELATIONSHIPS`
  and `classify.CANONICAL_RELATIONSHIPS` are the *same object* (structural identity, not a
  copied tuple).
- `test_models_module_only_imports_vocabulary_from_wake` -- updated no-wake-imports guard;
  `wake.vocabulary` is now the single allowed wake import in `models.py`.

**Test count:** 722/722 (net zero -- one test replaced by two, but the equality test is subsumed
by the identity test + the allowlist test).

### Verification

ruff, mypy, 722/722 offline tests passing.

## v0.4.8 — Golden-packet fixture: Dorier Mofka (W4414299303) (`test/golden-packet`)

**Assessment driver:** The second-look assessment (20260806-wake-assessment-2.md) identified a
whole-packet golden-fixture test as "now more important than adding additional unit tests" and
as the gating prerequisite for safely extending the dossier-versioning pattern (Phase 6) to the
other four artifact families.  This phase delivers that fixture.

### Seed paper

Matthieu Dorier et al., "Toward a persistent event-streaming system for high-performance
computing applications," *Frontiers in High Performance Computing*, 2025.
DOI: 10.3389/fhpcp.2025.1638203 · OpenAlex: W4414299303 · OSTI: 3002321 · License: CC-BY 4.0.

### How the packet was generated

A live end-to-end run against OpenAlex + Claude Sonnet 4.6 via the Argo gateway:

```
wake resolve "10.3389/fhpcp.2025.1638203"   # seed PDF auto-fetched from OSTI
wake describe W4414299303                    # LLM contribution paragraph
wake citing W4414299303                      # 4 citing works
wake classify W4414299303                    # real LLM classifications
wake bake W4414299303
wake evidence W4414299303 W4416004498        # background-mention (arXiv PDF)
wake evidence W4414299303 W7167027240        # builds-on (arXiv PDF)
# W4414909013, W4416004574: no PDF available -> no dossier (realistic, noted)
wake override ...  (x2, accept proposed findings)
wake theme create ... provenance-capture
wake theme create ... resilient-workflows
wake narrative outline/section create ... (3 sections)
wake narrative section confirm ... introduction
wake narrative stitch W4414299303
wake rebuild W4414299303
```

Real LLM findings: W4416004574 (RESILIO) and W7167027240 (StreamGuard) classified `builds-on`;
W4414909013 (ControlA) and W4416004498 (LLM Agents for Provenance) classified
`background-mention`.  Both themes are draft (two cited works lack verified dossiers -- PDFs
not publicly available at generation time).

### What is vendored

`tests/fixtures/golden-packet/wake-out/W4414299303/` -- all canonical JSON/JSONL, all derived
Markdown renders, both PDF extraction caches (pdfs/*.pdf.json, seed.pdf.json), and
evidence/log.md.  Binary PDFs stripped (seed.pdf, pdfs/*.pdf).  37 files total.

### Tests (`tests/test_golden_packet.py`)

25 new tests (722->747 offline passing):

- **Schema validation (non-slow):** all canonical artifacts validate against current Pydantic
  models (Work, ClassificationResult, EvidenceDossier, Theme, NarrativeOutline/Section,
  Override).
- **Phase-6 acceptance test (non-slow):** real dossiers on disk have schema_version=2 and
  relative pdf_path; load_dossier() returns schema_version=2 on the real packet; migrate_dossier()
  applied to a stripped real dossier returns schema_version=2 preserving all fields;
  load_dossier() on an artificially-stripped copy upgrades at read time.
- **Rebuild cycle (slow -- shutil.copytree + rebuild_seed()):** succeeds; dossier/override/
  theme/section counts preserved; verification status preserved; double-rebuild produces same
  set of .md files.
- **Structural sanity (non-slow):** evidence/log.md present and non-empty; PDF extraction caches
  exist; seed has description; narrative.md references Mofka.

### Verification

ruff, mypy, 747/747 offline tests passing.

## v0.4.9 — Theme versioning (`refactor/theme-versioning`)

**First of four phases replicating the dossier-versioning pattern (v0.4.6) to the remaining
artifact families**, now unblocked by the golden-packet fixture (v0.4.8).  Theme is the
simplest case: a single-document JSON sidecar with one canonical loader and no existing
legacy-shape normalization to formalize.

### What changed

**`wake/models.py`**

- `THEME_VERSION = 1`.
- `ThemeWrite(Theme)` -- strict write subclass, `extra="forbid"`.  `Theme` (read model) stays
  `extra="allow"` for the several glob-scan bypass readers (evidence_wiki.py's
  `_load_all_themes`, evidence.py's `_themes_citing`, themes.py's `list_theme_needs_evidence`,
  report.py's theme counts) that load every theme sidecar for derived counts/backlinks and must
  stay permissive.
- `migrate_theme(raw) -> dict` -- v0->v1: stamp `schema_version` (no shape change; themes have
  no legacy-shape normalization to formalize, unlike dossiers' path fixup).

**`wake/themes.py`**

- `load_theme()` now calls `migrate_theme()` on every read -- the single canonical loader,
  no bypass to worry about for this family.
- `create_theme()` write site: payload includes `schema_version=THEME_VERSION`; write uses
  `ThemeWrite.validate_or_raise(...).to_json_dict()`.
- `confirm_theme()` write site (the re-persist-of-loaded-dict path): same treatment.
- `rerender_all_themes()`: added the same opportunistic-migration-persistence pattern as
  dossiers' `rerender_dossier_md` -- if the on-disk theme pre-dates the migration, persist the
  migrated form during rerender.

### Tests

7 new tests (747->755 offline passing):

- `test_migrate_theme_v0_stamps_schema_version`, `test_migrate_theme_already_current_is_noop`,
  `test_migrate_theme_idempotent` -- migration chain correctness.
- `test_old_unversioned_theme_round_trips_through_load_theme` -- a pre-v0 JSON file is upgraded
  by `load_theme`.
- `test_theme_write_rejects_unknown_field` / `test_theme_read_model_accepts_unknown_field` --
  strict-write / permissive-read split.
- `test_rebuild_seed_over_pre_migration_theme` (test_build.py) -- `rebuild_seed` upgrades a
  legacy theme in place via `rerender_all_themes`.

**Golden-packet acceptance test** (`test_golden_packet.py`):
`test_theme_jsons_are_unversioned_pre_phase_9_and_migrate_on_read` -- confirms the real Mofka
packet's two themes (generated before this phase existed) have no `schema_version` on disk,
and that `load_theme()` upgrades them to `THEME_VERSION` on read.  This is the retroactive proof
that the migration is correct on genuinely produced artifacts, mirroring the Phase-6 dossier
acceptance test.

### Updated existing test

`test_theme_validates_real_create_theme_json_sidecar` (test_models.py) now additionally asserts
`sidecar.get("schema_version") == THEME_VERSION`.

### Verification

ruff, mypy, 755/755 offline tests passing.

## v0.4.10 — Narrative outline + section versioning (`refactor/narrative-versioning`)

**Second of four phases** replicating the dossier-versioning pattern.  Narrative has one wrinkle
theme didn't: sections have two read paths -- `load_section()` (single) and `_load_all_sections()`
(bulk, used by `stitch`/`export_refs`/`_refresh_outline_md`), and the bulk path bypassed
`load_section()` entirely (parses JSON directly via its own glob).  Both needed the migration
hook.

### What changed

**`wake/models.py`**

- `NARRATIVE_OUTLINE_VERSION = 1`, `NARRATIVE_SECTION_VERSION = 1`.
- `NarrativeOutlineWrite(NarrativeOutline)` -- strict, `extra="forbid"`.  Outline has no bypass
  readers (singleton file, always via `load_outline`).
- `NarrativeSectionWrite(NarrativeSection)` -- strict, `extra="forbid"`.  `NarrativeSection`
  (read model) stays permissive for the cross-module backlink glob scans (`evidence.py`'s
  `_sections_citing`, `themes.py`'s `_narrative_sections_grounded_in`).
- `migrate_outline()`, `migrate_section()` -- both v0->v1: stamp `schema_version` (no shape
  change).

**`wake/narrative.py`**

- `load_outline()` calls `migrate_outline()` on every read.
- `load_section()` **and** `_load_all_sections()` both call `migrate_section()` -- the bulk
  glob-scan path migrates each entry as it's parsed, so `stitch()`/`export_refs()` (which go
  through `_load_all_sections`, not `load_section`) see current-version data too.
- `create_outline()` write site: `schema_version=NARRATIVE_OUTLINE_VERSION`,
  `NarrativeOutlineWrite.validate_or_raise(...).to_json_dict()`.
- `create_section()` and `confirm_section()` write sites: same treatment with
  `NarrativeSectionWrite`.
- `rerender_all_sections()`: added the opportunistic-migration-persistence pattern (same as
  themes/dossiers) -- upgrades a legacy section's JSON in place during rerender.
- Outline has no equivalent bulk-rerender-write path (only `_refresh_outline_md`, which
  re-renders `.md` only, never rewrites `outline.json`) -- documented via
  `test_rebuild_seed_over_pre_migration_outline`, which confirms `rebuild_seed` still succeeds
  even though the outline JSON itself stays legacy-shaped until `create_outline` runs again.

### Tests

14 new tests (755->769 offline passing):

- Migration-chain correctness for both outline and section (stamp, idempotent).
- Old-unversioned round-trip through `load_outline`/`load_section`.
- `test_old_unversioned_section_migrates_via_load_all_sections` -- confirms the bulk bypass
  path also migrates (the wrinkle unique to this phase).
- Strict-write rejects unknown field / permissive-read accepts unknown field, for both models.
- `test_rebuild_seed_over_pre_migration_outline`, `test_rebuild_seed_over_pre_migration_section`
  (test_build.py).

**Golden-packet acceptance test:**
`test_section_and_outline_jsons_are_unversioned_pre_phase_10_and_migrate_on_read` -- confirms
the real Mofka packet's outline and three sections (generated before this phase existed) have no
`schema_version` on disk, and that `load_outline()`/`load_section()` upgrade them correctly.

### Updated existing tests

`test_narrative_outline_validates_real_create_outline_json` and
`test_narrative_section_validates_real_create_section_json` (test_models.py) now additionally
assert the persisted `schema_version`.

### Verification

ruff, mypy, 769/769 offline tests passing.

## v0.4.11 — Classification versioning + new ClassifiedFile wrapper model (`refactor/classify-versioning`)

**Third of four phases**, and the most involved: `classified.json` had no aggregate model and
*no write validation at all* -- the one genuinely unvalidated write in the codebase (confirmed
by the Phase-11 research pass). Closing it required a new wrapper model, not just a Write
subclass of an existing one.

**Key design constraint discovered during research:** `classified.json`'s `works` list
legitimately contains entries with no `relationship` key at all -- a citing work whose
classification LLM call errored is stored as `{**work, "error": ..., "error_at": ...}`
(`classify.py`'s `classify_all()` error-handling branch), and `report.py`'s bake step
deliberately treats these as unclassified (`[w for w in citing_works if w.get("relationship")]`)
rather than rejecting them. This meant `ClassifiedFile.works` could **not** be typed as
`list[ClassificationResult]` (which requires `relationship`) -- it had to stay
`list[dict[str, Any]]`, with per-entry `schema_version` stamping applied only to entries that
are real classifications.

### What changed

**`wake/models.py`**

- `CLASSIFICATION_VERSION = 1`; `ClassificationResultWrite(ClassificationResult)` --
  `extra="forbid"`, used for the per-work `classify/<id>.json` sidecar write (always a real
  classification; `classify_one()`'s return always sets `relationship`).
- `CLASSIFIED_FILE_VERSION = 1`; new **`ClassifiedFile`** model
  (`seed_openalex_id`, `classified_at`, `count`, `works: list[dict[str, Any]]`) -- the first
  validation of any kind on `classified.json`'s wrapper shape. `works` is deliberately loose
  (not `list[ClassificationResult]`) per the design constraint above.
- `ClassifiedFileWrite(ClassifiedFile)` -- `extra="forbid"` at the wrapper level only (does not
  additionally constrain each `works[]` entry).
- `migrate_classification_result(raw)` -- v0->v1: stamp `schema_version` on one sidecar dict.
- `migrate_classified(raw)` -- formalizes the existing implicit bare-list->wrapper handling
  (`classify.py`'s old `data.get("works") if isinstance(data, dict) else data`) as an explicit
  v0->v1 migration step, plus stamps `schema_version` on every `works[]` entry that has a
  `relationship` key (skipping error/unclassified entries, which are left untouched).

**`wake/classify.py`**

- `_load_sidecar()` calls `migrate_classification_result()` on every read.
- `_write_sidecar()` write site: stamps `schema_version`, uses
  `ClassificationResultWrite.validate_or_raise(...).to_json_dict()`.
- `load_classified()` calls `migrate_classified()` on every read (replaces the old inline
  bare-list-vs-wrapper check).
- `save_classified()` write site: stamps `schema_version` on the wrapper and on each real
  (non-error) work entry, validates via `ClassifiedFileWrite`, persists `.to_json_dict()`.

### Tests

13 new tests (769->782 offline passing):

- Migration-chain correctness: sidecar stamping, bare-list wrapping, wrapper stamping,
  idempotency, and the critical **error-entry preservation** test
  (`test_migrate_classified_preserves_error_entries_without_relationship`) confirming an
  error/unclassified entry survives migration completely unchanged.
- `test_classified_file_accepts_error_entries` -- `ClassifiedFile` validates a `works` list
  mixing a real classification and an error entry.
- Strict-write rejects unknown field, for both `ClassificationResultWrite` and
  `ClassifiedFileWrite`.
- `test_save_classified_persists_schema_version_and_stamped_works` /
  `test_save_classified_persists_error_entries_unstamped` -- confirms real entries get
  `schema_version` on disk and error entries do not.
- `test_old_bare_list_classified_json_round_trips_through_load_classified` -- the pre-wrapper
  shape upgrades correctly.

**Golden-packet acceptance test:**
`test_classify_sidecars_and_classified_json_are_unversioned_pre_phase_11` -- confirms the real
Mofka packet's 4 classify sidecars and `classified.json` (generated before this phase existed)
have no `schema_version` anywhere, and that `_load_sidecar()`/`load_classified()` upgrade them
correctly on read.

### Updated existing tests

`test_sidecar_write_and_load` and `test_load_sidecar_falls_back_to_legacy_dotfile_dir`
(test_classify.py) previously asserted exact dict equality after a round-trip; updated to assert
the original fields are preserved plus `schema_version` is now present (both `to_json_dict()`'s
default-filling on write, and `migrate_classification_result()`'s stamping on read of an
un-migrated legacy file, change the exact dict shape by design).

### Verification

ruff, mypy, 782/782 offline tests passing.

## v0.4.12 — Override versioning, JSONL append-only (`refactor/override-versioning`)

**Fourth and final phase** replicating the dossier-versioning pattern.  This closes the
migration story: all five artifact families (dossiers, themes, narrative outline+sections,
classification, overrides) are now versioned, with an explicit `migrate_*()` step and a
strict-write/permissive-read split.

**The migration mechanic differs from the other four families**, as anticipated in the Phase-9
research pass: `overrides.jsonl` is an append-only log, not a single document. There is no
whole-file rewrite to hook a migration into on read -- `load_overrides()` must migrate **each
parsed line, in memory**, as it reads it, rather than rewriting the file. The on-disk lines stay
exactly as they were written; only the in-memory dict handed to callers is upgraded.

### What changed

**`wake/models.py`**

- `OVERRIDE_VERSION = 1`.
- `OverrideWrite(Override)` -- strict, `extra="forbid"`.  Used only by `add_override()`'s
  append; `remove_override()`'s rewrite deliberately preserves every surviving line verbatim
  (including unparseable ones, by design -- see its own docstring) and must not be routed
  through a validating write model.
- `migrate_override(raw) -> dict` -- v0->v1: stamp `schema_version` on one record (no shape
  change). Explicitly documented as per-record, not whole-file, unlike every other
  `migrate_*()` in this module.

**`wake/report.py`**

- `load_overrides()`: each parsed JSONL line is passed through `migrate_override()` before
  being keyed by `citing_id` -- non-destructive, in-memory only.
- `add_override()` write site: stamps `schema_version`, uses
  `OverrideWrite.validate_or_raise(...).to_json_dict()` before appending the line.
- `remove_override()`: **left untouched**, exactly as planned -- its verbatim-preserving
  rewrite contract (surviving lines, including malformed ones, pass through unchanged) is
  incompatible with routing through a migrating/validating write model.

### Tests

8 new tests (782->790 offline passing):

- Migration-chain correctness: stamp, already-current no-op, idempotent.
- `test_load_overrides_migrates_legacy_unversioned_lines_per_record` -- confirms the on-disk
  file is untouched by a read while the in-memory result is upgraded (the core distinguishing
  behavior of this family's migration mechanic).
- Strict-write rejects unknown field / permissive-read accepts unknown field.
- `test_remove_override_preserves_lines_verbatim_including_unversioned` -- confirms
  `remove_override()`'s rewrite still passes a legacy unversioned line for an unrelated
  `citing_id` through completely unchanged (not upgraded, not touched).

**Golden-packet acceptance test:**
`test_overrides_jsonl_is_unversioned_pre_phase_12_and_migrates_on_read` -- confirms the real
Mofka packet's `overrides.jsonl` (2 entries, generated before this phase existed) has no
`schema_version` on any line on disk, and that `load_overrides()` upgrades every record on read.

### Updated existing test

`test_override_validates_real_overrides_jsonl_entry` (test_models.py) now additionally asserts
`entry.get("schema_version") == OVERRIDE_VERSION`.

### Verification

ruff, mypy, 790/790 offline tests passing.

## Migration story: complete

With this phase, **all five persisted artifact families** (`EvidenceDossier`, `Theme`,
`NarrativeOutline`/`NarrativeSection`, `ClassificationResult`/`ClassifiedFile`, `Override`) now
carry an explicit `schema_version`, a `<Model>Write` strict-write variant, and a `migrate_*()`
function invoked at every canonical read site. The ~15 implicit `_normalize_*`/legacy-shape
checks the original assessment catalogued are now either formalized into an explicit migration
step (the bare-list `classified.json` shape, absolute/relative dossier paths) or superseded by
the versioning discipline itself. The golden packet (v0.4.8) served as the acceptance test for
all four of this run's phases (v0.4.9-v0.4.12), each confirming migration correctness against
genuinely produced, pre-migration artifacts rather than only synthetic test dicts.

Offline test count across the four phases: 747 (post golden-packet baseline) -> 755 (themes) ->
769 (narrative) -> 782 (classification) -> 790 (overrides).

---

## v0.4.13 — Documentation reorganization: PLAN.md/BACKLOG.md role split (`docs/backlog-reorg`)

Docs-only phase, no code touched. Prompted by a user observation, in two parts: (1) `BACKLOG.md`
had grown to 1,189 lines interleaving open roadmap items with heavy design rationale for
already-shipped work, making "what's next?" hard to scan; (2) `PLAN.md`, despite its name, had
become ~93% an append-only, past-tense build log (every `v0.2` through `v0.4.12` entry), not a
forward-looking plan -- a genuine role mismatch against standard practice (a "PLAN" doc should be
short and forward-looking; retrospective build history is a changelog/engineering-journal
concern).

**Constraint driving the whole reorg:** ~30 source/test files cite BACKLOG themes by name
(`BACKLOG Theme C`, `BACKLOG Theme J item 9`, `BACKLOG deferred item D.1`, ...) and ~21 files cite
`PLAN.md "Phase 3"` / `PLAN.md v0.4.6`. Per explicit decision, no code/test comments were changed
-- every anchor had to remain resolvable via preserved heading text plus redirect notes/index
tables in the new locations. Verified by grep after the move: every cited anchor (`Theme
A2/C/D/E/F1`, `Theme J item 4/8/9/10/11`, `deferred item A/D.1`, `Phase 3`, `v0.4.6`) resolves in
its new home.

**PLAN.md split:**
- New `docs/build-log.md` -- the append-only engineering journal: verbatim move of everything
  from v0.1's "Build Order (completed)"/"Verification (v0.1)" through `v0.4.12` (the full
  historical record, including this Structural Hardening effort's "Phase 3" heading and every
  `v0.4.x` sub-heading, unchanged). Banner clarifies it is historical, not a plan.
- `PLAN.md` rewritten down to a genuine, short design charter (Goal, Motivation, What We Reuse,
  New Capability, Architecture, Design Decisions, Ranking -- the original v0.1 content minus its
  retrospective Build Order/Verification blocks) plus a new "Current Plan -- What's Next" section
  that actually looks forward (next phase: formalize the remaining `_normalize_*` migrations) and
  a redirect note pointing existing `PLAN.md "Phase N"`/`v0.4.x` references at `docs/build-log.md`.

**BACKLOG.md reorg:**
- New `docs/design/backlog-built-history.md` -- verbatim design rationale for every BUILT
  product theme (A, A2, C, D, E, F1, K Pass 1, and all 11 numbered items of Theme J), preserving
  original heading text/labels so existing `BACKLOG Theme X` code comments still resolve. Theme L
  (Structural Hardening) is summarized here rather than duplicated, since `docs/build-log.md` is
  already its authoritative record.
- `BACKLOG.md` trimmed from 1,189 to ~240 lines: a new "Open / Not Yet Built" checklist at the top
  (Structural Hardening's 3 deferred follow-ons, Themes B/G/H, Theme K Pass 2, smaller deferred
  items, held Theme F4, the explicit not-planned database note), a "Built -- see design history"
  index table mapping each shipped theme to its new location, and the full text of everything
  still genuinely open (Theme B, Theme K Pass 2, Themes G/H/I, "Open items carried forward", the
  Theme L follow-on list, held Theme F4).
- **Corrected two stale statuses found during the move**: `wake missing-pdfs` (BACKLOG "deferred
  item A") and single-file `wake evidence --from-pdf` (BACKLOG "deferred item D.1") were both
  listed as not-yet-built in the original BACKLOG text, but their modules (`wake/missing_pdfs.py`,
  `wake/pdf_verify.py`), CLI wiring, and tests already existed -- confirmed by direct inspection
  before writing the history entry. Marked BUILT in the history doc; only the genuinely unbuilt
  batch variant (`wake evidence --from-pdf-dir`) and `wake assess` remain in BACKLOG's open list.

**README updates:** top-level `README.md`'s documentation table and `docs/README.md`'s index both
gained rows for `docs/build-log.md` and `docs/design/backlog-built-history.md`, and the `BACKLOG.md`
row description was corrected to reflect its new, narrower scope.

### Verification

`ruff check wake/ tests/` and `mypy` clean (no code touched); full offline suite
(`pytest tests/ -m 'not network'`) still 790 passed, 14 deselected -- confirms no test reads these
markdown files as data. Anchor-resolution grep (above) confirms every cited BACKLOG/PLAN anchor
resolves in its new location.

---

## v0.4.14 — Fix `test_openai_client.py` false pass in credential-free environments (`fix/openai-client-test-creds`)

The first real GitHub Actions CI run on this repo (triggered by the v0.4.13 docs-reorg merge)
surfaced 7 test failures that had never appeared locally: every test in `test_openai_client.py`
that calls `chat_json` directly (mocking only `_stream_completion` or the low-level
`openai.resources.chat.completions.Completions.create`) failed with `openai.OpenAIError: Missing
credentials`, not the mocked/asserted behavior.

Root cause: `chat_json`/`chat_text` call `_client()`, which constructs a real `openai.OpenAI()`.
The `OpenAI` client validates credentials (`OPENAI_API_KEY` or equivalent) at *construction* time,
before any request is made -- so even though every one of these 7 tests mocks the actual network
call, `_client()` itself raises first. This had passed silently in every prior local/sandbox run
purely because those environments happened to have a real `OPENAI_API_KEY` set (e.g. this
project's own dev sandbox, configured against the Argo gateway) -- CI correctly has no such
credentials configured, which is what exposed the gap. No other test file in the suite has this
problem: every other module exercising the LLM path mocks `wake.<module>.chat_json` itself (one
level higher than `_client()`), never reaching `OpenAI()`'s constructor at all.

Fixed with a single `autouse=True` pytest fixture in `tests/test_openai_client.py`
(`_fake_openai_credentials`) that sets `OPENAI_API_KEY` to a fake value via `monkeypatch.setenv`
for every test in the module -- `OpenAI()` only *validates the value is present* at construction,
it doesn't validate the key is real, so a fake value is sufficient and no real request is ever
made (every test already mocks the network layer below construction). Same pattern
`tests/test_config.py` already uses (`_clear_all_env` autouse fixture) for the inverse case
(guaranteeing a clean env-var slate).

Verified locally by reproducing the CI failure exactly:
`env -u OPENAI_API_KEY -u OPENAI_BASE_URL -u OPENAI_API_BASE pytest tests/test_openai_client.py`
failed the same 7 tests before the fix, passed all 23 after. Full offline suite re-run the same
way (`env -u OPENAI_API_KEY ... pytest tests/ -m 'not network'`): 790 passed, 14 deselected --
matching the pre-existing count exactly, confirming this is a test-only fix with zero production
code changes. `ruff`/`mypy` clean.

---

## v0.4.15 — Audit remaining `_normalize_*`/legacy-shape functions (`docs/normalize-audit`)

Discharges the Structural Hardening follow-on tracked since the migration story closed
(v0.4.12's summary, above) as "formalize the remaining `_normalize_*`/legacy-shape functions
using the migration-chain pattern" -- the next item both `PLAN.md`'s "Current Plan" and
`BACKLOG.md`'s "Open / Not Yet Built" nominated. Docs-and-docstrings-only, no behavior change.

The premise going in was that this would mirror the five-family migration work: find each
remaining `_normalize_*`/`_legacy_*` function and convert it to a `migrate_*()` step. That
premise didn't survive contact with the actual functions. `rg -n 'def _normalize_|def
_legacy|def migrate_|_VERSION\s*='` against `wake/` found ~15 candidates, sorted into three
categories, written up in full in the new `docs/design/normalize-audit.md`:

- **Category 1 (8 functions)** -- `_normalize_doi` (six near-identical copies across
  `wake/sources/*.py`), `_normalize_openalex_id`, `_normalize_for_match`. Pure input
  normalization on external API/user strings, unrelated to schema versioning. Out of scope;
  no action. (The six-way `_normalize_doi` duplication is a real DRY wart, but a refactor
  concern, not a migration one -- noted in the audit doc, not fixed here.)

- **Category 2 (3 rename families, already formalized)** -- the `.classify/`->`classify/`,
  `.overrides.jsonl`->`overrides.jsonl`, and `.manual_abstracts.jsonl`->`manual_abstracts.jsonl`
  dotfile renames. These are filesystem-location changes, not shape changes, so they were
  correctly built outside `models.py`'s pattern: a `_migrate_legacy_*_if_needed()` invoked from
  each family's write path (rename in place, no-op if already migrated or nothing to migrate),
  plus a read-only fallback in the load path. Verified the write-migrates/read-falls-back
  invariant holds for all three by tracing call sites. No action.

- **Category 3 (2 functions, the real judgment call)** -- `classify._normalize_relationships`
  and `evidence._normalize_proposed_relationships`, both of which synthesize a multi-facet
  `relationships` list from a pre-multi-facet sidecar/dossier's legacy scalar fields. These
  looked most like the five-family pattern but aren't: they run at build/render time on a
  sub-block (not a whole persisted file at the load boundary), sometimes on data that was never
  persisted at all (a classify result fresh from the LLM); folding the classify-side one into
  `migrate_classification_result` would force a `relationships` key onto `ClassifiedFile.works[]`
  entries that the model deliberately allows to have no such key (error/unclassified entries);
  and the two functions aren't symmetric -- only the dossier-side one carries quotes, so they
  can't collapse into a single step either. Determination: legitimately not schema migrations,
  correctly implemented as plain read-compat view-derivers. Action taken: clarified both
  docstrings to state this explicitly and point to the audit doc, so a future reader doesn't
  re-raise the same question without the context to answer it.

Net result: **no schema migrations were missing.** The original assessment's count ("~15
implicit `_normalize_*`/legacy-shape checks," this file's migration-story-complete summary
above) is confirmed accurate, and every one is now on record as either out of scope, already
formalized via the right mechanism for its kind, or intentionally not a migration.

### Verification

`rtk ruff check wake/ tests/` clean, `rtk mypy` clean. Full offline suite under CI-parity
conditions (`env -u OPENAI_API_KEY -u OPENAI_BASE_URL -u OPENAI_API_BASE pytest tests/ -m 'not
network'`): 790 passed, 14 deselected -- unchanged, as expected for a docs/docstring-only change.

### Next phase

`PLAN.md`/`BACKLOG.md` updated: this item is closed. Remaining Structural Hardening follow-ons
(unchanged) are full `WakeContext` threading through the ~90 `base:`-taking domain functions, and
a persisted dirty/revision manifest for `wake rebuild`.

---

## v0.4.16 — Make rendering an explicit `wake rebuild` step (`refactor/explicit-render`)

Phase 1 of the rebuild-manifest work (BACKLOG's persisted dirty/revision manifest item):
removed every write-time side-effect render from wake's JSON-mutating commands, so `wake
rebuild` is now the *only* place any derived Markdown gets (re-)written. This was a
prerequisite the user identified directly: a manifest that shows "what changed since the last
render" is only meaningful once rendering is a distinct, explicit act -- with commands still
auto-rendering inline, a manifest would mostly report "nothing changed" because every write
already re-rendered its own effects.

### What changed

Removed inline render calls (dossier `.md`, `evidence/index.md`, `evidence/themes/index.md`,
theme/section/outline `.md`, README.md/AGENTS.md orientation) from every write path that had
one: `evidence.build_dossier`, `report.add_override`, `unverify.unverify_work`,
`themes.create_theme`/`confirm_theme`, `narrative.create_outline`/`create_section`/
`confirm_section`. Each now writes only its JSON sidecar (plus, where applicable, an
append-only `log.md` line -- logging is not rendering and correctly stays inline) and returns
`"rebuild_needed": True`. `report.bake_and_save`/`narrative.stitch` remain explicit render
verbs for `impact.md`/`narrative.md` (that is their whole purpose) but no longer additionally
refresh README.md/AGENTS.md as a side effect -- `wake rebuild` calls both plus
`rebuild_wiki_orientation` as separate, explicit steps, exactly as it already did.
`build.py::rebuild_seed()` itself is unchanged in mechanism; its module docstring is rewritten
to describe itself as *the* render step rather than a recovery tool for piecemeal-rendering
gaps, since those gaps no longer exist -- there is nothing left to be piecemeal about.

Two now-dead code paths were removed outright rather than left as unreachable: `themes.py`'s
`_rerender_dossiers_for()` and `narrative.py`'s `_rerender_dependents()`, both write-time
render-trigger helpers with no remaining callers. The render *functions* they used to call
(`rerender_dossier_md`, `rerender_all_themes`, `rebuild_index`, etc.) are untouched and remain
reachable via `rebuild_seed()` and their own standalone `--rerender-all`/`rerender-all` verbs.

### Correctness fixes surfaced by the removal

Three real bugs, not just test churn, fell out of making rendering explicit -- each was a
place that checked a dossier's `.md` existence (as a proxy for "has this work been evidenced")
when it should have checked the JSON sidecar, since a dossier now legitimately has JSON with no
`.md` yet between a write and the next `wake rebuild`:

1. `narrative._check_packet_consistency()` refused to draft a section citing a
   just-verified work, because it checked `dossier_path(...).exists()` (the `.md`) instead of
   `dossier_json_path(...).exists()`.
2. `narrative._render_refs_in_section_prose()` and `report.bake_markdown()`'s "Strongest
   Evidence" title-linking both had the same `.md`-existence check controlling whether to emit
   a link -- fixed to check the JSON sidecar; the emitted link still points at the eventual
   `.md` filename, which resolves once rendered.
3. `evidence_wiki.append_log_entry()`'s dossier-link decision (whether to render `[id](id.md)`
   or plain text in `log.md`) had the same issue -- a dossier logged in the same call that
   built it would never get a link. Fixed to check the JSON sidecar.

A fourth, pre-existing gap (not a bug, but tightened as part of this pass): `mark_pending()`'s
`reason` argument (`wake unverify --reason "..."`) was patched directly into the dossier's
already-rendered `.md` via a string replace, never persisted to JSON -- meaning a from-JSON
`rerender_dossier_md()` call would silently drop it. Added `EvidenceDossier.pending_reason`
(a new optional field; the model is `extra="allow"` so no version bump needed),
`mark_pending()`/`mark_verified()` set/clear it, and `_render_dossier_markdown()` renders it
from JSON like every other field. This closes the one case flagged in the normalize-audit
(v0.4.15) as a "render depends on non-persisted in-memory state" finding.

### CLI-facing changes

Every affected command's human output gained a one-line `Run \`wake rebuild <seed>\`...` hint;
`--json` output gained `"rebuild_needed": true`. The four `... show` commands that print an
already-rendered `.md` (`theme show`, `narrative outline show`, `narrative section show`,
`show dossier`) now distinguish "never created" (point at the `create` command) from "created
but not yet rendered" (point at `wake rebuild`) by checking JSON vs. `.md` existence, instead
of a single generic "run X first" message that would have been actively misleading once JSON
and `.md` can legitimately diverge.

### Docs

`build.py`'s module docstring rewritten (recovery-tool framing -> the render step). SKILL.md:
fixed every "automatically updates/regenerates ... no separate step needed" claim (the
`wake override`/`wake evidence`/README.md-AGENTS.md-regeneration passages), added a `rebuild`
to the primitives list, a new "Rendering the Wiki" section explaining the JSON-now/render-later
model, and a 14th agent principle. `references/evidence.md`, `references/themes.md`,
`references/narrative.md`, `references/output-layout.md` (the agent-facing mirrors): same
audit and fix, including the theme/dossier "Referenced By" cross-link sections and the
`.md`+`.json` pair convention writeup. `docs/workflow.md` (new "Rendering the Wiki" section,
Quick Start now includes a `wake rebuild` call), `docs/evidence.md`, `docs/themes.md`,
`docs/narrative.md` (human-facing mirrors): same fixes.

### Verification

`rtk ruff check wake/ tests/` clean, `rtk mypy` clean. Full offline suite under CI-parity
conditions (`env -u OPENAI_API_KEY -u OPENAI_BASE_URL -u OPENAI_API_BASE pytest tests/ -m 'not
network'`): 790 passed, 14 deselected -- unchanged count; this phase restructured many existing
tests (adding explicit `rerender_dossier_md`/`rerender_all_themes`/`rerender_all_sections`/
`rebuild_index`/`rebuild_themes_index`/`rebuild_wiki_orientation`/`rebuild_seed` calls where a
test needed to read a `.md` that a write no longer renders inline) but did not add or remove
any test cases net. The `test_wiki_invariants.py::_build_full_wiki` fixture -- shared by
`test_build.py` and `test_wiki_invariants.py` -- now ends with a `rebuild_seed()` call instead
of a bare `rebuild_wiki_orientation()`, matching what a real agent session would do after the
same sequence of CLI calls.

### Next phase

Phase 2 (deferred to a future session): the persisted dirty/revision manifest itself, now that
rendering is a distinct act for it to report a diff against. Scope per the user's framing: the
manifest records what changed *between* renders (a diff/report), not an incremental-skip
optimization of `rebuild_seed()` -- `rebuild_seed()` continues to unconditionally re-render
everything; the manifest is additive, not a behavior change to the render path itself.

## v0.4.17 — Persisted rebuild manifest (`feature/rebuild-manifest`)

Phase 2 of the Structural Hardening follow-on above: the manifest itself. Per the user's framing
("I couldn't care less if things are always in sync ... I think the manifest is more about
showing what has changed from one rendering to the next"), this is a report of what changed on
the *input* side (the JSON render sources) since the previous `wake rebuild` call -- not an
incremental-skip optimization. `rebuild_seed()` still unconditionally re-renders every artifact
type on every call; the manifest never gates or skips a step.

### What was built

`models.RebuildManifest` (+ `RebuildManifestWrite`, `MANIFEST_VERSION = 1`, `migrate_manifest()`),
following the same schema-version/migration convention as every other artifact family in this
module. Persisted at `wake-out/<seed>/rebuild-manifest.json`: `{schema_version, rendered_at,
sources: {<source-key>: <sha256>}}`.

`build.py` gained `_collect_source_hashes()` (hashes every JSON file that currently feeds a
render for this seed -- `seed.json`, `citing.json`, `classified.json`, `overrides.jsonl`, every
`evidence/<id>.json` dossier, every `evidence/themes/<slug>.json` theme, `narrative/outline.json`,
every `narrative/sections/<slug>.json` -- keyed by a stable path-like string relative to the
seed's work dir; rendered `.md`/index output is never hashed) and `_diff_and_write_manifest()`
(loads the prior manifest if any, diffs current vs. prior hashes into added/changed/removed sets,
writes the refreshed manifest, and returns the report). `rebuild_seed()` calls the latter once,
after every render step, and adds the result under a new `"changes"` key in its return dict:
`{first_render, previous_render, added, changed, removed}`. `narrative/refs.json` and
`refs-results.json` (ref-checker scratch files) were confirmed to feed no renderer and are
deliberately excluded from the source set.

`wake rebuild`'s CLI human output (`run_rebuild` in `cli/commands/report.py`) now prints a
compact summary after the per-step list: "First render — N sources tracked." on a packet's first
ever rebuild, "No source changes since `<iso>`." when nothing changed, or an
Added/Changed/Removed breakdown (with source-key lists) otherwise. `--json` output passes the
full `"changes"` block through unchanged; `emit()` needed no changes.

### Docs

`build.py`'s module + `rebuild_seed()` docstrings extended to describe the manifest and its
report-only guarantee. `references/output-layout.md` gained a `rebuild-manifest.json` entry.
SKILL.md's "Rendering the Wiki" section gained a paragraph on the `changes` block.
`docs/workflow.md`'s "Rendering the Wiki" section, same addition. `wake rebuild`'s `--help` text
mentions the manifest. `PLAN.md`/`BACKLOG.md`: this closes the second of the two remaining
Structural Hardening follow-ons (only `WakeContext` threading remains open).

### Verification

New `tests/test_rebuild_manifest.py` (13 tests): first-render reports all current sources as
added and writes the manifest; a no-op second rebuild reports nothing changed; editing a dossier
JSON is reported `changed`; deleting a theme JSON is reported `removed`; adding a new dossier
between rebuilds is reported `added`; hand-editing a rendered `.md` (not its JSON) never shows up
in any diff (confirms outputs are never hashed); a legacy manifest with no `schema_version` key
round-trips through `migrate_manifest()` without breaking `rebuild_seed()`; every artifact type
still re-renders even when the manifest reports zero source changes (confirms report-only, not
incremental); CLI `--json`/human-output coverage for both first-render and no-change paths.
`rtk ruff check wake/ tests/` clean, `rtk mypy` clean. Full offline suite under CI-parity
conditions: 803 passed, 14 deselected (790 prior baseline + 13 new tests, no regressions).

## v0.4.18 — Theme K Pass 2: wire seed-PDF consumers (`feature/seed-pdf-consumers`)

Theme K Pass 1 (v0.4.x, acquire and cache the seed paper's own PDF at `seed.pdf`/`seed.pdf.json`)
shipped with explicitly no downstream consumers. This closes Pass 2 for the two LLM consumers and
documents the third (agent-driven, no code needed).

### What was built

New shared reader `seed_pdf.load_seed_excerpt(seed_id, *, base, max_chars) -> str | None`: reads
`seed.json`'s `seed_pdf.extracted_text_path`, loads the page-tagged extraction cache, joins via
`extract_full_text_from_pages`, truncates to `max_chars`. Returns `None` (never raises) for every
"no seed PDF text yet" case -- no `seed_pdf` key, a failed fetch attempt (`extracted_text_path:
null`), a cache file missing from disk, or a scanned PDF whose extraction produced only blank
pages. Both consumers below treat `None` as "fall back to today's behavior," so a seed with no PDF
acquired yet is completely unaffected.

**`wake describe`** (`describe.describe_seed`): the user prompt now appends a "Seed paper excerpt"
block (only when `load_seed_excerpt` returns something) alongside the existing title/authors/year/
venue/abstract fields -- the abstract alone routinely undersells a paper's actual contribution.
New config `describe.seed_excerpt_chars` (default 6000 -- enough for an intro + contribution
section). `describe.prompt_version` bumped `describe-1` -> `describe-2` so cached descriptions
regenerate.

**`wake evidence`** (`evidence.verify_full_text`): same excerpt block prepended to the user message
before the citing work's full text, framed as "ground truth for what the seed actually
contributes" -- lets the model check a claimed "extends"/"builds-on"/"benchmarks" relationship
against what the seed paper really did, not just its title. New system prompt `_SYSTEM_EVIDENCE_3`
(evidence-2's multi-facet shape, patched with one added instruction about the excerpt) registered
in `_SYSTEM_BY_VERSION`. New config `evidence.seed_excerpt_chars` (default 4000 -- supporting
context alongside the 40k-char citing full text, not the star of the prompt).
`evidence.prompt_version` default bumped `evidence-1` -> `evidence-3`, which also modernizes the
packaged default off the legacy single-facet prompt onto the multi-facet one.

**`wake narrative section create`** -- documentation-only, as scoped: SKILL.md,
`references/narrative.md`, and `docs/narrative.md` now note that `[ref:SEED]`-marked sentences
should be grounded in `seed.pdf` directly (open it as a plain file) rather than the abstract alone.
No code change -- the agent already had everything needed, it just wasn't written down.

`wake narrative section audit` (the fourth Pass-2 item from BACKLOG.md) remains a wholly separate,
still-unbuilt deferred item (a claim-vs-dossier semantic check) -- explicitly out of scope here.

### Verification

New tests: `tests/test_describe.py` (4, new file -- no prior describe tests existed): abstract-only
fallback with no seed PDF, excerpt included when available, `seed_excerpt_chars` cap respected,
fallback when extraction produced no text. `tests/test_seed_fetch_pdf.py` (+7):
`load_seed_excerpt`'s five fallback-to-None cases (no seed.json, no `seed_pdf` key, failed fetch,
missing cache file, blank-page extraction) plus the present/truncated-text cases.
`tests/test_evidence.py` (+4): excerpt included/omitted in `verify_full_text`'s user message,
char-cap respected, `_SYSTEM_EVIDENCE_3` mentions the seed excerpt.

`rtk ruff check wake/ tests/` clean, `rtk mypy` clean. Full offline suite under CI-parity
conditions: 818 passed, 14 deselected (803 prior baseline + 15 new, no regressions). Confirmed the
`evidence-1`/`evidence-2`/`describe-1` prompt-version default bumps didn't destabilize existing
tests -- every test that cares about a specific prompt version already patches `evidence_cfg`/
`describe_cfg` explicitly rather than relying on the packaged default.

### Next phase

Full `WakeContext` threading (the one remaining Structural Hardening follow-on) stays deliberately
deferred -- confirmed via a fresh audit this session that `WakeContext.settings`/
`.llm_client_factory` still have zero real consumers, so threading it now would be pure mechanical
churn (~137 `base:`-taking function signatures across 19 files) with no realized payoff. Next
candidates are product features: Theme B/G/H, or smaller carried-forward items like `wake assess`/
`theme coverage` evidence-gap triage.

## v0.4.19 — `wake assess`: evidence-gap triage report (`feature/assess`)

Closes the "smaller deferred item" from BACKLOG.md: before this, deciding which provisional
citing works to spend a `wake fetch-pdf`/`wake evidence` call on required an agent to read
`classified.json` directly (the only complete provisional set -- `impact.json`'s `top_evidence`
is truncated to `top_evidence_n`), stat the `evidence/` directory per work (dossier existence is
not surfaced by any read command), read every theme's own JSON sidecar for membership, and
re-derive the relationship-strength × log(citations) ranking formula from config rather than
reusing `report._score()`. `wake theme queue`/`wake missing-pdfs`/`wake gaps` each cover one slice
of this but none combine them, and none report the complete unranked set of works.

### What was built

`report.build_assessment(seed_work, base) -> dict`: the single join, reusing existing primitives
rather than re-deriving any of them --
`themes._resolve_work_status()` for honest per-work status (`verified`/`proposed`/`provisional`,
derived from `overrides.jsonl` and dossier existence, never the classify-time-stale
`verification_status` field), `report._score()`/`relationship_strength()` for the ranking score
(also exposed as `score_inputs` so an agent can re-rank by its own criteria instead), and the same
PDF-fetch-log derivation `missing_pdfs.list_missing_pdfs()` uses (cached/never-attempted/exhausted/
fetched-but-gone), applied here to every classified work rather than only the ones missing a PDF.
Returns `{seed, totals, themes, works, triage}`:
- `totals` -- aggregate counts (classified/verified/proposed/provisional/unclassified/error/
  excluded/duplicate).
- `themes` -- per-theme evidence coverage (verified/proposed/provisional/unclassified member
  counts) plus `member_ids`, from glob-scanning `evidence/themes/*.json` (same pattern as
  `report.bake_markdown`'s existing theme-count scan).
- `works` -- every classified work (not truncated), each with relationship/confidence/citations,
  status, `has_dossier`, `author_overlap` (reported only -- does not affect `score`, matching
  `impact.json`'s existing ranking), theme membership (reverse-indexed from the theme scan),
  `score`/`score_inputs`, and a `pdf` block. A work whose classify call errored (no `relationship`
  key) is included with `status: null` and its `error` message, counted in `totals.error`, and
  excluded from `triage`.
- `triage` -- the opinionated shortcut: provisional (not excluded, not a confirmed duplicate)
  `openalex_id`s, score-descending. `works` remains the complete, unranked truth for an agent that
  wants to re-sort by different criteria.

`wake assess <seed> [--top N]` (`wake/cli/commands/assess.py`), registered in `cli/main.py`
alongside `gaps`/`missing-pdfs`. Read-only, no LLM/network call, same trust model as `wake gaps`/
`wake missing-pdfs`/`wake theme queue` -- never mutates classify/evidence/theme state. Human output:
coverage line, a per-theme table (flagging themes with zero verified members), and the top
`--top` (default 15) triage entries with score/relationship/citations/PDF state/theme tags; the
full ranked list is always present under `--json`.

SKILL.md: new Step 12 ("Triage what's worth verifying next"), inserted between baking (11) and
deep-dive verification (renumbered 12->13); the vague "reserve it for works where the narrative
genuinely hinges on getting the relationship right" language in the deep-dive step now points at
`wake assess`'s `data.triage` instead. Steps 13/14/15 renumbered from 13/14/15... (14/15/16); two
"step 12" cross-references fixed to "step 13". `docs/workflow.md`'s command table gained a
`wake assess` row.

### Verification

New `tests/test_assess.py` (9): empty-classified baseline; mixed verified/proposed/provisional/
errored states (totals + per-work status + triage membership/ordering); score parity against
`report._score()` directly (guards against the ranking formula drifting between `build_metrics`
and `build_assessment`); excluded/duplicate flags present but excluded from `triage`; all four PDF
fetch-state variants (cached/never-attempted/exhausted/fetched-but-gone); theme membership
reverse-index across two themes plus per-theme coverage counts; CLI `--json` envelope and human
output (including the no-provisional-works and populated-triage-worklist paths).

`rtk ruff check wake/ tests/` clean, `rtk mypy` clean. Full offline suite under CI-parity
conditions: 827 passed, 14 deselected (818 prior baseline + 9 new, no regressions).

### Next phase

No further follow-on identified for this item -- it was a self-contained read-only report. Open
roadmap items remain: full `WakeContext` threading (deliberately deferred, no realized payoff),
Theme B (DOE-relevance signals, explicitly wanted by the user for their own use case), Theme G
(timeline generation), Theme H (non-publication evidence search), and `wake narrative section
audit` (claim-vs-dossier semantic check for `[ref:...]`-marked sentences).

## v0.4.20 — Theme G: Timeline curation (`feature/timeline`)

Originally scoped in BACKLOG.md as a lower-complexity, `report.py`-adjacent renderer: a Markdown
timeline of key developments derived non-interactively from classified works' years + relationship
strength. Mid-design, the user reframed the goal directly: the consumer of this feature is an agent
and human iterating together in conversation, not a batch report -- wake's job is to hand over the
material for that iteration, not to pre-decide what's a "key development." A further reframing
during the same discussion mapped the unit of iteration onto periods of time with curated
highlights, exactly like narrative sections: "the user/agent team are selecting from the material we
have what should belong. timeline.md would be the working artifact of that, like narrative.md is."
The shipped design follows from that framing, not the original BACKLOG scope.

### What was built

Rebuilt on the same "candidate material -> curated units -> stitch" pattern as `wake theme`/`wake
narrative`, not a one-shot metrics aggregate:

**Candidates** (`wake timeline candidates`, `timeline.build_candidates()`) -- read-only, complete,
scored/dated view of every classified work, bucketed by year (default) or an N-year window
(`--bucket-years`). Reuses `report._score()`/`report.relationship_score()` directly for scoring --
never a second, drifted ranking formula. Same full resolution `wake assess`/`wake bake` use
(overrides applied for verification status, confirmed duplicates flagged, exclusions flagged, never
silently hidden). Deliberately never pre-selects "the milestones" or filters weak relationships by
default -- `--min-strength`/`--since`/`--until` are query-time conveniences the agent varies in
conversation, not a persisted decision; the editorial threshold for what counts as a "key
development" stays between the agent and the human, not baked into a config default.

**Periods** (`wake timeline period create`/`confirm`, new `wake/timeline.py`) -- a period is either
an emergent single-year bucket (a bare year slug, e.g. `2012`, with `from_year`/`to_year` defaulted
to that year) or a named span the team defines up front (e.g. `early-adoption` with explicit
`--from`/`--to`) -- both are the same `TimelinePeriod` JSON shape (new models: `TimelinePeriod`,
`TimelineHighlight`, `TimelinePeriodWrite`, `TIMELINE_PERIOD_VERSION`, `migrate_period()`), so
neither mode needed a separate outline step (the user's explicit scope call: "First cut: candidates
feed + period create/confirm + stitch, no separate outline"). Each highlight carries both a
per-highlight note and the period carries its own framing note (the user's choice: "Both: a
per-highlight note + a period-level note"). `create_period()` validates every highlight is
classified and not excluded/a confirmed duplicate (same bar `wake theme create` enforces) and always
writes `draft`. `confirm_period()` refuses unless every highlighted work is *currently*
human-verified, re-resolved fresh at confirm time (not from the period's own possibly-stale JSON) --
the user's explicit choice: "Require highlighted works be verified (like theme confirm)" -- a
confirmed period is an evidentiary claim about what mattered at that point in the story, not merely
an agent's classification guess. Periods may overlap or leave year gaps; that's the team's editorial
call, reported (`stitch()`'s `overlaps`) but never enforced or auto-corrected.

**Stitch** (`wake timeline stitch`) -- assembles every period (chronological by `from_year`) into
two files with different audiences: `timeline.md` (the working, human-readable artifact showing
every period confirmed-or-draft, clearly labeled -- like `narrative.md`) and `timeline.json` (the
**CONFIRMED periods only** -- the handoff to a separate Tufte-style graphic-rendering tool, per the
user's explicit choice: "The confirmed selection... not the full candidate pool"). Works on partial
data, same philosophy as `wake bake`/`narrative.stitch`.

**Wiring:** new `wake/cli/commands/timeline.py` (`candidates`/`period create`/`period confirm`/
`period show`/`stitch`/`show`, nested like `wake narrative`), registered in `cli/main.py`.
`build.py::rebuild_seed()` gained a `timeline_periods`/`timeline` step (re-renders period `.md`s,
re-stitches) between `narrative` and `impact`; `_collect_source_hashes()` tracks
`timeline/periods/*.json` as new render-input sources (rendered outputs `timeline.md`/`.json` are
never hashed, consistent with the manifest's input-only design). `evidence_wiki.py`'s
README/AGENTS.md orientation and `report.bake_markdown()`'s impact.md "See also" nav both gained a
`[timeline](timeline.md)` link, conditional on `timeline.md` existing.

### Documentation

New `wake/skills/impact-analysis/references/timeline.md` (mirrors `themes.md`/`narrative.md`'s
structure). SKILL.md gained Step 16 ("Curate a timeline of key developments," between narrative and
Refine, which renumbered to Step 17) plus updates to "Rendering the Wiki"'s command/source lists and
the frontmatter description. `references/reference.md`'s Full Command List and reference-file index,
`references/output-layout.md`'s directory tree, `docs/workflow.md`'s command table, `BACKLOG.md`
(Theme G moved from Deferred to Built, index table row), `PLAN.md`.

### Verification

New `tests/test_timeline.py` (35): `build_candidates` bucketing (per-year and N-year windows),
no-pre-selection/`min_strength`-filtering/`since`-`until` behavior, undated/errored-work exclusion,
override/exclusion/duplicate flag reporting, score-descending ordering within a bucket;
`create_period` validation (empty/invalid-slug/unclassified/excluded/confirmed-duplicate
highlights), bare-year vs. named-span defaulting, highlight status/notes, overwrite-preserves-
created_at; `confirm_period` blocking on unverified highlights and re-resolving fresh after a later
override; `stitch` chronological ordering, confirmed-vs-draft counts, confirmed-only `timeline.json`,
overlap reporting, frontmatter; `rerender_all_periods`; CLI `--json`/human paths for every verb.
Extended `tests/test_wiki_invariants.py`'s shared `_build_full_wiki` fixture with one confirmed
timeline period and asserted the rendered wiki's README/AGENTS/impact.md timeline links and
`timeline.json`'s confirmed-only shape; registered `timeline`/`timeline-period` frontmatter types in
`tests/wiki_invariants.py`'s `KNOWN_TYPES`/`REQUIRED_KEYS_BY_TYPE`. Updated
`tests/test_build.py::test_cli_rebuild_json_output`'s expected step-name set to include
`timeline_periods`/`timeline`.

`rtk ruff check wake/ tests/` clean, `rtk mypy` clean. Full offline suite under CI-parity
conditions: 862 passed, 14 deselected (827 prior baseline + 35 new, no regressions).

### Next phase

Open roadmap items: full `WakeContext` threading (deliberately deferred, no realized payoff),
Theme B (DOE-relevance signals, explicitly wanted by the user for their own use case), Theme H
(non-publication evidence search), and `wake narrative section audit` (claim-vs-dossier semantic
check for `[ref:...]`-marked sentences). No further follow-on identified specifically for Theme G --
a second phase (e.g. an outline-equivalent step for planning periods up front, or folding in
`--with-doe-signals`-style domain enrichment) could be revisited once the first cut has been used on
a real seed.

## v0.4.21 — CiTO-alignment relationship taxonomy refactor (`refactor/predicate-taxonomy`)

Prompted by the user reviewing wake's seven relationship classes against
[CiTO](https://sparontologies.github.io/cito/current/cito.html) (the Citation Typing Ontology) with an
eye toward aligning wake's predicate naming/semantics with CiTO's where a real correspondence exists
-- not adopting CiTO wholesale (most of CiTO's ~40 citation sub-properties have no bibliometric-impact
use case wake needs, and most of wake's classes have no CiTO equivalent: domain transfer and baseline
benchmarking aren't citation types CiTO models). Mid-discussion the user also caught a genuine
pre-existing ambiguity: `builds-on` ("builds a new system that depends on the seed") and `uses-as-tool`
("uses the seed's software/tool/dataset as-is") overlapped in practice -- a paper building something
new on top of the seed's method both "uses" it and "depends on" it. Resolved by merging `builds-on`
into an expanded `uses-method-from` rather than trying to sharpen an already-blurry boundary with more
prompt prose (the user's explicit call).

### What changed

Net effect: **seven labels, same count, four renamed/merged, three now with exact CiTO matches** (up
from one, `extends`, before this refactor):

| Old | New | Nearest CiTO |
|---|---|---|
| `extends` | `extends` (unchanged) | `cito:extends` (exact) |
| `uses-as-tool` **+** `builds-on` | `uses-method-from` | `cito:usesMethodIn` (exact) |
| *(new split from `uses-as-tool`)* | `uses-data-from` | `cito:usesDataFrom` (exact) |
| `applies-to-domain` | `applies-to-domain` (unchanged) | `cito:usesMethodIn` (domain-transfer sub-case) |
| `benchmarks` | `benchmarks` (unchanged) | `cito:citesAsPotentialSolution` (weak -- CiTO has no dedicated baseline-comparison property) |
| `related-infrastructure` | `related` | `cito:citesAsRelated` |
| `background-mention` | `cites` | `cito:cites` (exact -- CiTO's own root "cites, unspecified" property) |

`extends` vs. `uses-method-from` is now stated explicitly as a boundary in every prompt: `extends`
changes the seed's own method; `uses-method-from` uses it unchanged, whether applied as-is or
incorporated as a dependency of something new. `related` vs. `cites` is likewise explicit: `related` is
an affirmative "these are adjacent" judgment; `cites` is the true fallback for when nothing more
specific is determinable -- mirroring CiTO's own `citesAsRelated`/`cites` split. `author_overlap`
(orthogonal boolean tag, not a relationship class) is unchanged; its CiTO analogue
(`cito:AuthorSelfCitation`/`sharesAuthorWith`) was already noted in docs and needed no code change.

Default strengths were reset by the user directly (not derived from the old scale), reflecting a
deliberate editorial choice to weight domain transfer above even `extends`:
`applies-to-domain` (7) > `uses-method-from` (6) = `uses-data-from` (6) > `extends` (5) >
`benchmarks` (3) > `related` (2) > `cites` (1). Still fully overridable per-project via
`classify.relationship_strength` in `wake.config.yaml`, unchanged mechanism.

No `cito:` IRI is emitted anywhere in code or output artifacts -- the correspondence is documentation
only (a table in `references/classify.md`/`docs/workflow.md`), a deliberate scope-narrowing the user
made explicit after initially considering a machine-readable mapping: with no external consumer of
such a mapping, it would be dead code carried for its own sake.

### What was built

**`wake/vocabulary.py`** (single source of truth): `CANONICAL_RELATIONSHIPS`/`RelationshipLabel`
updated to the new seven; added `RETIRED_RELATIONSHIPS` (`uses-as-tool`/`builds-on` ->
`uses-method-from`, `related-infrastructure` -> `related`, `background-mention` -> `cites`), consumed
only by migration, never by classify/evidence/scoring.

**Migrations** (`wake/models.py`): every retired label is rewritten forward on read, with no
re-classification required. `migrate_classification_result`/`migrate_classified` remap the
`relationship` scalar and every `relationships[]` facet's `label` (`CLASSIFICATION_VERSION`/
`CLASSIFIED_FILE_VERSION` 1 -> 2); `migrate_dossier` remaps `provisional`/`proposed` the same way
(`EVIDENCE_DOSSIER_VERSION` 2 -> 3); `migrate_override` remaps a retired `relationship`
(`OVERRIDE_VERSION` 1 -> 2). All four migrations are idempotent and covered by new tests. Also fixed a
latent bug surfaced by the version bump: `evidence.py`'s dossier writer hardcoded
`"schema_version": 2` instead of importing `EVIDENCE_DOSSIER_VERSION` -- newly written dossiers would
have silently stayed one version behind every future bump.

**Prompts** (`wake/classify.py`'s `classify-2`/`classify-3`, `wake/evidence.py`'s
`evidence-1`/`evidence-2`/`evidence-3`): all five system prompts rewritten to the new seven labels with
the `extends`/`uses-method-from` and `related`/`cites` boundary notes spelled out verbatim, since the
label set is fixed in code precisely because these prompts must spell out every label as prose (not
config-driven). Every hardcoded fallback site (`background-mention` used when nothing else applies)
changed to `cites` across `classify.py`, `evidence.py`, `report.py`, `evidence_wiki.py`, `timeline.py`.

**Config** (`wake/config.yaml`): `classify.relationship_strength` default block and its documentation
comment updated to the new seven keys and values.

**Docs**: `references/classify.md` (full taxonomy table with CiTO column, `extends`/`related`
boundary notes, new "CiTO Correspondence" section explaining the scope decision), `references/
evidence.md`, `references/timeline.md`, `references/exclude.md`, `SKILL.md`, `docs/workflow.md`
(taxonomy table + CiTO column), `README.md`, `PLAN.md` (also fixed a pre-existing staleness: the
ranking section listed only six labels with weights that didn't match `config.yaml`'s actual seven).

### Verification

Golden-packet fixture (`tests/fixtures/golden-packet/`) predates this refactor and was **not**
hand-edited, consistent with how it already predates every prior schema-version bump (Phase 6/9/10/11/
12's dossier/theme/narrative/classification/override versioning) -- `test_golden_packet.py`'s two
label-validating tests (`test_all_classify_sidecars_validate_as_classification_result`,
`test_classified_json_works_validate`) now migrate the raw fixture JSON forward before validating
against the current `RelationshipLabel` Literal, and `test_dossier_schema_version_persisted_on_disk`
now documents and asserts the fixture is frozen at the pre-refactor `EVIDENCE_DOSSIER_VERSION=2` rather
than asserting the current version, mirroring the existing `..._is_unversioned_pre_phase_N_and_migrates_
on_read` acceptance-test pattern used for every earlier schema bump. New coverage: retired-label remap
in all four migrations (`test_models.py`), the new label set's strength defaults and ordering, the
`extends`/`uses-method-from` and `related`/`cites` boundaries via updated prompt-adjacent tests, and a
mechanical relabel of every fixture/assertion across ~20 other test files that used a retired label
name without testing the taxonomy itself.

`rtk ruff check wake/ tests/` clean, `rtk mypy` clean. Full offline suite under CI-parity conditions:
862 passed, 14 deselected (no count change -- a taxonomy rename/merge, not new functionality).

### Next phase

No functional change to wake's behavior beyond the label rename/merge and default-strength reset --
purely a naming/taxonomy clarity refactor made possible by wake having exactly one user at the time.
Open roadmap items unchanged: Theme B (DOE-relevance signals), Theme H (non-publication evidence
search), `wake narrative section audit`, full `WakeContext` threading (still deliberately deferred).

## v0.4.22 — `classify-4` prompt enrichment + title-only short-circuit (`feature/classify-4-enrichment`)

Motivated by a live-data investigation against the PVFS packet (843 citing works,
`wake-out/W2110298485/`) recorded in `PLAN.md`: `classify-2` (the packaged default since v0.1) only
ever saw the seed's *title* plus the citing work's title/year/venue/abstract -- it didn't know what the
seed paper actually contributes, just pattern-matched on its title. 62% of classified works landed in
the `cites` fallback (89% among the ~22% of works OpenAlex left abstract-less), mean confidence 0.61.

### What was built

**Part A -- `classify-4` prompt** (`wake/classify.py`): a single-facet successor to `classify-2` (NOT
`classify-3` -- `classify-3`'s multi-facet schema has never been a packaged default and this change
deliberately doesn't flip it on as a side effect). `_SYSTEM_CLASSIFY_4`/`_USER_TEMPLATE_4` add the
seed's own abstract (always present post-resolve), the seed's `wake describe` contribution paragraph
when one exists (degrades cleanly to abstract-only otherwise, capped at 1500 chars), and the citing
work's `topics`. `author_overlap` deliberately excluded from the prompt -- stays a post-hoc tag only.
`classify.prompt_version` packaged default bumped `classify-2` -> `classify-4` in `wake/config.yaml`
(invalidates every existing packet's classify sidecars, same as any prior prompt-version bump).

**Part B -- title-only deterministic short-circuit** (`wake/classify.py::classify_all`): a citing work
that still has no abstract after backfill (Primo/OSTI/Semantic Scholar all missed) gets a deterministic
`cites` classification with **no LLM call**, tagged `low_signal: true` -- gated on new
`classify.title_only_shortcircuit` (default `true`) and `classify.title_only_relationship` (default
`"cites"`, overridable). Based on the same investigation: 89% of PVFS's title/venue-only works were
LLM-classified `cites` anyway, mostly reproducing the prompt's own fallback instruction. The
short-circuited sidecar carries the same `has_abstract`/`verification_status`/`prompt_version`/`model`/
`classified_at` fields as an LLM result, so it's cached and resumable identically. `wake.models`'s
`ClassificationResult`/`ClassificationResultWrite` gained a `low_signal: bool = False` field.

**Part C -- `low_signal` surfaced in the brief** (`wake/report.py`): `build_metrics` counts
`low_signal_count`, carries `low_signal` through `top_evidence` entries, and `bake_markdown` adds a
"Reach" coverage line ("N of M citing works were title/venue-only after backfill and not
LLM-classified") when the count is nonzero -- distinct from the pre-existing `no_abstract_count` line,
so a short-circuited work is never confused with one the LLM actually judged `cites`.

**Part D -- skill guidance** (`wake/skills/impact-analysis/SKILL.md`,
`references/classify.md`): new "Run `wake describe` first" and "Title-only short-circuit" sections in
`classify.md`; step 4 of `SKILL.md`'s sequence now recommends `wake describe` before the first
`classify` call on a new seed. Soft guidance only -- not auto-triggered, no stage dependency added.

### Verification

`ruff check wake/ tests/` clean, `mypy` clean. Full offline suite: 939 passed, 15 deselected (up from
862 in v0.4.21 -- new coverage for classify-4's prompt/template dispatch, the seed-description
present/absent/author_overlap-exclusion cases, the short-circuit's deterministic output and
no-LLM-call guarantee, its config-flag opt-out, cache/resume behavior, and `low_signal` propagation
through `build_metrics`/`bake_markdown`/`top_evidence`).

### Explicitly not in this pass (see `PLAN.md`'s "Explicitly not in this plan" for the full list)

`classify-3`'s multi-facet schema was not adopted; no per-difficulty model routing; no in-text citation
context integration; no auto-triggering of `wake describe`; no confidence calibration or evaluation
harness. All separate, larger ideas, deliberately scoped out.

### Next phase

Product features next: Theme B (DOE-relevance signals), Theme H (non-publication evidence search). See
`BACKLOG.md`'s "Open / Not Yet Built" section for current sequencing. A live spot-check re-run of `wake
classify --force` against the PVFS packet (to confirm the coverage/confidence shift the investigation
predicted) remains a natural follow-up but wasn't required to close this pass -- the offline suite is
green and the change is behavior-verified there.

## v0.4.23 — `classify-4` description-only + required, non-destructive re-resolve (`feature/classify-4-description-only`)

Motivated by a live A/B run of v0.4.22's `classify-4` against the PVFS packet (843 citing works,
comparison baseline preserved at `wake-out-classify-2/W2110298485/`). Two problems surfaced mid-run:

1. **`resolve_and_cache` silently destroyed seed enrichment on re-resolve.** The PVFS classify-4 run was
   set up by hand-copying `seed.json`/`seed.pdf`/`seed.pdf.json`/`citing.json` into a fresh work-dir
   without also seeding `.state.json`'s `seed`/`citing` stage-completion entries. Because
   `is_stage_current()` saw no recorded `seed` stage, the next `wake classify` call silently re-resolved
   the seed from OpenAlex and overwrote `seed.json` wholesale -- the fresh resolve has `abstract` but not
   `description`/`described_at`/`seed_pdf` (only ever written by `wake describe`/`wake fetch-pdf`, never
   re-derived by `resolve`). The classify-4 run completed successfully (839/843 classified) with an
   **empty seed-description block** for all 839 calls -- no error, no warning, silently degraded to
   abstract-only.
2. **classify-4's abstract+optional-description shape was the wrong call.** `wake describe`'s description
   is generated from the abstract *plus* an excerpt of the seed's own extracted PDF full text (confirmed
   live: the PVFS seed's `describe-2` output paragraph reflects details present only in the PDF body, not
   the abstract) -- so the description strictly dominates the abstract as seed-side context. Sending both
   was redundant on the common path and silently downgraded on the uncommon one with no signal to the
   operator.

### What was built

**Part A -- classify-4 description-only** (`wake/classify.py`): `_SYSTEM_CLASSIFY_4` rewritten to tell the
model it's given a description of the seed's contribution (no mention of an abstract); `_USER_TEMPLATE_4`
no longer has a `Seed abstract:` line -- the description is the sole, always-present seed-side context
block; `_build_classify4_user_msg` drops the `seed_abstract` parameter and asserts the description is
non-empty (belt-and-suspenders backstop; Part B is the real enforcement point). Mutated classify-4 in
place (not a new `classify-5`) -- the existing PVFS classify-4 sidecars (abstract+topics-only) are
superseded and were preserved as a frozen snapshot at `wake-out-classify-4-abstractonly/W2110298485/`
before this change, specifically so that data point isn't lost.

**Part B -- fail-fast requirement** (`wake/classify.py::classify_all`): raises `ValueError` immediately,
before the resume-cache loop and before any LLM calls, if `prompt_version == "classify-4"` and the seed
has no description ("classify-4 requires a seed description. Run `wake describe <seed>` first, then
re-run classify."). `cli/commands/classify.py::run_classify` now wraps the `classify_all` call in
`try/except ValueError` and routes through `emit_error` (that command previously had no error handling at
all -- any exception propagated as a raw traceback). One upfront failure instead of every one of
potentially hundreds of citing works failing identically. `classify-2`/`classify-3` are unaffected.

**Part C -- non-destructive re-resolve** (`wake/seed.py::resolve_and_cache`): new
`_SEED_ENRICHMENT_FIELDS` (`abstract_source`, `description`, `described_at`, `seed_pdf`,
`primo_pdf_url` -- the authoritative set per `models.Work`'s "Enrichment fields" list, minus
`resolved_at`, which a genuine resolve always freshly sets). Any re-resolve that falls through the
`is_stage_current` fast path now merges these forward from the existing on-disk `seed.json` (if present)
into the freshly-resolved payload, rather than overwriting wholesale. Core bibliographic fields (title,
authors, abstract, etc.) still always reflect the fresh resolve. Root-cause fix, not classify-4-specific
-- protects `wake describe`/`wake fetch-pdf` output for every stage and every packet.

**Part D -- docs**: `references/classify.md`'s "Run `wake describe` first" section rewritten as "`wake
describe` is required before `wake classify`"; documents that abstract-only judgment (`classify` stage,
`models.classify`) vs. full-text-grounded judgment against the citing paper's own PDF (`evidence` stage,
`models.evidence`) are already two independently configurable model roles -- no new model-role config
surface was added, since the "abstract-only vs. with-PDF-text" distinction the investigation raised maps
onto that existing stage split, not a new setting inside `classify` (which has no citing-PDF-text code
path at all). `SKILL.md` step 4 updated to run `wake describe` unconditionally, not as an optional
consideration. `config.yaml` gained a comment on `models:` documenting the classify/evidence division of
labor.

### Verification

`ruff check wake/ tests/` clean, `mypy` clean. Full offline suite: 944 passed, 15 deselected (up from 939
in v0.4.22 -- new coverage for classify-4's description-only/required behavior, the
`classify_all`/`_build_classify4_user_msg` fail-fast paths, and `resolve_and_cache`'s non-destructive
merge). Several pre-existing tests that called `classify_one`/`classify_all` with the shared
`PARALLEL_NETCDF_WORK` fixture (which has no `description`) and no explicit `prompt_version` pin were
updated to pin `classify-2` explicitly, since they test behavior orthogonal to which prompt version is
active and the packaged default is now classify-4.

### Not in this pass

No new model-role config surface (existing `classify`/`evidence` split covers the abstract-only vs.
full-text distinction); no `classify-5` (mutated classify-4 in place, by explicit choice); no
auto-triggering of `wake describe` from `classify` (hard failure with an actionable message instead); no
full re-run of the PVFS 843-work comparison (see "Next phase" below).

### Next phase

Post-merge validation was a small sanity sample, not a full second A/B run: `wake describe` regenerated
the live PVFS packet's description (safe now under Part C), then `wake classify --limit 20 --sort
cited-by` under the new description-only classify-4. A full 843-work description-only comparison against
the two preserved snapshots (`wake-out-classify-2/`, `wake-out-classify-4-abstractonly/`) remains a
natural follow-up but is not required to close this pass. Product features next: Theme B (DOE-relevance
signals), Theme H (non-publication evidence search).

## v0.4.24 — packaged `classify` model default switched to Claude Haiku 4.5 (`feature/classify-haiku-default`)

Closes the full 843-work description-only comparison flagged as a natural follow-up at the end of v0.4.23
(above), reframed as a model comparison rather than a second prompt-shape comparison: the classify-4
prompt itself is unchanged.

### Investigation

A live A/B run of the (unchanged) classify-4 prompt against the PVFS packet (843 citing works,
`W2110298485`), swapping only `models.classify` from Claude Sonnet 4.6 to Claude Haiku 4.5 via a local
`wake.config.yaml` override (no code touched for the experiment itself):

- **Completion**: Haiku classified all 843/843 with **0 errors**, vs. Sonnet's 839/843 (4 errors) on the
  equivalent abstract-only classify-4 run preserved at `wake-out-classify-4-abstractonly/W2110298485/`.
- **Speed**: mean per-call wall time 2.83s (Haiku) vs. 7.67s (Sonnet) across the classify stage's
  `.cost.jsonl` records -- roughly 2.7x faster overall, closer to 3x once the fixed 0.5s inter-call delay
  common to both runs is backed out.
- **Label distribution**: the two runs diverge sharply on the two most common labels -- Haiku:
  `related` 535 (63.5%), `cites` 134 (15.9%); Sonnet: `cites` 573 (68.3%), `related` 127 (15.1%). Per-work
  diff (843 shared IDs, excluding both-`low_signal` short-circuits): 35.1% exact-label agreement overall,
  but 72% of Sonnet's `cites` works (398/550) were relabeled `related` by Haiku specifically -- reading
  the paired justification text for a sample showed near-identical reasoning ("same ecosystem, no direct
  dependency") resolved to different labels, not a comprehension gap. `extends` and `benchmarks` fared
  better at ~48-50% direct overlap. Haiku's mean confidence was +0.19 higher than Sonnet's on matched
  works.
- **Cost**: comparable input-token cost per call (1276 vs. 1303 mean in-tokens, same prompt/seed
  description); Haiku produced longer justifications on average (99 vs. 74 mean out-tokens). Neither
  model has a `cost.rates_per_1k_usd` entry, so no live-$ comparison was possible.

Full run artifacts and analysis preserved outside this repo at `/workspaces/wake-pvfs/haiku-root/` and
`/workspaces/wake-pvfs/HAIKU-COMPARISON.md`.

### Decision

Adopt Haiku 4.5 as the packaged `classify` default. The `cites`/`related` divergence was accepted
deliberately rather than treated as a regression: `classify` output is always `verification_status:
"provisional"` (see `classify.py`'s docstring on the provisional -> proposed -> verified lifecycle), and
the boundary between the two labels is genuinely ambiguous from an abstract alone -- `related`'s own
definition ("complementary work or infrastructure in the same ecosystem... an affirmative 'these are
related' judgment") is arguably satisfiable by most of the works landing in `cites`'s fallback bucket
("no more specific relationship... including unclear/indirect/merely contextual mentions"). The 2.7-3x
latency win and cleaner completion rate were judged to outweigh a label shift that only affects a
provisional, not-yet-human-reviewed field. `describe`, `pdf_abstract_extract`, and `evidence` all remain
on Sonnet 4.6, unchanged -- `evidence` in particular is the stage that reads full citing-work PDF text and
produces the non-provisional `proposed`/`verified` finding, where judgment quality matters most and
nothing in this investigation touched that stage.

### What was built

Config-only change, no prompt/behavior code touched:

- `wake/config.yaml` -- `models.classify: "Claude Sonnet 4.6"` -> `"Claude Haiku 4.5"`. Comment block
  above `models:` extended to document the split and point at this entry's evidence.
- `wake/config.py::init_local` -- the starter `wake.config.yaml` written by `wake config init` updated to
  match (`classify: "Claude Haiku 4.5"`; `describe` stays Sonnet 4.6).
- `README.md` -- sample `wake.config.yaml` and a new sentence explaining the split.

**Cache consequence** (same class of effect as any prior classify prompt-version bump): classify sidecars
are cache-keyed on `model` (see `classify.py`'s `_load_sidecar`/`classify_all` checks), so this
invalidates every existing packet's classify sidecars -- the next `wake classify` run against any packet
re-classifies from scratch under Haiku.

**Not changed**: no code in `classify.py` (prompt, parsing, short-circuit logic all untouched); no new
model-role config surface; `wake/__init__.py`'s stale `__version__ = "0.1.0"` left as-is (tracked
separately in `BACKLOG.md`'s "Open items carried forward"); no Haiku entry added to
`cost.rates_per_1k_usd` (real rates not available at time of this change -- both Sonnet and Haiku report
`unpriced: true` today).

### Verification

`ruff check wake/ tests/` clean, `mypy` clean, full offline suite green (`pytest tests/ -m 'not network'`)
-- no test asserts `classify`'s default model specifically; `test_config.py`'s two model-name regression
guards (`test_show_reflects_correct_model_defaults`, `test_init_local_writes_consistent_model_name`) only
assert that `"Claude Sonnet 4.6"` appears somewhere and `"4.7"` does not, both still true since
`describe`/`pdf_abstract_extract`/`evidence` remain on Sonnet 4.6.

## v0.4.25 — `__version__` derived from package metadata, no longer a stale hardcoded literal (`fix/version-from-metadata`)

Closes the `wake/__init__.py`'s `__version__` staleness item from `BACKLOG.md`'s "Open items carried
forward" (moved to this file's "Built" index): `__version__` had been hardcoded `"0.1.0"` since the
project's first commit and never bumped despite ~24 documented `v0.4.x` releases in this file.
`state.py::mark_stage_complete` stamps this constant into every packet's `.state.json` as `tool_version`
(both top-level and per-stage), so that field was useless as a provenance/era signal -- confirmed live
during the v0.4.23 PVFS session, where `tool_version: "0.1.0"` on a classify-2 sidecar nearly caused a
wrong inference about whether the packet predated the v0.4.21 CiTO taxonomy refactor.

### What was built

- `pyproject.toml` -- `version = "0.1.0"` -> `"0.4.24"`, matching the actual most-recently-shipped
  build-log entry at the time of this fix. This is now the single source of truth for wake's version.
- `wake/__init__.py` -- `__version__` is no longer a literal. It's read via
  `importlib.metadata.version("wake")` at import time, so it always reflects whatever `pyproject.toml`
  says for however wake was actually installed (`pip install -e .`, a built wheel, etc.) -- one number to
  keep in sync per release, not two files that can silently disagree. Falls back to the obviously-
  placeholder `"0.0.0+unknown"` (never a fabricated real-looking version) if `PackageNotFoundError` is
  raised -- e.g. wake's source directory is on `PYTHONPATH` without ever having been `pip install`ed.
- `tests/test_version.py` (new) -- asserts `wake.__version__` equals `importlib.metadata.version("wake")`
  directly (not just "looks like a version string"), asserts it's no longer the stale `"0.1.0"` literal
  (regression guard for the specific bug), and asserts the `PackageNotFoundError` fallback path returns
  `"0.0.0+unknown"` via a monkeypatched `importlib.metadata.version`.

### Explicitly not changed

- The golden-packet fixture's frozen `.state.json`/sidecar files still say `"tool_version": "0.1.0"` --
  correct to leave as-is, since that's a historical snapshot of what a real past run actually recorded,
  not something that should retroactively reflect the current version.
- No change to `state.py::mark_stage_complete`'s use of `tool_version` -- it still stamps `__version__`
  into every packet exactly as before; the fix is that the value stamped is now trustworthy.
- Per-stage `prompt_version`/`model` fields (already the more reliable provenance signal per the
  original BACKLOG note) are unchanged -- this fix makes `tool_version` usable too, rather than replacing
  it with those fields.
- Future releases must still remember to bump `pyproject.toml`'s `version` by hand -- this fix removes
  the *two-files-can-disagree* failure mode, not the need for a human to bump the number at all. No
  automated release-versioning tooling (e.g. setuptools-scm) was introduced; out of scope for this pass.

### Verification

`ruff check wake/ tests/` clean, `mypy` clean, full offline suite green (`pytest tests/ -m 'not network'`,
947 passed / 15 deselected -- 3 new from `test_version.py`, no regressions). Live-checked
`python -c "import wake; print(wake.__version__)"` after `pip install -e .` prints `0.4.24`, matching
`pyproject.toml`.
