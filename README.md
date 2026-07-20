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

## Where this is headed

The impact brief isn't the end product — it's the first thing you can
generate from the evidence `wake` accumulates. Every `wake evidence` call
writes one OKF-style concept document into a growing packet under
`wake-out/<seed>/evidence/`, and that packet keeps growing (and staying
put) across sessions rather than being scratch cache for a single brief.

It's shaped that way on purpose: a durable, quote-backed, page-cited
evidence base is the substrate a later generation pass — a one-paragraph
pitch, a slide/timeline of adoption, a fully-cited narrative for a tech
editor — can read *from*, instead of needing its own research pass. None
of those generators exist yet; see `BACKLOG.md` (Themes C, D, F, G) for
where they're headed.

## Design: explore-first, not autopilot

There is no single "run everything" command. `wake` provides thin,
JSON-emitting primitives — `resolve`, `citing`, `sample`, `describe`,
`classify`, `bake`, `status`, `cost`, `override` — that an agent composes
into a workflow: resolve and confirm the seed, sample a handful of citing
works, classify the sample and check with the human, review the estimated
cost to finish, then scale up. See
[`wake/skills/impact-analysis/SKILL.md`](wake/skills/impact-analysis/SKILL.md)
for the full recommended workflow — this is the primary way the tool is
meant to be used.

## Install

```bash
pip install -e ".[dev]"

# Optional: PDF abstract extraction (wake fill-abstract --from-pdf)
pip install -e ".[dev,pdf]"
```

## Quick Start (as an agent would run it)

```bash
export OPENAI_API_KEY=your-key
export OPENAI_BASE_URL=https://apps-stage.inside.anl.gov/argoapi/v1
export OPENALEX_MAILTO=you@example.com

wake --json config validate                             # setup check — run once per session
wake --json resolve "10.1145/1048935.1050189"           # confirm the seed
wake --json citing "10.1145/1048935.1050189" --sort cited-by
wake --json sample "10.1145/1048935.1050189" -n 10      # free — no LLM calls
wake --json classify "10.1145/1048935.1050189" --limit 10 --sort cited-by
wake --json status "10.1145/1048935.1050189"            # check cost before scaling
wake --json classify "10.1145/1048935.1050189"          # classify everything

# Optional: escalate high-value citing works with no recoverable abstract
wake --json gaps "10.1145/1048935.1050189" --min-cited-by 50
wake --json fetch-pdf "10.1145/1048935.1050189" <citing-id>
wake --json fill-abstract "10.1145/1048935.1050189" <citing-id> --from-pdf wake-out/.../pdfs/<citing-id>.pdf
wake --json classify "10.1145/1048935.1050189" --ids <citing-id> --force

wake --json bake "10.1145/1048935.1050189"

# Optional: full-text-verify a specific finding, then record the human's call
wake --json evidence "10.1145/1048935.1050189" <citing-id>
wake --json override "10.1145/1048935.1050189" <citing-id> \
  --relationship extends --justification "<quoted evidence>" \
  --verification-source evidence-dossier

# Output: wake-out/W2156077349/impact.md
```

Every command supports `--json` for machine-readable output (a stable
envelope: `{"wake_version", "command", "ok", "data"}` or `{"ok": false,
"error": {...}}`), and human-readable text otherwise.

## Commands

