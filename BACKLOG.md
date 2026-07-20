# BACKLOG — wake Phase 2: Evidence, Narrative & Wiki

Captures the roadmap discussed after the first full live run (Parallel netCDF,
408 citing works classified, complete impact.md reviewed). This is a
substantial expansion beyond wake's citation-classification core: an
evidence-digging, DOE-relevance-signal, and narrative-drafting layer, built
as an OKF-compliant knowledge wiki alongside the existing classify/bake
pipeline.

Sequencing: **A + B first (foundation), then D (organization), then E
(small, high-value), F/G/H deferred** until we've used A/B/D/E for real and
know what's actually needed. A/A2/C/D/E have now been used for real (a
live 408-work run against Parallel netCDF, 46 works full-text verified, 3
themes confirmed) — see Theme F1 below, now BUILT as a result.

---

## Theme A — PDF Acquisition (`wake fetch-pdf`)

Standalone, reusable primitive — not just an internal helper for evidence
dossiers. Also usable to streamline the existing `fill-abstract --from-pdf`
workflow (skip the manual-download step when the PDF chain succeeds).

`wake fetch-pdf <seed> <citing-id>` tries sources in order, all
API-based (no scraping publisher landing pages, no sci-hub-style sources):

1. **OSTI** — extend `sources/osti.py`'s existing DOI lookup to also check
   `links[].rel == "fulltext"` (direct PDF at `osti.gov/servlets/purl/<id>`,
   no auth wall, DOE-funded work only). Zero cost, no rate limit.
2. **Semantic Scholar** — `openAccessPdf.url` field on the paper endpoint
   (distinct from Unpaywall; often a repository copy).
3. **Unpaywall** — `best_oa_location.url_for_pdf` (existing pattern from
   backfill research). Frequently 403s on direct download from publisher
   sites (confirmed: ScienceDirect during WIND Toolkit testing) — still
   worth attempting.
4. **Springer** — `sources/springer.py`, added during a real end-to-end
   validation run (BACKLOG's "use A/C/D/E for real" gate) when older
   Springer LNCS conference chapters kept failing OSTI/S2/Unpaywall/arXiv
   but resolved cleanly at `link.springer.com/content/pdf/<DOI>.pdf`.
   No API call — pure URL construction for `10.1007/...` DOIs, validated
   the same way as every other source (`_looks_like_pdf` rejects a
   paywall HTML page served at that URL). A no-op for non-Springer DOIs.
5. **arXiv** — conditional: if title/author search finds a matching arXiv
   preprint, download directly (always freely available, no bot-blocking).
6. **CORE.ac.uk** — optional, gated behind `CORE_API_KEY` env var (silently
   skipped if unset, same pattern as `SEMANTICSCHOLAR_API_KEY`). Large
   aggregator of repository-hosted OA copies.

On success: saves to `wake-out/<seed>/pdfs/<citing-id>.pdf`, returns the
path.

On failure (paywalled / no OA copy / all attempts 403): returns a
ready-made set of links for the human to try manually:
- Unpaywall lookup page for the DOI
- Google Scholar search URL for the title ("All versions" often surfaces
  a free copy)
- Publisher's direct DOI link
- CORE.ac.uk search link (if not already tried via API)

---

## Theme A2 — Evidence Deep-Dive Dossier (`wake evidence`) — BUILT

`wake evidence <seed> <citing-id>` calls `fetch-pdf` first, extracts the
**entire** document (page-tagged, `sources/pdf_fulltext.py`), then runs an
LLM full-text verification pass (`evidence.py::verify_full_text()`) and
writes `wake-out/<seed>/evidence/<citing-id>.md` as an **OKF concept
document** (+ a `.json` sidecar for programmatic reuse).

**Lifecycle — reframed mid-design at explicit user direction**:
the abstract-only classification is not a baseline that full-text reading
confirms/contradicts — it's inherently weak from the start, and full-text
reading is the substantive assessment, pending human sign-off:

- `provisional` — `classify.py`'s output, always, unconditionally (every
  classified work, not just ones later verified). Never presented as a
  finding, however high its confidence.
