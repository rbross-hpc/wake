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

Relationship strengths (default, highest to lowest — configurable via
`classify.relationship_strength` in `wake.config.yaml`):
  applies-to-domain (7) > uses-method-from (6) = uses-data-from (6) >
  extends (5) > benchmarks (3) > related (2) > cites (1)

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

v0.4.15 closed the remaining item from that follow-on: an audit of every
`_normalize_*`/legacy-shape function found none actually missing a
migration — see
[`docs/design/normalize-audit.md`](docs/design/normalize-audit.md) for
the full determination.

v0.4.16 was Phase 1 of the persisted dirty/revision manifest item:
rendering became a single explicit step (`wake rebuild`), not a
write-time side effect of `wake evidence`/`override`/`unverify`/`theme
create`/`confirm`/`narrative outline create`/`section create`/`confirm`
— a prerequisite for a manifest that reports what changed *between*
renders, per the user's framing (a diff/report, not an incremental-skip
optimization).

v0.4.17 closed Phase 2, the manifest itself: `wake rebuild` now persists
a sha256-per-JSON-source `rebuild-manifest.json` and reports a
`changes` block (added/changed/removed sources since the previous
rebuild) in its return value and human/`--json` output.
`rebuild_seed()` remains fully unconditional — the manifest is
report-only, never a gate. This closes the second of the two remaining
Structural Hardening follow-ons.

v0.4.18 built Theme K Pass 2 (wire seed-PDF consumers): `wake describe`
and `wake evidence` both now include an excerpt of the seed paper's own
extracted PDF text (via new shared `seed_pdf.load_seed_excerpt()`) as
context, falling back cleanly to abstract-only when no seed PDF text
exists. `describe-2`/`evidence-3` prompt versions. `wake narrative
section create` got a documentation-only note (open `seed.pdf` directly
for `[ref:SEED]` sentences); `wake narrative section audit` remains
separately deferred.

Full `WakeContext` threading through the ~137 existing `base:`-taking
domain functions remains the one open Structural Hardening follow-on,
deliberately not prioritized: `WakeContext.settings`/`.llm_client_factory`
have zero real consumers today, so threading it now would be pure
mechanical churn with no realized payoff — see `BACKLOG.md`'s "Theme L
follow-on" section. Revisit only if a concrete driver appears (hermetic
LLM-client injection for tests, or multi-config embedding).

v0.4.19 built `wake assess`: a read-only evidence-gap triage report
(`report.build_assessment()`) joining classified.json, override/dossier
status (via `themes._resolve_work_status()`), theme membership, and PDF
fetch state into one per-work document, plus a `triage` worklist ranked
by the same `report._score()` formula `impact.md` already uses. Closes
the highest-leverage remaining carried-forward item — previously an
agent had to read `classified.json` directly, stat `evidence/`, and
re-derive the ranking formula from config by hand.

