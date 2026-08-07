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

**Structural Hardening follow-ons** (Theme L closed; one of three
original items closed by audit, two remain):
1. Full `WakeContext` threading through the ~90 `base:`-taking domain
   functions. *(Next phase.)*
2. A persisted dirty/revision manifest for `wake rebuild`.

(Formalizing the remaining `_normalize_*`/legacy-shape functions was
closed by audit rather than by migration code — see
[`docs/design/normalize-audit.md`](docs/design/normalize-audit.md):
every candidate was already correctly handled or was never a schema
migration in the first place.)

**Product features, decided but not built:**
- Theme B — DOE-relevance signals (`signals_doe.py`, off-by-default).
- Theme G — Timeline generation.
- Theme H — Non-publication evidence search.
- Theme K Pass 2 — wire seed-PDF consumers (`describe`/`evidence`/
  `narrative`).

**Smaller deferred items** (see "Open items carried forward" below for
full detail): `wake evidence --from-pdf-dir` (batch variant), `wake
assess`/`theme coverage`, `wake narrative section audit`, interactive
review rendering polish, README multi-harness skill-install docs,
author-email discovery, `wake fetch-pdf` negative-result caching, F2
(bullet-style narrative sections), narrative packaging/export.

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
| J | Session-notes batch (11 items: dotfile rename, docs split, `show` verbs, help-text audit, README split, `refs-check`, `dedup`, `posters`, `exclude`, `unverify`) | [history](docs/design/backlog-built-history.md) — Theme J |
| L | Structural Hardening (13 phases, v0.4.0–v0.4.12) | [build log](docs/build-log.md), summarized in [history](docs/design/backlog-built-history.md) — Theme L |

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

## Open — Theme K (Pass 2): wire seed-PDF consumers

Pass 1 (acquire and store the seed's own PDF) is BUILT — see "Theme K"
in [`docs/design/backlog-built-history.md`](docs/design/backlog-built-history.md).

**Pass 2 (wire consumers) — NOT YET DONE.** Each consumer is a separate
future item requiring its own design decision (prompt changes, cost
impact per call):
- `wake describe` — feed seed full text or first-few-pages instead of
  just the abstract for the contribution paragraph.
- `wake evidence` — include seed text excerpt in the LLM verification
  system prompt so the model can better judge claimed extensions.
- `wake narrative section create` — agent can open seed.pdf directly
  when drafting seed-contribution sentences; no code change needed, just
  documentation.
- `wake narrative section audit` (deferred F) — load seed text for
  `[ref:SEED]`-marked sentences.

---

## Deferred — Theme G: Timeline Generation

Markdown timeline of key developments/uses/adoption (derived from
classified works' years + relationship strength), meant to be handed to a
separate model/tool for Tufte-style graphic rendering. Lower complexity —
mostly a new `report.py`-adjacent renderer.

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
- `wake assess <seed>` (or `wake theme coverage <seed>`) — evidence-gap
  triage report run between `wake classify` and `wake fetch-pdf`:
  current theme evidence density, and which classified-but-unverified
  works look highest-value for each theme (by relationship + confidence
  + citation count) — so PDF-fetching effort gets prioritized rather
  than spent uniformly across every provisional work.
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
below. It had three deferred follow-ons; one is now also closed:

- ~~Formalize the remaining `_normalize_*`/legacy-shape functions~~ —
  **closed by audit** (v0.4.15): every remaining candidate was either
  out of scope (pure input normalizers), already formalized via the
  right mechanism for its kind (filesystem-location renames), or
  determined to be legitimately not a schema migration (two render-time
  view-derivers). See
  [`docs/design/normalize-audit.md`](docs/design/normalize-audit.md)
  for the full function-by-function determination.

Two remain open:

- **Full `WakeContext` threading** through all ~90 existing
  `base:`-taking domain functions. Phase 3 landed the context object and
  one canonical CLI construction point; `ctx.base` is a verified drop-in
  for any existing `base=` call site, but the mechanical rewrite of every
  call site itself was deliberately deferred given the blast radius.
- **A persisted dirty/revision manifest for `wake rebuild`** to track
  staleness *between* calls, distinct from the per-call summary it
  already returns.

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

