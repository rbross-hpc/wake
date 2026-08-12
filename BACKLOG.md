# BACKLOG — wake

Open roadmap: deferred features, held designs, and not-yet-built items.
For the design rationale, lifecycle corrections, and live-validation
detail behind everything already **shipped**, see
[`docs/design/backlog-built-history.md`](docs/design/backlog-built-history.md)
(product themes) and [`docs/build-log.md`](docs/build-log.md)
(Structural Hardening / engineering work, Theme L). Existing code/test
comments citing `BACKLOG Theme X` or `BACKLOG deferred item N` refer to
sections in one of those two files, or below if still open — see the
"Built — see design history" index below for the mapping.

---

## Open / Not Yet Built

The current actionable list, roughly in order of what's most likely
next. See each linked section below for full detail.

**Structural Hardening follow-ons** (Theme L closed; two of three
original items closed, one remains):
1. ~~A persisted dirty/revision manifest for `wake rebuild`~~ —
   **closed** (v0.4.16 Phase 1: rendering is now a single explicit
   `wake rebuild` step, not a write-time side effect of `evidence`/
   `override`/`unverify`/`theme create`/`confirm`/`narrative outline
   create`/`section create`/`confirm`; v0.4.17 Phase 2: `wake rebuild`
   persists a sha256-per-JSON-source `rebuild-manifest.json` and reports
   a `changes` block — sources added/changed/removed since the previous
   rebuild — in its return value and CLI output. Report-only:
   `rebuild_seed()` still unconditionally re-renders everything on every
   call, per the user's framing).
2. Full `WakeContext` threading through the ~90 `base:`-taking domain
   functions. *(Next phase.)*

(Formalizing the remaining `_normalize_*`/legacy-shape functions was
closed by audit rather than by migration code — see
[`docs/design/normalize-audit.md`](docs/design/normalize-audit.md):
every candidate was already correctly handled or was never a schema
migration in the first place.)

**Product features, decided but not built:**
- Theme B — DOE-relevance signals (`signals_doe.py`, off-by-default).
- Theme H — Non-publication evidence search.

(Theme K Pass 2 — wire seed-PDF consumers — is now BUILT, v0.4.18. See
"Built — Theme K (Pass 2)" below. `wake assess`/evidence-gap triage is
now BUILT, v0.4.19 — see "Built — `wake assess`" below. Theme G —
timeline curation — is now BUILT, v0.4.20 — see "Built — Theme G" below.)

**Smaller deferred items** (see "Open items carried forward" below for
full detail): `wake evidence --from-pdf-dir` (batch variant), `wake
narrative section audit`, interactive review rendering polish, README
multi-harness skill-install docs, author-email discovery, `wake
fetch-pdf` negative-result caching, F2 (bullet-style narrative
sections), narrative packaging/export.

**Held — do not execute without a live walkthrough:**
- Theme F4 — two-phase theme workflow reframe (`theme declare`/`theme
  add`). Full design in
  [`docs/design/theme-workflow-reframe.md`](docs/design/theme-workflow-reframe.md).

**Not planned:** replacing the filesystem-artifact model with a database.

---

## Built — see design history

| Theme | What it is | Where the rationale lives |
|---|---|---|
| A | PDF acquisition (`wake fetch-pdf`) | [history](docs/design/backlog-built-history.md) — Theme A |
| A2 | Evidence deep-dive dossier (`wake evidence`) | [history](docs/design/backlog-built-history.md) — Theme A2 |
| C | Combined-evidence / thematic documents (`wake theme`) | [history](docs/design/backlog-built-history.md) — Theme C |
| D | OKF evidence wiki (organization layer) | [history](docs/design/backlog-built-history.md) — Theme D |
| E | Author-overlap tag | [history](docs/design/backlog-built-history.md) — Theme E |
| F1 | Narrative drafting (`wake narrative`) | [history](docs/design/backlog-built-history.md) — Theme F1 |
| K (Pass 1) | Seed paper PDF acquisition | [history](docs/design/backlog-built-history.md) — Theme K |
| K (Pass 2) | Wire seed-PDF consumers (`describe`/`evidence`/`narrative`) | this file — "Built — Theme K (Pass 2)", v0.4.18 |
| — | Evidence-gap triage report (`wake assess`) | this file — "Built — `wake assess`", v0.4.19 |
| G | Timeline curation (`wake timeline`) | this file — "Built — Theme G", v0.4.20 |
| J | Session-notes batch (11 items: dotfile rename, docs split, `show` verbs, help-text audit, README split, `refs-check`, `dedup`, `posters`, `exclude`, `unverify`) | [history](docs/design/backlog-built-history.md) — Theme J |
| L | Structural Hardening (13 phases, v0.4.0–v0.4.12) | [build log](docs/build-log.md), summarized in [history](docs/design/backlog-built-history.md) — Theme L |
| M | Primo abstract/DOI/PDF-URL backfill (opt-in institutional discovery-layer source) | this file — "Built — Theme M", `feature/primo-abstract-backfill` + `feature/oa-pdf-url-capture` |
| — | `classify-4` prompt enrichment + title-only short-circuit | [build log](docs/build-log.md) — v0.4.22, design record in `PLAN.md` |

---

## Theme B — DOE-Relevance Signals — DEFERRED, explicitly decoupled from A2

Mid-session design discussion: Theme A2 is fully general-purpose and
contains zero domain-specific logic. Theme B (author affiliation strings,
DOE compute-resource acknowledgments, funding language, OSTI cross-check)
was explicitly identified by the user as something *they* want for their
own use case, but not something every wake user would — it must not be
baked into the general dossier by default.

Decision: a separate, off-by-default module (e.g. `signals_doe.py`),
gated by a config flag (`signals.doe.enabled: false` in packaged
`config.yaml`) with a per-call `wake evidence --with-doe-signals`
override. When enabled it would reuse A2's already-extracted full text
(no second parse pass) and append its own section/tags — A2's core
dossier structure is unaffected whether or not it runs. **Not built in
this pass** — still fully deferred, tracked here for the next session.

---

## Built — Theme K (Pass 2): wire seed-PDF consumers

Pass 1 (acquire and store the seed's own PDF) is BUILT — see "Theme K"
in [`docs/design/backlog-built-history.md`](docs/design/backlog-built-history.md).

**Pass 2 (wire consumers) — BUILT** (v0.4.18, `feature/seed-pdf-consumers`):
- `wake describe` — `describe_seed()` now includes up to
  `describe.seed_excerpt_chars` (default 6000) of the seed's own
  extracted PDF text via the new shared `seed_pdf.load_seed_excerpt()`,
  alongside (not instead of) the abstract. Falls back to abstract-only
  when no seed PDF text exists. Prompt version bumped `describe-1` ->
  `describe-2`.
- `wake evidence` — `verify_full_text()` includes up to
  `evidence.seed_excerpt_chars` (default 4000) of the same seed excerpt
  as context for judging claimed extensions/relationships. New
  `evidence-3` system prompt (evidence-2's multi-facet shape + one
  instruction to treat the excerpt as ground truth for what the seed
  contributes); `evidence.prompt_version` default bumped `evidence-1` ->
  `evidence-3`.
- `wake narrative section create` — documentation-only, as scoped:
  SKILL.md / `references/narrative.md` / `docs/narrative.md` now note
  that `[ref:SEED]`-marked sentences should be grounded in `seed.pdf`
  directly, not just the abstract. No code change (none was needed).

**Still deferred:** `wake narrative section audit` (a separate item, not
yet built at all — see "Open items carried forward" below) is the
intended place for a claim-vs-dossier semantic check for `[ref:SEED]`
sentences specifically; out of scope for this pass.

---

## Built — `wake assess`: evidence-gap triage report

**BUILT** (v0.4.19, `feature/assess`). Read-only report run between
`wake classify` and `wake fetch-pdf`, joining classified.json (relationship/
confidence/citations), `themes._resolve_work_status()` (honest status +
dossier existence, derived from overrides — never the classify-time-stale
`verification_status` field), every theme's own JSON sidecar (membership),
and the PDF fetch log into one per-work document —
`report.build_assessment()`. Reuses `report._score()`/
`relationship_strength()` directly for ranking rather than a second,
drifted copy of the formula.

Returns `{seed, totals, themes, works, triage}`: `totals` is aggregate
coverage; `themes` is per-theme verified/proposed/provisional/unclassified
counts; `works` is every classified work (not truncated, unlike
`impact.json`'s `top_evidence`) with full per-work detail including
`score_inputs` (so an agent can re-rank by its own criteria) and a `pdf`
block (cached/never-attempted/exhausted/fetched-but-gone, same derivation
`missing_pdfs.list_missing_pdfs()` uses); `triage` is the opinionated
shortcut — provisional, not excluded/duplicate, score-descending.
`author_overlap` is reported but does not affect `score` (matches
`impact.json`'s existing ranking).

`wake assess <seed> [--top N]`. SKILL.md gained a new Step 12 pointing the
agent at `data.triage` instead of the previous vague "reserve it for
works where the narrative genuinely hinges on getting the relationship
right" heuristic.

---

## Built — Theme G: Timeline Curation

**BUILT** (v0.4.20, `feature/timeline`). Originally scoped as a
`report.py`-adjacent metrics renderer (a markdown timeline derived
non-interactively from classified works' years + relationship strength);
re-scoped mid-design once framed around who actually uses it — an agent
and human iterating together, deciding what belongs on the timeline, not
wake computing it for them. Rebuilt on the same "candidate material →
curated units → stitch" pattern as `wake theme`/`wake narrative`, not a
one-shot aggregate:

- `wake timeline candidates` — read-only, complete, scored/dated/bucketed
  view of every classified work (`report.relationship_score()` directly,
  never a second formula); never pre-selects a "top N" or filters weak
  relationships by default — the editorial threshold stays in the
  agent/human conversation, not baked into a config default.
- `wake timeline period create`/`confirm` — a period (a bare-year
  emergent bucket or a named span with `--from`/`--to`) holds a curated
  set of highlighted works, each with its own optional note plus a
  period-level framing note. Always writes `draft`; `confirm` refuses
  unless every highlighted work is currently human-verified (re-resolved
  fresh, same bar `wake theme confirm` enforces) — a confirmed period is
  an evidentiary claim, not just a classification guess.
- `wake timeline stitch` — assembles every period (chronological) into
  `timeline.md` (the working artifact, all periods, like `narrative.md`)
  and `timeline.json` (the CONFIRMED periods only — the handoff to a
  separate Tufte-style graphic-rendering tool). Overlapping period
  ranges are reported, never blocked.
- Wired into `wake rebuild` (re-renders periods + re-stitches) and the
  rebuild manifest (`timeline/periods/*.json` tracked as inputs); a
  `[timeline](timeline.md)` nav link added to `impact.md`/README/AGENTS
  when it exists.

---

## Built — Theme M: Primo abstract/DOI/PDF-URL backfill

**BUILT** across two branches: `feature/primo-abstract-backfill`
(abstracts + DOI) and `feature/oa-pdf-url-capture` (OpenAlex + Primo PDF
URLs). Originated from a live capability investigation of the ANL Primo
discovery-layer API (Ex Libris) — confirmed reachable and unauthenticated
from the working environment, tolerant of a much higher request rate in
practice than OSTI/Semantic Scholar (no throttling observed at 20
parallel / 15 rapid-sequential requests), and able to recover a usable
abstract for 20/20 sampled citing works OpenAlex's own abstract
reconstruction had missed (Elsevier/Springer/IEEE sources).

- `wake/sources/primo.py` — DOI- and title-similarity-guarded
  lookups for abstract, DOI, and (new) OA PDF URL
  (`get_oa_pdf_url_by_doi`/`by_title`, gated on Primo's own
  `display.oa == free_for_read` — verified against live paywalled IEEE/
  Elsevier/ACM records, which only ever exposed a `linktorsrc` abstract-
  page link, never a PDF). Institutional endpoint resolved from
  `WAKE_PRIMO_BASE_URL`/`_VID`/`_INST`/`_SCOPE` env vars first, then an
  optional `abstract_backfill.primo` config block — every function is a
  safe no-op with no network call unless explicitly configured, since a
  Primo endpoint is one institution's library subscription, never a
  shared default.
- `wake/backfill.py` — Primo wired in as the first abstract-backfill
  source (`[primo, osti, semanticscholar]`), plus DOI backfill for
  DOI-less works and a `prefer_over_openalex` mode that consults Primo
  for every citing work, not just abstract-less ones. A discovered OA
  PDF URL (`primo_pdf_url`) is captured as a side effect of whichever
  Primo call already ran for the abstract/DOI — never an extra request.
- `wake/sources/openalex.py` — separately, `best_oa_location.pdf_url`
  and `open_access.oa_status` added to the citing-works `select=` and
  `_summarize_work`'s output as `oa_pdf_url`/`oa_status` — free (already
  in the `citing` response), populated for the ~13–23% of works OpenAlex
  itself marks open access. Noticed while evaluating (and declining) a
  Primo-based PDF source: Primo's OA links only ever cover records
  already open access, which this OpenAlex field reaches even earlier
  and for zero extra API calls; a live PVFS-seed data pull confirmed
  OpenAlex's `best_oa_location` strictly dominates its own
  `primary_location.pdf_url` (every work with the latter also has the
  former; 12/843 had only the former) and that the recovered PDF hosts
  include a long tail (institutional repositories, ACM, Springer,
  figshare, etc.) `pdf_fetch.py`'s existing DOI-keyed chain doesn't
  reliably reach on its own.
- `wake/models.py` — `Work` gained `oa_pdf_url`/`oa_status` (OpenAlex,
  born with the work) and `primo_pdf_url` (Primo, backfill-time) as two
  independent fields, not one overwritten by the other, since they come
  from different sources at different times and may disagree.
- `wake/pdf_fetch.py` — new `openalex_oa` (pre-resolved URL, zero
  network calls) and `primo` (prefers a captured `primo_pdf_url`, else a
  live lookup) chain entries. Default order:
  `[openalex_oa, osti, semanticscholar, unpaywall, springer, arxiv,
  primo, core]` — `openalex_oa` first (free and only ever helps), `primo`
  second-to-last (opt-in, and a smaller long-tail fallback given the
  earlier sources' overlap with it).

Verification: `ruff check`/`mypy` clean on both branches; full offline
suite green throughout (895 passed after the abstract/DOI branch, no
regressions after the PDF-URL branch's ~35 new tests across
`test_primo.py`, `test_backfill.py`, `test_pdf_fetch.py`,
`test_openalex.py`, `test_models.py`).

Deferred (not part of Theme M): authenticated Primo/Alma delivery for
licensed (non-OA) publisher PDFs — the public API this integration uses
only ever exposes OA full text, confirmed by inspecting real IEEE/
Elsevier paywalled records during the initial capability check.

## Deferred — Theme H: Non-Publication Evidence Search

Press releases, news coverage, etc. — a genuinely new source type (web
search, not OpenAlex/OSTI/Semantic Scholar). Needs its own fetch/dedup/
credibility-tagging logic and a place in the Theme D OKF wiki.

---

## Theme I — Async/Background Processing

No new `wake` job abstraction for now. Ad hoc `setsid ... & disown` +
poll-loop (via `kill -0` in a bash loop) proved sufficient for the full
408-work live classify run. `opencode-pty` (github.com/shekohex/opencode-pty)
is a real, installable community plugin for persistent background PTY
sessions if needed later — not currently installed in this workspace.
Revisit only if/when MinerU or another genuinely slow step gets adopted.

---

## Open items carried forward (not yet decided)

- **`wake/__init__.py`'s `__version__ = "0.1.0"` has never been bumped**,
  despite ~22 documented `v0.4.x` releases in `docs/build-log.md`.
  `state.py::mark_stage_complete` stamps this stale constant into every
  packet's `.state.json` as `tool_version` (both top-level and per-stage)
  — so that field is useless as a provenance/era signal. Confirmed live:
  a session investigating the PVFS packet (`W2110298485`) saw
  `tool_version: "0.1.0"` on a classify-2 sidecar and wrongly inferred it
  predated the v0.4.21 CiTO taxonomy refactor; only inspecting the raw
  on-disk relationship labels (already in the post-refactor vocabulary)
  caught the false lead. Fix: derive `__version__` from a single real
  source (package metadata, or bump it per release), and/or treat the
  per-stage `prompt_version`/`model` fields already captured in
  `.state.json` as the real provenance signal rather than `tool_version`.
- Author-email discovery strategy for Theme A2 (Crossref? ORCID? PDF
  parsing?) — no source currently reliably provides this; not attempted
  in the A2 build.
- Whether `wake fetch-pdf` should cache negative results (a source
  confirmed to have no OA copy) to avoid re-querying on every dossier
  regeneration. Still open — `wake evidence`'s own dossier-level cache
  (skip re-verification if a dossier already exists) covers the common
  case of re-running `wake evidence` on the same citing work, but a
  fresh `wake evidence` call on a *different* citing work with the same
  unresolvable DOI would still re-try the full fetch-pdf chain.
- Theme B (DOE-relevance signals): design decided (separate, off-by-default
  module — see Theme B above), not yet built.
- `wake evidence --from-pdf-dir <folder> <seed>` — the batch variant of
  the (now-built) single-file `wake evidence --from-pdf`: tries every PDF
  in a folder against every currently-provisional citing work; non-matches
  are left alone in the input folder and simply reported (not deleted,
  not moved) — the command is stateless, so pointing it at the same
  folder again just re-reports the same mismatches.
- Interactive review rendering polish — when presenting a citing work to
  the human pre-verify, include authors alongside title, and surface the
  dossier's per-quote text + page numbers inline (not just title +
  justification). Small template change to whatever the agent uses to
  render the pre-verify summary; the one-at-a-time confirmation pattern
  itself already works well and doesn't need a redesign, just this
  richer rendering.
- `wake narrative section audit <seed> <slug>` / `wake narrative audit
  <seed>` — semantic claim-vs-source check: for each `[ref:...]`-marked
  sentence, load the referenced dossier(s) and have an LLM flag whether
  the sentence's claim is actually supported. Reports only, does not
  enforce; kept separate from `section confirm` so drafting is never
  blocked on LLM audit availability.
- README multi-harness skill-install docs. The `wake skill export`
  install step (Getting Started, step 1) currently only names the
  correct destination path for opencode (`.opencode/skills/wake`,
  fixed after `wake-doc-bug.md` reported the old `.opencode/agent/wake`
  example silently failed opencode's skill discovery — see
  `packages/opencode/src/skill/index.ts`'s `{skill,skills}/**/SKILL.md`
  pattern). Deferred: a short per-harness table (opencode, Claude Code,
  others) with each one's confirmed-correct skill directory, rather
  than one example plus a "check your harness's docs" hand-wave.
  Needs someone to actually verify each harness's path from its source
  the way opencode's was verified here, not guess it.
- **F2** — Thematic impact bullet summary: a shorter, bullet-style
  section-drafting mode alongside full prose (F1's sections are already
  "cluster confirmed-theme evidence into a narrative unit," so F2 may
  turn out to be a rendering variant of the same `section create`
  primitive rather than a separate mechanism — revisit once F1 is used
  for a second real seed).
- Packaging (zip a folder of `narrative.md` + linked `evidence/` +
  `evidence/themes/` for a tech editor) — F1's `narrative.md` +
  `evidence/` directory already are that folder; only the packaging step
  itself (zip, or a `wake export` command) remains unbuilt.
---

## Theme L follow-on — Structural Hardening deferred work

Theme L (Structural Hardening) itself closed — see the "Built" index
below. It had three deferred follow-ons; two are now also closed:

- ~~Formalize the remaining `_normalize_*`/legacy-shape functions~~ —
  **closed by audit** (v0.4.15): every remaining candidate was either
  out of scope (pure input normalizers), already formalized via the
  right mechanism for its kind (filesystem-location renames), or
  determined to be legitimately not a schema migration (two render-time
  view-derivers). See
  [`docs/design/normalize-audit.md`](docs/design/normalize-audit.md)
  for the full function-by-function determination.
- ~~A persisted dirty/revision manifest for `wake rebuild`~~ — **closed**
  in two phases. **Phase 1** (v0.4.16, `refactor/explicit-render`):
  rendering became a single explicit `wake rebuild` step -- every
  JSON-mutating command (`evidence`, `override`, `unverify`, `theme
  create`/`confirm`, `narrative outline create`, `section
  create`/`confirm`) writes only JSON and returns `"rebuild_needed":
  true`; `wake bake`/`wake narrative stitch` remain explicit render
  verbs for `impact.md`/`narrative.md` but no longer additionally
  refresh README.md/AGENTS.md as a side effect. This was a prerequisite
  the user identified directly: a manifest reporting "what changed since
  the last render" is only meaningful once rendering is a distinct act,
  not something every write already did inline. **Phase 2** (v0.4.17,
  `feature/rebuild-manifest`): the manifest itself. `wake rebuild`
  hashes (sha256) every JSON render-input source (seed.json,
  citing.json, classified.json, overrides.jsonl, every dossier/theme/
  section JSON, outline.json), persists them in `rebuild-manifest.json`
  (`models.RebuildManifest`), and reports a `changes` block (sources
  added/changed/removed since the previous rebuild) in its return value
  and CLI output. Report-only, as the user specified: `rebuild_seed()`
  still unconditionally re-renders every artifact type on every call --
  the manifest never gates or skips a render step, it only answers "what
  changed since I last looked."

One remains open:

- **Full `WakeContext` threading** through all ~90 existing
  `base:`-taking domain functions. Phase 3 landed the context object and
  one canonical CLI construction point; `ctx.base` is a verified drop-in
  for any existing `base=` call site, but the mechanical rewrite of every
  call site itself was deliberately deferred given the blast radius.

Explicitly **not** planned: replacing the filesystem-artifact model with
a database. Both the external assessment and independent review agree
file-first is a real strength of wake's design, not a symptom needing a
fix — what's missing is a formal schema/manifest/build-mechanism layer
*around* the existing files, not a different storage model.

---

## Held — Theme F4: Workflow reframe (two-phase themes)

**DO NOT EXECUTE.** Raised mid-session when a direct question — "wait:
what does `wake theme create` *do*?" — surfaced that the current
single-shot `theme create` (identity + evidence membership in one call)
runs backwards from how the human actually wants to work: decide the
narrative's themes first, as a planning conversation with no `wake`
involvement at all, then assign specific citing works to those themes as
evidence accumulates. Full design space, two candidate implementations
(a `theme declare` + `theme add` two-phase split, leaning direction, vs.
a lighter `theme create` allowing empty `citing_ids`), the rejected
alternative worked through, four explicit open questions, consequences
for `wake narrative outline`, and a backward-compatibility sketch are
all captured in
[`docs/design/theme-workflow-reframe.md`](docs/design/theme-workflow-reframe.md).
No code, tests, or docs referenced there should change until this has
been walked through live with the human.