| Command | Purpose |
|---------|---------|
| `wake resolve <seed>` | Resolve seed → canonical OpenAlex work |
| `wake status <seed>` | Cached-artifact counts + estimated remaining cost — start here |
| `wake citing <seed>` | Fetch & cache all citing works (`--sort`, `--min-year`, `--limit`) |
| `wake sample <seed>` | Representative slice of citing works for review (free, no LLM) |
| `wake describe <seed>` | LLM one-paragraph contribution description |
| `wake classify <seed>` | LLM relationship classification (`--ids`, `--limit`, `--sort`, `--dry-run`, resumable) |
| `wake gaps <seed>` | Surface high-value citing works with no recoverable abstract (`--min-cited-by`, `-n/--limit`, `--no-auto-backfill-check`) |
| `wake fill-abstract <seed> <id>` | Manually resolve one via `--from-pdf` or `--text` |
| `wake fetch-pdf <seed> <id>` | Try to automatically acquire a PDF (OSTI, Semantic Scholar, Unpaywall, Springer, arXiv, optional CORE) |
| `wake evidence <seed> <id>` | Full-text verification: reads the whole PDF, proposes a relationship with quoted, page-cited passages |
| `wake theme create <seed> <slug>` | Write a combined-evidence theme doc (`--title`, `--summary`, `--citing-ids`); always draft |
| `wake theme confirm <seed> <slug>` | Human sign-off promoting a theme to confirmed; refuses unless all cited works are verified |
| `wake theme queue <seed>` | List theme citing-works still needing an evidence dossier, or needing re-review |
| `wake narrative outline create <seed>` | Plan the narrative's structure (`--components`, a JSON list) before drafting any prose |
| `wake narrative section create <seed> <slug>` | Draft one section's prose (`--title`, `--prose`, `--theme-slugs`); always draft |
| `wake narrative section confirm <seed> <slug>` | Human sign-off promoting a section to confirmed; refuses unless every referenced theme is currently confirmed |
| `wake narrative stitch <seed>` | Assemble the outline + every section into the top-level `narrative.md`; works on partial data |
| `wake bake <seed>` | Assemble `impact.md` + `impact.json` from whatever is classified so far |
| `wake override <seed> <id>` | Record a human-reviewed relationship correction (`--verification-source human-judgment\|evidence-dossier`) |
| `wake cost <seed>` | Estimated LLM token/cost usage so far |
| `wake show brief <seed>` | Print cached impact.md |
| `wake show metrics <seed>` | Print cached impact.json |
| `wake show top <seed>` | Top-evidence table (`-n`, default 10) |
| `wake config show/validate/init` | Configuration plumbing |
| `wake skill show` | Print the bundled SKILL.md |
| `wake skill export <path>` | Copy the skill directory to `path` (`--force` to overwrite non-empty) |

Most commands that write cache accept `--force` to bypass it and re-run.

Global flags: `--json`, `--work-dir DIR` (or `WAKE_WORK_DIR` env var),
`--verbose` (keep progress banners under `--json`).

## Seed ID Formats

| Format | Example |
|--------|---------|
| DOI | `10.1145/1048935.1050189` |
| arXiv ID | `2301.04567` |
| OpenAlex ID | `W2156077349` |
| Paper title | `"Parallel netCDF: A High-Performance Scientific I/O Interface"` |

## Output Layout

```
wake-out/<OpenAlex-ID>/
  seed.json               — resolved seed + LLM description
  citing.json             — all citing works (paginated, cached)
  classified.json         — per-citing-work relationship + evidence
  impact.json             — aggregated metrics
  impact.md               — the impact brief (notes coverage if partial)
  .state.json             — stage cache keys
  classify/               — per-work classification sidecars (resumable)
  .cost.jsonl             — per-LLM-call estimated token/cost log
  overrides.jsonl         — human-reviewed relationship overrides
  .manual_abstracts.jsonl — human/PDF-recovered abstracts (wake fill-abstract)
  pdfs/                   — locally-cached PDFs (wake fetch-pdf / wake evidence)
    <citing-id>.pdf         — the PDF itself
    <citing-id>.json        — its extracted text, cached (see below)
  evidence/               — full-text verification dossiers (wake evidence)
    <citing-id>.md          — human/agent-readable OKF concept document
    <citing-id>.json        — same finding, structured
    index.md                — OKF catalog: Verified / Pending Review, ranked
    log.md                  — OKF chronological log of every investigation
    themes/                 — combined-evidence syntheses (wake theme create)
      <slug>.md               — OKF concept doc citing several works' findings
      <slug>.json              — same theme, structured (status, citing_works)
      index.md                 — OKF catalog: Confirmed / Draft
  narrative/              — narrative drafting (wake narrative)
    outline.md              — planned section structure (wake narrative outline create)
    outline.json             — same, structured
    sections/
      <slug>.md               — one drafted section's prose (wake narrative section create)
      <slug>.json              — same section, structured (status, theme_slugs)
  narrative.md            — assembled narrative (wake narrative stitch); notes coverage if partial
```

## Relationship Classes

| Class | Meaning |
|-------|---------|
| `extends` | Directly extends the method/framework of the seed |
| `builds-on` | Builds a new system/tool on top of the seed |
| `uses-as-tool` | Uses the seed's software/tool/dataset as-is |
| `benchmarks` | Benchmarks against the seed as a baseline |
| `applies-to-domain` | Applies the seed's approach to a new domain |
| `related-infrastructure` | Complementary tooling in the same ecosystem, no direct dependency |
| `background-mention` | Cites as background/related work |

