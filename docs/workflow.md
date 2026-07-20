# Workflow

## Design: explore-first, not autopilot

There is no single "run everything" command. `wake` provides thin,
JSON-emitting primitives — `resolve`, `citing`, `sample`, `describe`,
`classify`, `bake`, `status`, `cost`, `override` — that an agent composes
into a workflow: resolve and confirm the seed, sample a handful of citing
works, classify the sample and check with the human, review the estimated
cost to finish, then scale up. See
[`wake/skills/impact-analysis/SKILL.md`](../wake/skills/impact-analysis/SKILL.md)
for the full recommended workflow — this is the primary way the tool is
meant to be used.

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
| `wake dedup candidates <seed>` | Scan for likely-duplicate citing works (title similarity + shared authors) |
| `wake dedup confirm <seed> <dup-id> <canonical-id>` | Record a human-confirmed duplicate; excluded from bake/theme/narrative thereafter |
| `wake dedup reject <seed> <id-a> <id-b>` | Record that a candidate pair is genuinely distinct, not a duplicate |
| `wake posters candidates <seed>` | Scan for likely posters/conference-abstracts (`type: conference-abstract` or a `Poster:`/`Abstract:` title prefix) |
| `wake posters keep <seed> <id> --reason "..."` | Record that a flagged candidate should be kept as-is, not excluded |
| `wake exclude <seed> <id> --reason "..."` | Record an explicit, permanent exclusion; refused by theme/narrative, dropped from bake, hidden from gaps/theme-queue |
| `wake unexclude <seed> <id> --reason "..."` | Reverse a prior exclusion |
| `wake fill-abstract <seed> <id>` | Manually resolve one via `--from-pdf` or `--text` |
| `wake fetch-pdf <seed> <id>` | Try to automatically acquire a PDF (OSTI, Semantic Scholar, Unpaywall, Springer, arXiv, optional CORE) |
| `wake evidence <seed> <id>` | Full-text verification: reads the whole PDF, proposes a relationship with quoted, page-cited passages |
| `wake theme create <seed> <slug>` | Write a combined-evidence theme doc (`--title`, `--summary`, `--citing-ids`); always draft |
| `wake theme confirm <seed> <slug>` | Human sign-off promoting a theme to confirmed; refuses unless all cited works are verified |
| `wake theme queue <seed>` | List theme citing-works still needing an evidence dossier, or needing re-review |
| `wake theme show <seed> <slug>` | Print an already-written theme document |
| `wake narrative outline create <seed>` | Plan the narrative's structure (`--components`, a JSON list) before drafting any prose |
| `wake narrative outline show <seed>` | Print the current narrative outline |
| `wake narrative section create <seed> <slug>` | Draft one section's prose (`--title`, `--prose`, `--theme-slugs`); always draft |
| `wake narrative section confirm <seed> <slug>` | Human sign-off promoting a section to confirmed; refuses unless every referenced theme is currently confirmed |
| `wake narrative section show <seed> <slug>` | Print one already-drafted section's prose |
| `wake narrative stitch <seed>` | Assemble the outline + every section into the top-level `narrative.md`; works on partial data |
| `wake narrative show <seed>` | Print the assembled top-level `narrative.md` |
| `wake narrative refs-check export <seed>` | Write `narrative/refs.json` for the external `ref-checker` tool |
| `wake narrative refs-check summarize <seed> <results.json>` | Summarize a `ref-checker` results sidecar into OK/flagged counts |
| `wake bake <seed>` | Assemble `impact.md` + `impact.json` from whatever is classified so far |
| `wake override <seed> <id>` | Record a human-reviewed relationship correction (`--verification-source human-judgment\|evidence-dossier`) |
| `wake unverify <seed> <id> --reason "..."` | Reverse a mistaken verification; also `--since <timestamp>`/`--last N` for batch recovery |
| `wake cost <seed>` | Estimated LLM token/cost usage so far |
| `wake show brief <seed>` | Print cached impact.md |
| `wake show metrics <seed>` | Print cached impact.json |
| `wake show top <seed>` | Top-evidence table (`-n`, default 10) |
| `wake show dossier <seed> <id>` | Print an already-built evidence dossier for one citing work |
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