- `proposed` — `wake evidence`'s full-text reading: an independent
  judgment (not a rubber-stamp of the provisional guess), with quoted,
  page-cited, full-paragraph passages. Never auto-applied.
- `verified` — only via a human-approved `wake override` call
  (`--verification-source evidence-dossier` or `human-judgment`), always
  executed by the agent, never by asking the human to run it themselves.

Dossier frontmatter:
```yaml
---
type: citing-work-evidence
title: "<citing work title>"
description: "<one-line: how it uses the seed>"
resource: "<DOI or OpenAlex URL>"
tags: [provisional:<label>, proposed:<label>, status:pending-human-review]
timestamp: <generated-at>
---
```

Body: full citation, complete abstract, the provisional classification
(clearly framed as a placeholder), the proposed full-text reading, and
every supporting quote as a **full paragraph, verbatim, with page number**
— not a bare sentence fragment, per explicit requirement ("I want the
human to see the literal text supporting the claim, in context").

**Extraction approach (built as planned)**: lightweight — pypdf/pdfplumber,
page-level only, no MinerU. Confirmed live that multi-column academic PDF
layouts don't extract into clean paragraphs mechanically (both libraries
interleave columns on the committed OSTI fixture), so the LLM — not a
text splitter — is asked to quote the full containing paragraph; it
handles the reading-order jumbling far better than mechanical splitting
would, while wake still attaches a real page number.

Interactive, single-reference tool by design: you decide which leads to
follow, not a batch "process everything" command. Cached — a second call
for the same citing work is a no-op (no LLM call) unless `--force`.

**Extracted text is itself cached** (added in a follow-up pass, prompted
by the user asking whether extraction is saved consistently enough to
debug a surprising finding): `extract_pages_cached()` writes
`wake-out/<seed>/pdfs/<citing-id>.json`, a sibling of the PDF, keyed by
the PDF's sha256 (auto-invalidates on a re-fetched PDF) with an
`extractor` field (`pypdf`/`pdfplumber`) and a timestamp. `wake evidence
--force` re-runs extraction too, not just the LLM call. Lets a human or
an agent debugging a finding on the human's behalf distinguish "the
extraction was garbled" from "the model reasoned poorly" by reading the
cache file directly — no re-run required.

Author-email discovery (originally scoped as part of the dossier body)
was **not built** in this pass — deferred, still an open item below.

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

## Theme C — Combined-Evidence / Thematic Documents — BUILT

When several individual citing works together support a broader claim
(e.g. "extensive use in Earth system modeling"), a theme document
synthesizes them into `wake-out/<seed>/evidence/themes/<slug>.md` — an
OKF concept doc linking out to each work's own dossier rather than
duplicating content.

**Built as `wake/themes.py`**, a pure write-primitive with **no LLM
call**: the agent (having already read the underlying dossiers/
classifications) supplies the title, synthesis paragraph, and which
citing works belong together; `wake` validates and persists that
judgment — it never decides what's thematically related and never writes
the synthesis prose itself. Same trust model as `wake override`.

**Two independent verification tracks**, matching the codebase-wide rule
that only a human promotes anything to a settled state — this was an
explicit design correction mid-session (the first draft let the *agent's*
act of creating/re-asserting a theme count as confirmation, which broke
the invariant that only a human sign-off produces a "verified"/"settled"
result):

1. **Per-work relationship claims** — unchanged, existing lifecycle
   (`provisional` → `proposed` → `verified` via classify/evidence/
   override). `create_theme()` never alters a work's own status; every
   cited work is displayed with its own honest, current tag. A work
   verified via a plain `human-judgment` override (no dossier at all)
   is correctly treated as meeting the bar — it is never flagged as
   needing evidence just because it has no dossier file.