Every classification also carries an orthogonal `author_overlap` tag
(`true`/`false`, plus `overlapping_authors`): whether the citing work
shares an OpenAlex author ID with the seed — i.e. the original team
publishing a follow-on paper, not independent third-party adoption. This
is not a relationship class of its own; `extends` + `author_overlap:
true` and `extends` + `author_overlap: false` are both `extends`, just
different stories. Computed deterministically (ID-set intersection, no
LLM call) and surfaced in the brief as a `[SELF-EXTENSION — seed's own
team]` tag in "Strongest Evidence" plus a `self_extension_count` summary
line in "Nature of Impact."

## Abstract Recovery

~20% of citing works typically lack an OpenAlex abstract, forcing lower-
confidence title/venue-only classification. `wake` recovers most of these
automatically and lazily (only for works actually selected for
classification, never eagerly for the full citing set):

1. **Automatic backfill** (`classify` does this transparently): tries
   [OSTI](https://www.osti.gov) (DOE-funded work, via its `description`
   field), then [Semantic Scholar](https://www.semanticscholar.org)
   (broader coverage). Free, unauthenticated, no PDF dependency.
2. **Manual escalation** for high-value works that step 1 couldn't resolve:
   ```bash
   wake gaps <seed>                          # surface candidates, ranked by influence
   wake fill-abstract <seed> <id> --from-pdf paper.pdf   # extract from PDF lead pages + LLM cleanup
   wake fill-abstract <seed> <id> --text "..."           # or paste the abstract directly
   wake classify <seed> --ids <id> --force   # re-classify with the recovered abstract
   ```
   `--from-pdf` only ever reads the first few pages (config
   `pdf_extract.max_pages`, default 3) — if the abstract isn't in the front
   matter, it isn't reported as found. Requires the `pdf` extra
   (`pip install 'wake[pdf]'`).

Recovered abstracts are tagged with their source (`abstract_source`:
`osti`, `semanticscholar`, `pdf-extract`, or `human-text`) and the count is
shown in the brief's Reach section.

## PDF Acquisition

```bash
wake fetch-pdf <seed> <citing-id>
```

Tries a chain of open-access sources, mostly API-based (no scraping
publisher landing pages, no sci-hub-style sources), and saves the first
valid PDF to `wake-out/<seed>/pdfs/<citing-id>.pdf`:

1. **OSTI** — direct `fulltext` link (DOE-funded work, no auth wall)
2. **Semantic Scholar** — `openAccessPdf.url` (often a repository/arXiv copy)
3. **Unpaywall** — best-OA-location PDF URL (frequently blocked by
   publisher sites — still worth attempting)
4. **Springer** — predictable `link.springer.com/content/pdf/<DOI>.pdf`
   URL for Springer DOIs; no API call, just a direct download attempt.
   Often succeeds for older LNCS conference chapters that Unpaywall/OSTI/S2
   don't index; a no-op for non-Springer DOIs.
5. **arXiv** — title-search match (always freely downloadable when found)
6. **CORE.ac.uk** — optional, requires `CORE_API_KEY`, silently skipped if unset

A downloaded file that isn't a valid PDF (e.g. a paywall HTML page saved
with a `.pdf` extension) is rejected and the chain falls through to the
next source. If every source fails, `fetch-pdf` returns human-actionable
links instead of giving up silently: an Unpaywall lookup page, a Google
Scholar search for the title, the publisher's DOI link, and a CORE.ac.uk
search URL.

Reusable on its own (e.g. before `wake fill-abstract --from-pdf`, to skip
a manual download step) and cached — re-running is a no-op unless `--force`
is passed.

## Verification Lifecycle (provisional → proposed → verified)

`classify` only ever reads a citing work's title/abstract/venue — never
the actual paper — so every classification it produces is labeled
`"verification_status": "provisional"`: a placeholder guess, not a
finding, regardless of how high its confidence score looks.

```bash
wake evidence <seed> <citing-id>
```