v0.4.20 built Theme G (`wake timeline`): re-scoped mid-design from a
one-shot `report.py`-style metrics renderer to the same "candidate
material -> curated units -> stitch" pattern as `wake theme`/`wake
narrative`, once framed around who actually uses it -- an agent and
human choosing together what belongs on the timeline and how to
periodize it, not wake computing a timeline on its own. `wake timeline
candidates` is a read-only, complete, scored/dated/bucketed feed (never
pre-selecting a "top N"); `period create`/`confirm` curate one period
(bare-year or named span) at a time, confirming only once every
highlighted work is human-verified; `stitch` produces `timeline.md` (the
working artifact, all periods) and `timeline.json` (confirmed periods
only -- the handoff to a separate graphic-rendering tool). Wired into
`wake rebuild` and the rebuild manifest.

v0.4.22 built the `classify-4` prompt enrichment + title-only
short-circuit plan below: the packaged classify default now includes the
seed's own abstract/description and the citing work's topics, and a
citing work with no abstract after backfill gets a deterministic `cites`
short-circuit (no LLM call, tagged `low_signal`) rather than a call that
mostly reproduces the prompt's own fallback instruction. Full account in
`docs/build-log.md`'s "v0.4.22" entry; the design record below (kept
as-is for that context) predates the build.

A live A/B run of classify-4 against the PVFS packet (843 citing works)
surfaced two real follow-on items, tracked in the new plan section below
("classify-4: description-only + required, non-destructive re-resolve"):
(1) `resolve_and_cache` silently overwrites `seed.json` on any re-resolve
that races ahead of a stale/missing `.state.json` seed-stage entry,
destroying `description`/`seed_pdf` enrichment with no warning -- caught
live when a classify-4 run turned out to have run abstract-only, not
description-enriched, with no error; (2) classify-4's seed abstract +
optional description was, on reflection, the wrong shape -- the
PDF-grounded `wake describe` description is strictly more informative
than the abstract, so classify-4 should use it exclusively and require
it, not silently degrade.

v0.4.23 built the `classify-4` description-only + required,
non-destructive re-resolve plan below: classify-4 now uses the seed's
`wake describe` contribution paragraph exclusively (no seed abstract
line) and requires it -- `classify_all` fails fast, before any LLM
calls, if the seed has none. `resolve_and_cache` no longer silently
destroys `description`/`seed_pdf` enrichment on a re-resolve. Full
account in `docs/build-log.md`'s "v0.4.23" entry; the design record
below (kept as-is for that context) predates the build.

**Next phase:** product features — Theme B (DOE-relevance signals),
Theme H (non-publication evidence search). See `BACKLOG.md`'s "Open /
Not Yet Built" section for current sequencing.

**Deferred, real, not forgotten:**
- Product features: Theme B (DOE-relevance signals), Theme H
  (non-publication evidence search).

---

## Next: `classify-4` prompt enrichment + title-only short-circuit

**Status: built, v0.4.22** (see `docs/build-log.md`'s "v0.4.22" entry for
what actually shipped). Design record kept below as-is. Motivated by a
live-data investigation
against the PVFS packet (843 citing works, `wake-out/W2110298485/`):
`classify-2` (the packaged default since v0.1 — see "Investigation
findings" below) sees only the seed's *title* plus the citing work's
title/year/venue/abstract, nothing else. On that packet, 62% of
classified works land in the `cites` fallback (89% among the ~22% of
works OpenAlex left abstract-less), and mean confidence is 0.61 with
only 5% above 0.85. The classifier doesn't even know what the seed paper
*is* — it's pattern-matching on titles.

### Investigation findings (context for the design below)

- **`classify-3` (multi-facet, shipped opt-in per commit `9edd484 feat:
  multi-facet relationship classification (opt-in)`) has never actually
  been the default and has never run on real data as a default** — the
  packaged `classify.prompt_version` went `classify-1` → `classify-2`
  and has stayed at `classify-2` ever since. `classify-4` (below)
  deliberately extends `classify-2`'s single-facet schema, not
  `classify-3`'s, so this change doesn't simultaneously flip on an
  unexercised multi-facet behavior as a side effect of fixing the
  input-starvation problem.
- **The seed's own abstract and LLM-written `description` (from `wake
  describe`) already exist on disk in `seed.json` and are never passed
  to `classify_one`** — only `seed_work.get("title")`/`.get("year")` are
  read (`classify.py`'s `_USER_TEMPLATE`).
- **The citing work's `topics` field (e.g. `["Computer Science"]`) is
  already fetched and stored on every work dict but is dropped from the
  classify prompt.**
- **`author_overlap` is computed (`author_overlap.py::compute_overlap`)
  but only *after* classification**, as a tag on the result — never fed
  into the LLM's reasoning. Explicitly **excluded** from this plan by
  design choice (kept as a post-hoc tag, not a classification input).
- **There is no separate model setting for "title-only" vs. "abstract
  available" vs. "full PDF."** The four model roles
  (`describe`/`classify`/`pdf_abstract_extract`/`evidence`) map to
  pipeline *stages*, not input richness — `classify` is one flat model
  for every citing work regardless of how much signal it has. Real gap,
  not addressed by this plan (see "Not in this plan" below).
- **Of the 183 title/venue-only PVFS works, 163 (89%) were classified
  `cites`** — an LLM call that mostly reproduces the prompt's own
  fallback instruction ("if abstract missing, base decision on title and
  venue; set confidence <= 0.5") rather than adding signal. The other 20
  (11%) got a specific, plausible label from a self-describing title
  alone (e.g. *"pCFS vs. PVFS: Comparing a Highly-Available..."* →
  `benchmarks`, confidence 0.82) — so a blanket skip would lose real
  signal in a minority of cases, hence the short-circuit below is
  config-gated, not unconditional.
- **Primo abstract backfill (see `BACKLOG.md`'s Theme M) measurably
  shrinks the true title-only population first**: exercised directly
  against the PVFS packet's 186 abstract-less works, Primo alone
  recovered 163/186 (87.6%), lifting net abstract coverage from 77.9% to
  97.3% and leaving only ~23 works genuinely irrecoverable (DOI-less
  theses/reports, foreign-language publications, works no source
  indexes). The short-circuit below is meant to apply to that shrunken
  post-backfill remainder, not to the original ~20% OpenAlex gap.

### Part A — `classify-4` prompt enrichment (single-facet)

- `wake/classify.py`: add `_SYSTEM_CLASSIFY_4`, based on the single-label
  `_SYSTEM_CLASSIFY_2` (unchanged 7-label taxonomy and JSON response
  shape), revised to tell the model it will be given a description of
  the seed paper and to use it when distinguishing `uses-method-from` /
  `related` / `cites`. Add `_USER_TEMPLATE_4` including:
  - **Seed abstract** (`seed_work.get("abstract")`) — always present
    after `wake resolve`.
  - **Seed description** (`seed_work.get("description")`) — the LLM-
    written contribution paragraph from `wake describe`, included as an
    extra line when present, cleanly omitted when absent (describe is
    not auto-triggered — see Part C).
  - **Citing topics** (`", ".join(citing_work.get("topics") or [])`).
  - **No `author_overlap`** (explicit exclusion, see findings above).
  - Defensive truncation on the seed description to bound token growth
    (current per-call input is ~830 tokens; this roughly doubles it —
    report the actual delta once implemented).
  - Register `"classify-4"` in `_SYSTEM_BY_VERSION`; select the template
    by prompt version inside `classify_one`. `classify-2`/`classify-3`
    left fully intact (cache-compat; multi-facet stays opt-in/unused).
- `wake/config.yaml`: bump the packaged default
  `classify.prompt_version` from `"classify-2"` to `"classify-4"`.
  **Cache consequence**: `classify_all`'s resume-cache is keyed on
  `prompt_version` + `model` (see `classify.py`'s `_load_sidecar`
  checks), so this invalidates every existing packet's classify
  sidecars — the next `wake classify` run on any packet (including the
  PVFS one) re-classifies from scratch. This is the same behavior prior
  prompt-version bumps have always had; call it out explicitly to
  whoever runs the next classify pass rather than let it surprise them.

### Part B — Title-only deterministic `cites` short-circuit

- `wake/classify.py` (`classify_all`'s per-work loop): after
  `cw = backfill_mod.backfill_one(cw)` and before calling
  `classify_one`, if the work **still** has no abstract (i.e. Primo/
  OSTI/Semantic Scholar backfill all missed) and
  `classify.title_only_shortcircuit` is enabled, write a deterministic
  sidecar with **no LLM call**: `relationship: "cites"` (or
  `classify.title_only_relationship` if overridden), a low/zero
  confidence, an explicit justification string ("No abstract available
  after backfill; title/venue-only — not classified by LLM."), and a new
  provenance flag **`low_signal: true`**, alongside the normal
  `has_abstract: false` / `verification_status: "provisional"` /
  `prompt_version` / `model` / `classified_at` fields so it's cached,
  resumable, and rebuild-compatible identically to an LLM result. Count
  these separately (e.g. "N title-only short-circuited") in the run
  summary printed by `classify_all`.
- `wake/config.yaml`: new `classify.title_only_shortcircuit: true` (with
  `classify.title_only_relationship: "cites"` as the overridable
  target), so a run that wants the LLM to attempt self-describing titles
  anyway (recall: ~11% of PVFS's title-only works got a real signal from
  title alone) can disable the short-circuit per-packet.

### Part C — Surface `low_signal` in the brief

- `wake/report.py`: carry `low_signal` through into `impact.json`, and
  add a coverage line to `impact.md` (e.g. "N of 843 citing works were
  title/venue-only after backfill and not LLM-classified") so
  short-circuited works are visibly distinct from works the LLM actually
  judged to be `cites` — the brief should never blur "the model decided
  this is just a background mention" with "there was nothing to decide
  from."

### Part D — Skill guidance (encourage `describe` before `classify`)

- `wake/skills/impact-analysis/SKILL.md` and
  `references/classify.md`: add a recommendation to run `wake describe`
  before `wake classify` (not auto-triggered — a deliberate choice to
  avoid coupling classify to an extra LLM call and stage dependency) so
  `classify-4` usually has the richer seed description available, not
  just the abstract. Soft guidance, not enforced: classify-4 degrades
  cleanly to abstract-only when no description exists yet.

### Tests

- `tests/test_classify.py`: `_system_prompt("classify-4")` returns the
  new prompt; the classify-4 user template includes seed abstract +
  citing topics, includes the seed description line when present, omits
  it cleanly when absent (fresh-resolve case), and never includes
  `author_overlap` (regression guard for the explicit exclusion);
  `classify-2`/`classify-3` prompts and behavior unchanged.
- Short-circuit: a work with no abstract after backfill yields a
  deterministic `cites` + `low_signal: true` sidecar with `chat_json`
  asserted **not called**; a work with a (possibly backfilled) abstract
  still goes through the normal LLM path; the config flag
  (`title_only_shortcircuit: false`) restores the pre-change
  LLM-always-called behavior; the short-circuit sidecar is cached and
  resumable exactly like an LLM-produced one.
- `tests/test_report.py`: `impact.json` carries `low_signal`; `impact.md`
  renders the new coverage line with the correct count.
- Full existing offline suite green (`pytest tests/ -m 'not network'`).

### Verification

`ruff check wake/ tests/`, `mypy`, `pytest tests/ -m 'not network'`.
Optional live spot-check: re-run `wake classify --force` against the
PVFS packet and confirm (a) title-only works are flagged `low_signal`
with no LLM call, (b) the LLM-classified population drops from 843 to
roughly 820 (matching the ~23 post-Primo-backfill irrecoverable works
measured during investigation), and (c) mean confidence / `cites`-bucket
share move in the expected direction now that the seed abstract and
description inform every real classification.

### Explicitly not in this plan

- **classify-3's multi-facet schema is not adopted as part of this
  change** — `classify-4` stays single-facet. Multi-facet remains
  available, opt-in, and still unused by any packaged default.
- **`author_overlap` is not added to the classify prompt** — kept as a
  post-classification tag only, by explicit choice.
- **No auto-triggering of `wake describe`** from `classify` — encouraged
  via skill guidance only (Part D).
- **No per-difficulty model routing** (a cheaper model for title-only
  work, a stronger one for the ambiguous tail, etc.) — the `classify`
  model role stays a single flat setting; this would need new config
  surface and is a separate, larger idea, not scoped here.
- **In-text citation context** (e.g. Semantic Scholar's citing-sentence
  `contexts`/`intents`) is the highest-ceiling remaining idea for
  classification quality but is a genuinely new source integration, not
  a prompt-enrichment change — deliberately scoped out of this plan for
  a later pass.
- **Confidence calibration, few-shot exemplars, self-consistency
  ensembling for the low-confidence tail, and a systematic quality-
  evaluation harness** are all real ideas raised during the
  investigation but are separate follow-on work, not bundled here.

Explicitly **not** planned: replacing the filesystem-artifact model with
a database. Both the original external assessment and independent
review agree file-first is a real strength of wake's design, not a
symptom needing a fix.

---

## Next: `classify-4` description-only + required, non-destructive re-resolve

**Status: built, v0.4.23** (see `docs/build-log.md`'s "v0.4.23" entry for
what actually shipped). Design record kept below as-is. Motivated by a live A/B run of the
v0.4.22 `classify-4` prompt against the PVFS packet (843 citing works,
`wake-out/W2110298485/`, comparison baseline preserved at
`wake-out-classify-2/W2110298485/`). Two problems surfaced mid-run, one a
data-loss bug, one a prompt-design reconsideration:

1. **`resolve_and_cache` silently destroys seed enrichment on re-resolve.**
   The PVFS classify-4 run was set up by hand-copying `seed.json`/
   `seed.pdf`/`seed.pdf.json`/`citing.json` into a fresh work-dir without
   also seeding `.state.json`'s `seed`/`citing` stage-completion entries.
   Because `is_stage_current()` saw no recorded `seed` stage, `wake
   classify`'s call to `resolve_and_cache` silently re-resolved the seed
   from OpenAlex and **overwrote `seed.json` wholesale** — the fresh
   resolve has `abstract` (OpenAlex always returns that) but not
   `description`/`described_at`/`seed_pdf` (only ever written by `wake
   describe`/`wake fetch-pdf`, never re-derived by `resolve`). The
   resulting classify-4 run completed successfully (839/843 classified)
   but with an **empty seed-description block** for all 839 calls — no
   error, no warning, silently degraded to abstract-only. This is a real
   bug independent of the hand-copy scenario that surfaced it: any
   packet whose `.state.json` is missing, stale, or hasn't recorded the
   `seed` stage (a corrupted/partial `.state.json`, a packet built by an
   older wake version with a different stage-key convention, or any
   manual intervention in `wake-out/`) will silently lose `wake
   describe`/`wake fetch-pdf` work the next time anything triggers a
   re-resolve.
2. **classify-4's abstract+optional-description shape was the wrong
   call.** The seed's `wake describe` description (see `describe.py`,
   `describe-2`) is generated *from* the abstract **plus** an excerpt of
   the seed's own extracted PDF full text (up to
   `describe.seed_excerpt_chars`, default 6000 chars) — confirmed live on
   the PVFS seed: `describe-2`'s output paragraph reflects details (API
   names, benchmark specifics) present only in the PDF body, not the
   abstract. The description therefore strictly dominates the abstract as
   seed-side context; classify-4 sending both (abstract always, description
   only when present) is redundant on the common path and silently
   downgrades on the uncommon one (see item 1) with no signal to the
   operator that anything was lost.

### What changed from the original classify-4 design (already shipped, v0.4.22)

The original plan (previous section) had classify-4 send the seed
**abstract** unconditionally plus the seed **description** as an optional
extra line, and treated "no description yet" as an unremarkable,
silently-degraded case (soft `wake describe`-first guidance only, per
that plan's Part D). This next pass **replaces** that shape:
classify-4 will use the description **only** (no seed abstract line at
all) and will **require** it — a `wake classify` run under classify-4
against a seed with no description fails fast with a clear instruction,
rather than silently sending less context than intended.

### Part A — classify-4 prompt: description-only

- `wake/classify.py`:
  - `_SYSTEM_CLASSIFY_4`: rewrite the opening paragraph. Currently: "You
    will be given the seed paper's own abstract (and, when available, a
    short description of its contribution)...". New: the model is told
    it will be given the seed's **contribution description** (grounded in
    the paper's own PDF text, not just its abstract) — no mention of an
    abstract at all.
  - `_USER_TEMPLATE_4`: remove the `Seed abstract: {seed_abstract}` line
    entirely. The seed description becomes the sole, always-present
    seed-side context block (no longer a conditionally-appended extra
    line via `_SEED_DESCRIPTION_BLOCK`/`_SEED_DESCRIPTION_LINE`) — since
    it's now required (Part B), there's no "omit cleanly when absent"
    case to design for on the happy path. Citing-side fields (title/
    year/venue/topics/abstract) are unchanged.
  - `_build_classify4_user_msg`: drop the `seed_abstract` parameter/
    formatting; keep the existing `_SEED_DESCRIPTION_MAX_CHARS = 1500`
    truncation cap on the description. Add a defensive assertion (not a
    silent fallback) that `seed_work.get("description")` is non-empty —
    belt-and-suspenders under the Part B guard, which is the actual
    enforcement point.
  - Module docstring's classify-4 paragraph updated to describe it as
    description-only and description-required, not abstract+optional-
    description.
  - **This mutates classify-4 in place** (not a new `classify-5`) — the
    existing PVFS classify-4 sidecars (abstract+topics-only, no
    description) are superseded by this shape and will be re-classified
    from scratch the next time `wake classify` runs against that packet
    (same cache-invalidation mechanism as every prior prompt-version
    change; see `_load_sidecar`'s prompt_version+model check). The
    abstract-only run has already been preserved as a frozen snapshot at
    `wake-out-classify-4-abstractonly/W2110298485/` specifically so this
    in-place mutation doesn't lose that data point.

### Part B — Fail-fast requirement: classify-4 needs a seed description

- `wake/classify.py::classify_all`: add a check near the top of the
  function, before the resume-cache loop and before any LLM calls:
  if the active prompt version is `"classify-4"` and
  `seed_work.get("description")` is empty/missing, raise immediately
  with a clear, actionable message (e.g. "classify-4 requires a seed
  description; run `wake describe <seed>` first.") — one check, one
  error, zero wasted LLM calls, rather than 800+ identical per-work
  failures.
  - Exception type: match whatever convention `wake/errors.py` already
    uses for user-facing precondition failures (audit at implementation
    time — likely a dedicated exception class so `cli/commands/classify.py`
    can catch it and route through the existing `emit_error()` path for a
    clean CLI message instead of a raw traceback, consistent with how
    `SeedNotFound` is already handled in `_resolve_seed_to_work`).
  - Deliberately **no auto-triggering of `wake describe`** from
    `classify` — same "no implicit side-effects" principle as the
    original plan's Part D, just enforced as a hard error now instead of
    soft guidance. The workflow this produces: `wake classify` on a
    seed with no description fails with the instruction, the operator
    (or agent) runs `wake describe <seed>`, then re-runs `wake classify`
    — self-healing, and it surfaces exactly the problem that silently
    degraded the PVFS run in item 1 above, instead of hiding it.
  - `classify-2`/`classify-3` are unaffected — the requirement is
    specific to `prompt_version == "classify-4"`.

### Part C — Non-destructive re-resolve (root-cause fix for the clobber bug)

- `wake/seed.py::resolve_and_cache`: when re-writing `seed.json` (the
  `if not force and is_stage_current(...)` guard falls through to a
  fresh resolve — whether because of `--force`, a genuinely stale
  prompt_version, or a missing/incomplete `.state.json`), **merge-preserve**
  existing enrichment fields from the on-disk `seed.json` if one is
  already present, rather than replacing the whole file with a bare
  fresh `resolve()` result:
  - Preserved (carried forward from the existing file if the fresh
    resolve doesn't independently produce them): `description`,
    `described_at`, `seed_pdf`, `abstract_source`, and any other
    post-resolve enrichment field a later stage has written (audit
    `models.Work`'s "Enrichment fields, added post-creation" list at
    implementation time for the authoritative set).
  - Still overwritten by the fresh resolve: core bibliographic fields
    (`title`, `authors`, `author_ids`, `year`, `venue`, `venue_type`,
    `doi`, `url`, `cited_by_count`, `type`, `abstract`, `topics`,
    `oa_pdf_url`, `oa_status`) — a genuine re-resolve should still pick
    up upstream OpenAlex corrections/updates to these.
  - Audit every existing caller of `resolve_and_cache` (`wake resolve`,
    every command's `_resolve_seed_to_work` path) to confirm none
    depends on the current destructive-overwrite behavior (e.g. a test
    or workflow that intentionally re-resolves specifically *to* clear
    stale enrichment — if one exists, it needs an explicit `--force`-like
    opt-out for the merge, not a silent behavior change out from under
    it).
  - This is a root-cause fix, not scoped to the classify-4 interaction:
    it protects `wake describe`/`wake fetch-pdf` output for every stage
    and every packet, not just classify-4's new hard dependency on
    `description`.

### Part D — Docs

- `wake/skills/impact-analysis/references/classify.md` /
  `wake/skills/impact-analysis/SKILL.md`: update the classify-4
  description — it now uses the seed's PDF-grounded contribution
  description exclusively (not the abstract) and **requires** `wake
  describe` to have been run first; the "Run `wake describe` first"
  guidance shifts from *recommended* to *required* specifically for
  classify-4 (still not auto-triggered).
  - Also document, as a clarification (no behavior change): abstract-only
    relationship judgment is the `classify` stage's job
    (`models.classify`); full-text-grounded judgment against the
    *citing* paper's own PDF is the `evidence` stage's job
    (`models.evidence`) — these are already two independently
    configurable model roles today, so no new model-role config is
    needed to distinguish "abstract-only" from "with full text";
    the distinction is which *stage* is running, not a new setting.
- `wake/config.yaml`: add a short comment near `models.classify`/
  `models.evidence` documenting that division of labor, so a reader
  scanning the models block doesn't go looking for a `classify_full_text`
  key that doesn't exist.

### Tests

- `tests/test_classify.py`:
  - classify-4's user message no longer contains a `Seed abstract:` line
    (inverts the existing `test_classify_4_user_msg_includes_seed_abstract_and_topics`
    assertion) and always contains the seed description.
  - `classify_all` raises the fail-fast error when `prompt_version ==
    "classify-4"` and the seed has no description, with `chat_json`
    asserted **never called** (mirrors the existing dry-run/short-circuit
    "no LLM call" test pattern).
  - `classify_all` proceeds normally (LLM called, sidecars written) when
    a description is present.
  - `classify-2`/`classify-3` prompts/behavior unchanged (regression
    guard, same as the original classify-4 pass).
- A seed-resolve test (new or added to wherever `resolve_and_cache` is
  covered today): re-resolving a seed that already has `description`/
  `described_at`/`seed_pdf` on disk preserves all three, while core
  bibliographic fields still reflect the fresh resolve.

### Verification

`ruff check wake/ tests/`, `mypy`, `pytest tests/ -m 'not network'`.

Post-merge validation is deliberately **not** a full 843-work
re-classification of the PVFS packet (that already happened once for the
abstract-only shape and is preserved at
`wake-out-classify-4-abstractonly/`). Instead: `wake describe
W2110298485` to regenerate the live packet's description (safe now under
Part C's non-destructive resolve), then `wake classify W2110298485
--limit 20 --sort cited-by` as a small sanity sample under the new
description-only classify-4 — checked for a sane label distribution and
a couple of legible justifications, not a full second A/B run. A full
843-work description-only comparison against the two preserved
snapshots (`wake-out-classify-2/`, `wake-out-classify-4-abstractonly/`)
remains a natural follow-up but is explicitly not required to close this
pass.

### Explicitly not in this plan

- **No new model-role config surface** (e.g. no
  `models.classify_abstract_only` / `models.classify_full_text` split).
  The abstract-only vs. full-text-grounded judgment distinction already
  exists as the `classify` vs. `evidence` stage split, each with its own
  independently configurable model role — adding a parallel config knob
  inside `classify` alone would be redundant, since `classify` has no
  citing-work-PDF-text code path today (that's `evidence`'s job; see the
  original plan's "Investigation findings" for confirmation that
  `classify_one` only ever sees title/abstract/venue/topics, never
  citing full text).
- **No `classify-5`** — this mutates `classify-4` in place, by explicit
  choice, accepting the cache invalidation this causes (the
  abstract-only PVFS classify-4 sidecars are superseded, but preserved
  separately as a frozen snapshot rather than kept live).
- **No auto-triggering of `wake describe`** from `classify` — hard
  failure with an actionable message instead, per Part B.
- **No full re-run of the PVFS 843-work comparison** as part of this
  plan (see Verification above) — a small-sample sanity check only.
- Everything already out-of-scope in the original classify-4 plan above
  (multi-facet adoption, per-difficulty model routing beyond the
  classify/evidence split, citation-context integration, confidence
  calibration/eval harness) remains out of scope here too.
