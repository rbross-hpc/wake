# BACKLOG — wake Phase 2: Evidence, Narrative & Wiki

Captures the roadmap discussed after the first full live run (Parallel netCDF,
408 citing works classified, complete impact.md reviewed). This is a
substantial expansion beyond wake's citation-classification core: an
evidence-digging, DOE-relevance-signal, and narrative-drafting layer, built
as an OKF-compliant knowledge wiki alongside the existing classify/render
pipeline.

Sequencing: **A + B first (foundation), then D (organization), then E
(small, high-value), F/G/H deferred** until we've used A/B/D/E for real and
know what's actually needed.

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
4. **arXiv** — conditional: if title/author search finds a matching arXiv
   preprint, download directly (always freely available, no bot-blocking).
5. **CORE.ac.uk** — optional, gated behind `CORE_API_KEY` env var (silently
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

## Theme C — Combined-Evidence / Thematic Documents

When several individual dossiers together support a broader claim (e.g.
"extensive use in Earth system modeling"), generate
`wake-out/<seed>/evidence/themes/<theme-slug>.md` — an OKF concept doc
synthesizing multiple dossiers, linking out to them rather than duplicating
content.

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
      index.md
      <theme-slug>.md   — Theme C combined-evidence docs (not yet built)
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
`impact.md` not existing until `wake render` and `.overrides.jsonl` not
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

## Deferred — Theme F: Narrative Drafting Tools

Four concrete use cases, roughly in dependency order:
- **F1** — Contribution narrative draft (problem / tool / differentiator),
  using seed abstract + Theme E-tagged self-extension papers.
- **F2** — Thematic impact bullet summary: cluster top-evidence into
  themes (essentially Theme C, directed at a specific narrative output).
- **F3** — Full cited narrative with per-sentence markdown links into
  Theme A2/B/C evidence docs, packaged into a folder (`narrative.md`
  top-level + `evidence/` + `evidence/themes/` + `data/` for JSON) —
  zippable for a tech editor.

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