2. **The theme's synthesis claim** — new: `theme_status: "draft"` →
   `"confirmed"`. `create_theme()` **always** writes `"draft"` — an
   agent's judgment can never itself produce a confirmed theme. Only
   `confirm_theme()` (`wake theme confirm`, run by the agent on the
   human's behalf, exactly like `wake override`) can promote to
   `"confirmed"` — and it **refuses unless every cited work is already
   `"verified"`**, re-resolving each work's status fresh at confirm time
   (not trusting the theme's own possibly-stale JSON), so a work verified
   after the theme was created still counts. A theme can never appear
   settled while resting on unverified findings.

**Mixed sourcing (v1, deliberately simple — flagged for revisit)**:
`create_theme()` allows citing works with no evidence dossier yet
(provisional, abstract-only) to be included, tracked in the theme's own
`needs_evidence` JSON field. This speeds up drafting (a theme doesn't
need every member fully verified before it can exist as a draft) but
means the mechanism for keeping that list honest as dossiers appear
independently needed real thought:

- `list_theme_needs_evidence()` (`wake theme queue <seed>`) is the
  surfacing mechanism — it scans every theme's JSON at *query time* and
  reports two states: `needs-evidence` (still no dossier) and
  `dossier-available-unreviewed` (a dossier has appeared since the theme
  was last created/reviewed, but hasn't been re-asserted).
- **Nothing is ever silently upgraded.** A dossier appearing for a
  `needs_evidence` citing work via an unrelated `wake evidence` call does
  **not** mutate the theme's JSON automatically — `evidence.py` has zero
  coupling to `themes.py` for this. The agent must explicitly read the
  new dossier and decide whether it still supports the thematic claim
  (the full-text reading may contradict the abstract-only guess the
  theme was built on), then re-run `wake theme create` with the same
  slug to re-assert inclusion.
- This is intentionally the simplest mechanism that preserves the
  human-confirms invariant; a more automatic reconciliation (e.g.
  `evidence.py` proactively flagging affected themes) was considered and
  explicitly deferred until real usage shows whether the manual
  `wake theme queue` + re-create loop is actually a friction point.

**CLI surface**:
```
wake theme create  <seed> <slug> --title "..." --summary "..." --citing-ids ID,ID,ID
wake theme confirm <seed> <slug>
wake theme queue   <seed>
```
`create` always overwrites (no `--force`) — unlike every other write
command in this codebase, there's no expensive LLM/network call to
protect against re-doing, so there's nothing to cache-guard. No
`wake show theme` — theme docs are plain markdown, read directly, same as
individual dossiers.

`evidence_wiki.py` gained `themes_index_path()` / `rebuild_themes_index()`
(catalog grouped Confirmed/Draft), called from `themes.py` after every
write — same pattern as `evidence.py` calling `rebuild_index()`.

---

## Theme D — OKF Evidence Wiki (organization layer) — BUILT

Google's **Open Knowledge Format** (OKF v0.1, June 2026) — a formalization
of Karpathy's "LLM Wiki" pattern: a directory of markdown "concept"
documents (file path = identity), each with minimal YAML frontmatter
(`type` required; `title`, `description`, `resource`, `tags`, `timestamp`
conventional) + a markdown body, linked via plain markdown links forming a
graph. Reserved filenames: `index.md` (catalog, progressive disclosure) and
`log.md` (chronological history).

Lives inside `wake-out/<seed>/` (same work-dir/cache lifecycle as
everything else — no separate init command):

```
wake-out/<seed>/
  evidence/
    index.md          — OKF catalog: concept + one-liner per dossier
    log.md             — OKF chronological log: what was investigated, when
    <citing-id>.md      — Theme A2/B dossiers (OKF concept docs)
    themes/
      index.md            — OKF catalog: theme docs, grouped Confirmed/Draft
      <theme-slug>.md     — Theme C combined-evidence docs (built)
      <theme-slug>.json   — same theme, structured (status, citing_works, needs_evidence)
  pdfs/
    <citing-id>.pdf     — locally-cached PDFs (Theme A)
```

**Built as `wake/evidence_wiki.py`**, a new leaf module derived entirely
from the existing dossier `.json` sidecars (no separate index/log data
store — `rebuild_index()` can always regenerate `index.md` from scratch
by rescanning `evidence/*.json`):

- `rebuild_index()` — groups dossiers **Verified** / **Pending Review**,
  sorted within each group by the same score `report.py` uses for
  "Strongest Evidence" (`RELATIONSHIP_STRENGTH[relationship] x
  log1p(cited_by_count)`). Two new dossier JSON fields support this
  without re-loading `classified.json`: `citing_cited_by_count` and an
  explicit `verification_status` (previously only implicit in the
  markdown frontmatter's `status:` tag).
- `append_log_entry()` — one line per real event, newest at the bottom:
  `dossier_built`, `dossier_rebuilt` (a `--force` re-run),
  `investigation_failed` (no PDF found, or extraction produced no text),
  and `verified_by_human`. A cache-hit `wake evidence` call (dossier
  already exists, `force=False`) is a true no-op — nothing logged,
  nothing rebuilt.
- `mark_verified()` — patches a dossier's `.json` (`verification_status`
  → `"verified"`, adds a `human_verification: {justification,
  verified_at}` block) and its `.md` (frontmatter `status:` tag +
  "Status" section body) in place.

**Wiring** (both call sites fire only on real work, never on a cache hit):
- `evidence.py::build_dossier()` calls `append_log_entry` +
  `rebuild_index` after every fresh build or `--force` rebuild, and logs
  the two failure paths (`no_pdf`, `extraction_failed`) too.
- `report.py::add_override()` calls `mark_verified` + `append_log_entry`
  + `rebuild_index` **only** when `verification_source ==
  "evidence-dossier"` — a plain `"human-judgment"` override (no dossier
  behind it) leaves the evidence wiki untouched. If no dossier exists for
  the citing ID (override without a prior `wake evidence` call),
  `mark_verified` is a silent no-op.
- **`--force` always resets a previously-verified dossier back to
  `pending-human-review`** — a fresh extraction + LLM read is a new
  finding, not a continuation of the old human sign-off; it reappears in
  `index.md`'s Pending Review section until re-confirmed. The prior
  `human_verification` record is overwritten, not preserved as history
  (the full history lives in `log.md` instead).

`index.md`/`log.md` only spring into existence on the first real event —
no empty scaffolding created at `resolve`/`citing` time, consistent with
`impact.md` not existing until `wake bake` and `overrides.jsonl` not
existing until the first override.

No new CLI surface: both files are plain markdown, read directly (same as
individual dossiers today — there's no `wake show dossier` either).

`SKILL.md` plays the role of Karpathy's/OKF's "schema file" — extended
with a note that `wake override` auto-updates the wiki, so the agent
doesn't need a separate step.

---

## Theme E — Author-Overlap Tag — BUILT

Answers: *"is 'enhanced by' one of the predicates we look for?"* — No, and
it shouldn't be a new relationship predicate. `extends` already captures
"directly extends the method/framework/theory of the seed" regardless of
authorship. What's missing is **author-overlap detection** as an
orthogonal tag:
- `extends` + `author_overlap: true` = the original team's own
  follow-on/enhancement paper
- `extends` + `author_overlap: false` = independent third-party extension

**Built as `wake/author_overlap.py`**, a small, pure, deterministic module
(no LLM call): `compute_overlap(seed_work, citing_work)` returns
`{"author_overlap": bool, "overlapping_authors": [name, ...]}` by
intersecting OpenAlex author-ID sets. ID-based, not name-based — display
names collide and OpenAlex formats the same author's name inconsistently
across papers. Two works both lacking author IDs are never treated as
"the same team" just because both sides are empty.

`sources/openalex.py::_summarize_work()` now preserves `author_ids`
alongside `authors` (previously discarded, display-name-only) —
index-aligned with `authors`, `""` for an authorship entry with no
OpenAlex author id. No new API field needed: `authorships[].author.id` is
already returned by the existing `authorships` `select` field.

Wired into both places BACKLOG originally called for:
- `classify.py::classify_one()` — every classified work gets
  `author_overlap`/`overlapping_authors` alongside its relationship,
  orthogonal to (not a replacement for) the relationship label itself.
- `evidence.py::verify_full_text()` — every dossier gets the same tag;
  `_render_dossier_markdown()` surfaces it as an `author-overlap:true`
  frontmatter tag plus an inline note under the citing work's byline when
  true ("this appears to be the original team's own follow-on work").

`report.py` aggregates it too: `build_metrics()` adds a
`self_extension_count` (works with `author_overlap: true` among the
classified set), surfaced in the brief's "Nature of Impact" section as a
one-line callout, and every `top_evidence` entry carries
`author_overlap`/`overlapping_authors` — rendered as a `[SELF-EXTENSION —
seed's own team]` tag alongside the existing provisional/verified tag in
"Strongest Evidence".

Powers the Theme F1 differentiator narrative (the tool's own evolution by
its creators is a different story thread than third-party adoption).

---

## Theme F1 — Narrative Drafting (`wake narrative`) — BUILT

Built directly out of the first real end-to-end validation run (a live
408-work Parallel netCDF run, 3 confirmed themes) — the original BACKLOG
sketch ("contribution narrative draft using seed abstract + Theme E
self-extension papers") turned out to under-specify the actual need once
real confirmed themes existed: a narrative isn't one paragraph, it's
several theme-grounded sections plus free-form framing, drafted one
component at a time and assembled at the end. Explicit user direction
mid-design: "describe an overall narrative with a set of themes, then do
what we just did to support the themes, and then do this narrative
generation piece one component at a time. Then stitch it all together."

Three explicit stages, same trust model as `wake theme`/`wake override`
throughout (`wake` never writes prose or decides what's related; it
validates and persists the agent's/human's judgment):

1. **Outline** (`wake narrative outline create`) — the agent plans the
   overall structure before writing any prose: an ordered list of
   components, each `"theme"` (backed by one or more already-existing
   themes — not required to be confirmed yet, since planning ahead of
   confirmation is fine) or `"free"` (framing prose, e.g. intro/
   conclusion, no evidence claim). Always overwritable, no confirmation
   of its own — a plan, not a claim.
2. **Sections** (`wake narrative section create` / `section confirm`) —
   one component drafted at a time. `create` always writes `"draft"`
   (mirrors `create_theme()` — drafting is never itself a sign-off).
   `confirm` promotes to `"confirmed"`: for a theme-backed section,
   refuses unless *every* referenced theme is **currently** confirmed,
   re-checked fresh at confirm time (not cached) — if a theme is later
   reopened to draft (e.g. a new unverified work added), a section built
   on it is caught, not silently left stale. A section can reference
   *multiple* confirmed themes (explicit user choice: not a strict 1:1
   constraint). Free-form sections go through the same draft→confirmed
   lifecycle uniformly (explicit user choice — framing prose can still
   make claims worth a human's eye) but confirm immediately since there's
   no theme to check.
3. **Stitch** (`wake narrative stitch`) — assembles the outline order +
   every section into `wake-out/<seed>/narrative.md`. Works on partial
   data like `wake bake` — missing or still-draft sections are clearly
   labeled ("Partial narrative — N section(s) not yet written: ...", a
   `⚠ DRAFT` banner on unconfirmed prose), never silently hidden or
   overstated as more final than they are.

Validated live against the real Parallel netCDF packet: outline created
referencing all 3 confirmed themes + 2 free sections, one theme-backed
section drafted and confirmed (blocked correctly when tested against an
unconfirmed theme first), partial stitch correctly labeled the 4 not-yet-
drafted sections.

**Per-sentence source references, added in a follow-up round (absorbing
most of F3 into F1):** explicit user requirement — "each sentence with a
factual basis" should carry a reference an agent or human can verify.
Every factual sentence in `--prose` can end with a `[ref:ID,ID,...]`
marker (`SEED` for the seed paper, or a citing OpenAlex ID for anything
else). `create_section` validates every marker in two passes before
writing anything:

1. **Packet consistency** — every citing work `.overrides.jsonl` calls
   human-verified must have an actual dossier file on disk; if any are
   missing, the whole packet is refused as inconsistent (a corrupted
   packet can't be trusted for any reference, not just the one being
   added).
2. **Per-marker validity** — each named ID must be `SEED` or a citing
   work that is *currently* human-verified for this seed (`.overrides
   .jsonl`, not `classified.json`'s own never-updated `verification_
   status` field — same "verified" definition `wake theme confirm`
   already uses). Unknown/unverified IDs are rejected, naming every bad
   ID at once.

This guarantees every reference names a real, checked source — it does
**not** guarantee the source supports the sentence's specific claim,
which stays an agent/human judgment (a future `wake narrative section
audit` command, deliberately deferred, is the intended place for that
semantic check).

Raw `[ref:...]` markers are the source of truth, kept as-written in
`section.json`/`section.md`/`outline.md`. Only `wake narrative stitch`
renumbers them — once the whole document is available — into `[R1]`,
`[R2]`, ... in reading order (stable across reuse: the same source cited
in two sections keeps one number), and appends a Chicago-author-date
`## References` list at the bottom, one entry per distinct source, with
a DOI link where available. wake has no persisted OSTI identifier for
any citing work (OSTI is used only transiently as one candidate
PDF-acquisition source, never written back to `classified.json`), so no
OSTI suffix is rendered — noted as a known gap, not silently faked.

Validated live: drafted a 3-paragraph narrative (what PnetCDF is, its own
evolution; broad adoption across scientific computing; earth-system
adoption) directly from the 3 confirmed Parallel netCDF themes, every
factual sentence carrying a marker, stitched with a dense R1...Rn
reference list.

Deferred, now that F1 (+ per-sentence refs) exists:
- **F2** — Thematic impact bullet summary: a shorter, bullet-style
  section-drafting mode alongside full prose (F1's sections are already
  "cluster confirmed-theme evidence into a narrative unit," so F2 may
  turn out to be a rendering variant of the same `section create`
  primitive rather than a separate mechanism — revisit once F1 is used
  for a second real seed).
- **Claim-vs-source semantic audit** — `wake narrative section audit`:
  for each `[ref:...]`-marked sentence, have an LLM read the referenced
  dossier(s) and flag whether the sentence's claim is actually supported
  — a real value-add for long, multi-session narratives, deliberately
  kept as a separate opt-in step rather than folded into `create_section`
  or `confirm_section`.
- Packaging (zip a folder of `narrative.md` + linked `evidence/` +
  `evidence/themes/` for a tech editor) — F1's `narrative.md` +
  `evidence/` directory already are that folder; only the packaging step
  itself (zip, or a `wake export` command) remains unbuilt.

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

---

## Theme J — Session-notes batch (post-narrative-refs housekeeping + trust-model rounding)

Raised as a long list of notes after the first live narrative was drafted
and reference-checked. Sequenced for execution (each item its own
branch, merged before the next); see the design-doc note above for why
the workflow reframe (originally "item 5" in this list) was pulled out
and held separately rather than sequenced here.

**Sequence:**

1. ~~Workflow reframe design capture~~ — done first, see Theme F4 above;
   held, not executed.
2. ~~**Rename dotfiles in packet directories.**~~ — BUILT. `.overrides
   .jsonl` → `overrides.jsonl`, `.classify/` → `classify/`. Read-either
   compat shim (old dotfile name/directory still read if the new one
   doesn't exist yet), migrates to the new name/directory automatically
   on the next write (`add_override`/`_write_sidecar`), never overwrites
   an existing new-named file/directory. `.cost.jsonl` and `.state.json`
   deliberately left as dotfiles — genuinely internal bookkeeping the
   human isn't expected to read directly, unlike overrides (the human's
   own verification decisions) and classify sidecars (debuggable raw
   per-work LLM output).
3. ~~**Split `wake/skills/impact-analysis/references/reference.md` into
   per-workflow-phase files.**~~ — BUILT. It had grown to ~475 lines
   covering every command's JSON schema and output layout in one file.
   Split by actual content boundary (some originally-proposed phases —
   resolve/citing/sample/bake — turned out to have no reference-page
   content of their own beyond the command list, which stays in the
   index) into `references/classify.md`, `pdf-acquisition.md`,
   `evidence.md`, `themes.md`, `narrative.md`, `output-layout.md`,
   `environment.md`, with `references/reference.md` itself rewritten
   down to a ~55-line index (seed ID formats, full command list, and a
   table linking to each phase file) plus SKILL.md's own two inline
   pointers redirected to the specific file they actually meant. No
   behavior change; docs-only.
4. ~~**`wake <noun> show` verbs.**~~ — BUILT. Added `wake theme show
   <seed> <slug>`, `wake narrative show <seed>` (the stitched top-level
   `narrative.md`), `wake narrative outline show <seed>`, `wake
   narrative section show <seed> <slug>`, following the subject-noun-
   first precedent already set by `wake config show`/`wake skill show`.
   One deviation from the original plan: `wake evidence <seed>
   <citing-id>` already has two bare positional args and no subaction
   structure, so adding an `evidence show` subaction created a genuine
   argparse ambiguity (confirmed interactively: argparse can't
   disambiguate `wake evidence W1 W2` from a third case `wake evidence
   show W1 W2` once both a subparser and top-level positionals are
   registered on the same parser). Rather than restructure `evidence`'s
   primary invocation shape, dossier re-printing was added as `wake show
   dossier <seed> <citing-id>` instead, alongside the existing
   `brief`/`metrics`/`top`. All five re-emit an already-written file
   as-is with no computation, matching `wake show brief`'s existing
   convention; 11 new end-to-end CLI tests (full `wake.cli.main.main()`
   invocation via `sys.argv`, not just the underlying module functions)
   verify success and not-yet-built-error paths for all five, live-
   tested against the real Parallel netCDF dry-run packet.
5. ~~**CLI help + SKILL.md write-primitive clarity audit.**~~ — BUILT.
   Small documentation-only pass triggered by the "wait: what does
   `theme create` *do*?" question mid-session. Every `wake theme
   create`/`confirm`, `wake narrative outline create`, `wake narrative
   section create`/`confirm`, and `wake override` `--help` text now says
   plainly that wake validates and persists a judgment already made
   (by the agent for `create`, by the human for `confirm`/`override`)
   rather than deciding anything itself or running an LLM. Added a new
   Principle 13 to SKILL.md's "Principles for Agents" section stating
   the same rule generally, as a catch-all for any future write-
   primitive command: "if you find yourself expecting one of these
   commands to tell you whether something is a good idea, that's a sign
   the command is being asked to do a job it doesn't do." No behavior
   change; docs-only.
6. **Split top-level `README.md` into a short README + `docs/` topic
   pages.** README has grown to ~500 lines including full workflow
   narrative, PDF-source explanation, abstract-recovery philosophy, etc.
   New README should be about one screen: what wake is, install, one
   command example, links out. New top-level `docs/` (repo docs, not
   packaged with the pip install) gets `docs/workflow.md`,
   `docs/abstract-recovery.md`, `docs/pdf-sources.md`,
   `docs/narrative.md`, `docs/themes.md`. Agent-facing files (SKILL.md,
   the skill's own `references/`) are untouched by this split — they
   serve a different reader.
7. **`wake narrative refs-check <seed>` — verify the stitched
   narrative's References section with the external `ref-checker` tool**
   (https://github.com/rbross-hpc/ref-checker). Distinct from the
   already-noted "claim-vs-source semantic audit" deferred item under
   Theme F1/F3 — this checks that the *bibliographic entries themselves*
   (authors, year, title, DOI) are correct and resolvable, not whether a
   sentence's claim is actually supported by its source. Shape: export
   the References section to a `refs.json` matching ref-checker's
   expected input, install ref-checker if not already present, run
   `ref-checker check --refs-json <refs> --results-json <output>` as a
   subprocess, parse the results and surface any discrepancies to the
   human. Human decides how to resolve flagged entries (fix the citing
   work's metadata upstream, or accept as a known limitation). Exact
   JSON shape TBD from ref-checker's own docs at implementation time.
8. **`wake dedup <seed>` — surface likely-duplicate citing works for
   human sign-off.** Covers all three duplicate shapes seen or expected:
   preprint vs. published version (2 caught by hand this session via
   fuzzy title matching — `W4229646607`/`W2137705743` and
   `W4251231835`/`W2153325196`, both GMDD preprints of their published
   counterparts), workshop vs. expanded journal version, and the same
   paper independently double-published. Heuristic: same/overlapping
   authors + high title similarity + one side showing a
   preprint/workshop venue signal. Never auto-merges — presents
   candidates one at a time (same "human confirms one at a time" rule
   used everywhere else), waits for explicit accept before recording a
   merge decision. Downstream theme/narrative/bake views treat a
   confirmed pair as one work under the human-designated canonical
   version.
9. **Posters/conference-abstracts: surface for human sign-off, same
   shape as dedup.** `type == "conference-abstract"` or a
   `Poster:`/`Abstract:` title prefix currently has to be caught and
   excluded by hand each session (this session's "posters are out" rule
   was established ad hoc mid-run). Surface candidates for explicit
   human exclusion rather than silently dropping them or requiring the
   human to remember to ask — same one-at-a-time confirmation pattern as
   dedup and the same downstream effect as `wake exclude` (below) once a
   human confirms.
10. **`wake exclude <seed> <citing-id> --reason "..."` — first-class
    exclude state.** Today, a citing work judged not actually about the
    seed (e.g. background-mention where the seed appears only in a
    bibliography) still just sits as a low-relevance `verified` work —
    nothing stops a future theme or narrative section from citing it.
    An explicit, permanent exclusion (with justification, recorded in
    `evidence/log.md` like other state transitions) should make a work
    unusable: `theme add`/`theme create` refuses to include an excluded
    work, `wake narrative` reference validation refuses an excluded ID,
    `wake gaps`/`wake theme queue` stop surfacing it. Undoing an exclude
    is a separate, explicit `wake unexclude` action with its own
    justification — never implicit.
11. **`wake unverify <seed> <citing-id> [--reason "..."]` — first-class
    undo for a mistaken verification.** This session needed exactly this
    when an agent misread a bulk go-ahead and auto-verified 13 works;
    recovery was a manual `.overrides.jsonl` backup-and-restore rather
    than a real command. Add `wake unverify` to remove one entry from
    `overrides.jsonl` and write a `verification_reverted` line to
    `evidence/log.md` (matching the ad hoc format used during this
    session's manual recovery) with the given reason. Batch-recovery
    variant for exactly this failure mode: `wake unverify --since
    <timestamp>` or `--last N`.

**Deferred, not sequenced into the batch above (still real, still
wanted, just not next):**

- `wake evidence --from-pdf <path> <citing-id>` — verify a human-supplied
  PDF actually matches the citing work's metadata (title fuzzy-match
  against extracted first-page text, author match, DOI-in-text where
  present) before copying it into the packet; refuse with a clear
  message on mismatch. Batch variant `wake evidence --from-pdf-dir
  <folder> <seed>` tries every PDF in a folder against every currently-
  provisional citing work; non-matches are left alone in the input
  folder and simply reported (not deleted, not moved) — the command is
  stateless, so pointing it at the same folder again just re-reports
  the same mismatches.
- `wake missing-pdfs <seed>` — read-only report of provisional citing
  works with no cached PDF and which fetch sources have already been
  exhausted, callable any time. Complements incremental surfacing during
  batch `wake fetch-pdf` runs (print each failure — DOI, title, sources
  tried — as it happens rather than only in an end-of-batch summary), so
  a human can start hunting down hard-to-find PDFs manually while the
  agent keeps working through the rest of the batch.
- `wake assess <seed>` (or `wake theme coverage <seed>`) — evidence-gap
  triage report run between `wake classify` and `wake fetch-pdf`:
  current theme evidence density, and which classified-but-unverified
  works look highest-value for each theme (by relationship + confidence
  + citation count) — so PDF-fetching effort gets prioritized rather
  than spent uniformly across every provisional work.
- Investigate Springer PDF page-count validation for false-negative
  failures — `curl`'s reported page count was observed to be wrong at
  least once against a real Springer PDF this session; the check should
  be loosened, replaced with a more reliable method, or removed for
  Springer specifically if it can't be trusted.
- Interactive review rendering polish — when presenting a citing work to
  the human pre-verify, include authors alongside title, and surface the
  dossier's per-quote text + page numbers inline (not just title +
  justification). Small template change to whatever the agent uses to
  render the pre-verify summary; the one-at-a-time confirmation pattern
  itself already works well and doesn't need a redesign, just this
  richer rendering.
- `wake narrative section audit <seed> <slug>` / `wake narrative audit
  <seed>` — semantic claim-vs-source check (already noted under Theme
  F1/F3's deferred list above; repeated here for visibility in this
  session's own notes). For each `[ref:...]`-marked sentence, load the
  referenced dossier(s) and have an LLM flag whether the sentence's
  claim is actually supported. Reports only, does not enforce; kept
  separate from `section confirm` so drafting is never blocked on LLM
  audit availability.