`wake evidence` fetches a PDF (same chain as `fetch-pdf`), reads the
*entire* document, and independently judges the relationship — quoting
full paragraphs verbatim, with page numbers, for every claim it makes. It
never fabricates a passage: if the seed paper isn't actually discussed in
the text, it says so and returns an empty quote list rather than
inventing evidence. The result is a `"proposed"` finding, written to an
OKF-style dossier (`wake-out/<seed>/evidence/<citing-id>.md`) — but it is
**never auto-applied**. Only a human-approved `wake override` call
promotes a finding to `"verified"`:

```bash
wake override <seed> <citing-id> --relationship extends \
  --justification "<quoted evidence>" --verification-source evidence-dossier
```

The baked brief tags every entry accordingly:
`[PROVISIONAL — abstract-only, not yet checked against full text]`,
`[VERIFIED via full-text reading]`, or `[VERIFIED via human judgment]`
(a plain override with no dossier behind it), plus a one-line
provisional/verified count summary in "Nature of Impact."

This tool never asks a human to run a CLI command themselves — an agent
using `wake` always presents a `wake evidence` finding (pasting the
literal quoted passages, in context) and runs the resulting `override`
call on the human's behalf. See `SKILL.md` for the full workflow.

Full-text extraction is page-level only (no MinerU, no paragraph-boundary
detection — multi-column academic layouts don't extract reliably enough
for that); the LLM is asked to quote the full containing paragraph
verbatim around any passage it relies on. Requires the `pdf` extra
(`pip install 'wake[pdf]'`), same as `fill-abstract --from-pdf`.

### The evidence wiki (`index.md` / `log.md`)

Every dossier is also a node in a small OKF-style wiki, maintained
automatically — no separate command to run. `wake-out/<seed>/evidence/index.md`
is a standing catalog of every investigated citing work, grouped
**Verified** / **Pending Review** and ranked within each group by the same
relationship-strength × reach score the brief uses for "Strongest
Evidence." `evidence/log.md` is the full chronological history: every
dossier built or rebuilt, every failed investigation (no PDF found,
extraction produced no text), and every human verification, newest at
the bottom.

Both regenerate as a side effect of `wake evidence` (fresh build or
`--force` rebuild — never on a cache hit) and `wake override
--verification-source evidence-dossier` (which also flips the matching
dossier from `pending-human-review` to `verified` in place). A plain
`--verification-source human-judgment` override has no dossier behind it
and leaves the wiki untouched. Re-running `wake evidence --force` on an
already-verified dossier resets it back to `pending-human-review` — a
fresh full-text read is a new finding, not a continuation of the old
sign-off.

### Thematic synthesis (`wake theme`)

When several citing works together support a broader claim (e.g.
"extensive use in Earth system modeling"), synthesize them into one
document instead of listing them separately:

```bash
wake theme create <seed> earth-system-modeling \
  --title "Extensive use in Earth system modeling" \
  --summary "<synthesis paragraph you write, having read the underlying findings>" \
  --citing-ids W111,W222,W333
```

This is a pure write primitive — no LLM call. You (the agent) decide
which works belong together and write the synthesis after reading their
dossiers/classifications yourself; `wake` validates and persists that
judgment, the same way `wake override` persists a relationship judgment
without making one. Always overwrites (no `--force` needed — there's no
expensive call to protect against re-doing).

A theme carries **two independent verification tracks**, since it makes
two different kinds of claim:

- Each **cited work** keeps its own honest, existing status
  (`[PROVISIONAL]` / `[PROPOSED]` / `[VERIFIED]`) — creating a theme never
  upgrades a work's relationship status.
- The **theme's synthesis itself** starts `draft` and can only be
  promoted to `confirmed` via a human-approved sign-off:
  ```bash
  wake theme confirm <seed> earth-system-modeling
  ```
  Confirmation **refuses unless every cited work is already
  human-verified** (via `wake override`) — a theme can never appear
  settled while resting on unverified findings. Run by the agent on the
  human's behalf, same as `wake override`.

Works with no evidence dossier yet can still be included in a draft
theme (mixed sourcing) — track outstanding work with:
```bash
wake theme queue <seed>
```
which lists, per theme, citing works still needing a `wake evidence`
dossier, and works whose dossier has since appeared but hasn't been
reviewed and re-asserted (re-run `wake theme create` with the same slug
after reading the new dossier — its full-text finding may not actually
support the thematic claim the way the abstract-only guess did).

### Narrative drafting (`wake narrative`)

Once you have one or more confirmed themes, draft a narrative from them —
one component at a time, then assemble:

```bash
wake narrative outline create <seed> --components '[
  {"slug":"intro","title":"Introduction","kind":"free"},
  {"slug":"earth-adoption","title":"Adoption in Earth System Modeling","kind":"theme","theme_slugs":["earth-system-modeling"]},
  {"slug":"conclusion","title":"Conclusion","kind":"free"}
]'
```

The outline is a plan, not a claim — it can be freely revised, and
referenced themes don't need to be confirmed yet (only at section-confirm
time). Then draft each section's prose, having read the underlying
theme(s)/dossiers yourself:

```bash
wake narrative section create <seed> earth-adoption \
  --title "Adoption in Earth System Modeling" \
  --prose "<the paragraph you write, grounded in the theme's confirmed findings, each factual sentence ending with [ref:ID,ID,...]>" \
  --theme-slugs earth-system-modeling
```

Like `wake theme create`, this is a pure write primitive — no LLM call.
Every section starts `draft`.

End every factual sentence with a `[ref:ID,...]` marker naming its
source(s) — `SEED` for the seed paper, or a citing work's OpenAlex ID.
`wake` refuses the whole call if any marker names an ID that isn't
`SEED` or isn't currently human-verified for this seed, and refuses
outright if the packet itself is inconsistent (a work `overrides.jsonl`
calls verified but has no dossier file on disk). This guarantees every
citation points at a real, checked source — it does not, by itself,
guarantee the source actually supports that sentence, which stays a
judgment call for you and the human. Framing sentences with no factual
content don't need a marker.

Promote a section after human sign-off:

```bash
wake narrative section confirm <seed> earth-adoption
```

For a theme-backed section, confirmation **refuses unless every
referenced theme is currently confirmed** — re-checked fresh, so a theme
later reopened to draft (e.g. a new unverified work added to it) is
caught rather than silently ignored. A section can reference multiple
themes if it synthesizes across them. Free-form sections (`kind: free`,
no `--theme-slugs` — e.g. an intro or conclusion) go through the same
draft → confirmed lifecycle, since framing prose can still make claims
worth a human's eye, but confirm immediately since there's no theme to
check.

Once you're satisfied with the sections drafted so far, assemble them:

```bash
wake narrative stitch <seed>
```

`narrative.md` is written from whatever exists — like `wake bake`, it
works on partial data. Sections not yet drafted are shown as a
placeholder with the exact command to draft them; drafted-but-unconfirmed
sections are shown with a `⚠ DRAFT` banner rather than presented as
final. A top-of-file note flags the whole document as a "Partial
narrative" whenever anything is missing or still draft, so a partially
assembled file is never mistaken for a finished one.

Stitching also renumbers every `[ref:ID,...]` marker into `[R1]`, `[R2]`,
... in reading order (the same source cited twice keeps one number), and
appends a Chicago-style `## References` list at the bottom — one entry
per distinct source, with a DOI link where available. This renumbering
only happens at stitch time, once the whole document exists; every
per-section preview file keeps the raw `[ref:...]` form.

### Inspecting what the model actually read

Every extraction is cached next to the PDF it came from:
`wake-out/<seed>/pdfs/<citing-id>.json` (a sibling of `<citing-id>.pdf`),
keyed by the PDF file's sha256 so a re-fetched PDF invalidates it
automatically. If a `wake evidence` finding looks wrong, you can open
this file directly — no need to re-run anything — and check whether the
extraction itself was garbled (a common failure mode with multi-column
academic layouts) before concluding the model's *reasoning* was at
fault. The dossier's "Source" section always links to this file. `wake
evidence --force` re-runs extraction too (not just the LLM verification
pass), so a bad extraction can be retried even when the PDF itself
hasn't changed.

## Cost Telemetry (estimate-only)

`wake` does not depend on the LLM endpoint reporting token usage. Every
`describe`/`classify` call records a char-count-based token estimate to
`.cost.jsonl`. Unpriced models (no rate configured) report `cost_usd_est:
0.0` with `unpriced: true` rather than guessing. Add real rates under
`cost.rates_per_1k_usd` in config as they become known.

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

## Tests

```bash
# Offline only
pytest tests/ -m 'not network'

# Including live network tests
pytest tests/
```

## License

BSD 3-Clause. Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
