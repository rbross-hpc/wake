# wake — Command & Output Reference

Detailed reference material for the `wake` CLI, split out from `SKILL.md`
(which stays focused on the explore-first workflow). See `SKILL.md` first
for how and when to use these.

## Seed ID Formats

| Format | Example |
|--------|---------|
| DOI | `10.1145/1048935.1050189` |
| arXiv ID | `2301.04567` |
| OpenAlex ID | `W2156077349` |
| Paper title | `"Parallel netCDF: A High-Performance Scientific I/O Interface"` |

## Full Command List

```bash
# Explore-first pipeline (see SKILL.md for sequencing/guidance)
wake --json resolve "<seed>"
wake --json citing "<seed>" [--sort cited-by|recent|oldest|random] [--min-year Y] [--limit N]
wake --json sample "<seed>" [-n N] [--sort ...]
wake --json classify "<seed>" [--ids ID,ID,...] [--limit N] [--sort ...] [--dry-run] [--force]
wake --json gaps "<seed>" [--min-cited-by N] [--no-auto-backfill-check]
wake --json fetch-pdf "<seed>" <citing-id> [--force]
wake --json fill-abstract "<seed>" <citing-id> --from-pdf PATH | --text TEXT
wake --json evidence "<seed>" <citing-id> [--force]
wake --json render "<seed>"
wake --json override "<seed>" <citing-id> --relationship <class> --justification "..." [--verification-source human-judgment|evidence-dossier]

# Standalone
wake --json describe "<seed>"      # LLM contribution paragraph (independent of classify)
wake --json cost "<seed>"          # cumulative estimated token/cost usage
wake --json show brief "<seed>"    # re-print cached impact.md
wake --json show metrics "<seed>"  # re-print cached impact.json
wake --json show top "<seed>" -n N # top-evidence table only
wake config show / validate / init
wake skill show / export PATH
```

Note: `--json` must appear before the subcommand (global flag), e.g.
`wake --json classify "<seed>"`, not `wake classify "<seed>" --json`.

Global flags: `--json`, `--work-dir DIR` (or `WAKE_WORK_DIR` env var, falls
back to cwd), `--verbose` (keep progress banners on stderr even under `--json`).

## Relationship Classes

Ordered by strength, strongest first:

| Class | Meaning |
|-------|---------|
| `extends` | Directly extends the method/framework/theory of the seed |
| `builds-on` | Builds a new system/tool that depends on the seed |
| `uses-as-tool` | Uses the seed's software/tool/dataset as-is |
| `benchmarks` | Benchmarks against the seed as a baseline |
| `applies-to-domain` | Applies the seed's approach to a new domain |
| `related-infrastructure` | Complementary tooling in the same ecosystem, no direct dependency |
| `background-mention` | Cites only as background/related work (including unclear/indirect relationships) |

### Author-Overlap Tag (orthogonal to relationship)

Every `classify` and `evidence` result also carries `author_overlap`
(bool) + `overlapping_authors` (list of names) — computed deterministically
by intersecting OpenAlex author IDs between the seed and citing work, no
LLM call. Not a relationship class of its own: `extends` +
`author_overlap: true` (the original team's own follow-on paper) and
`extends` + `author_overlap: false` (an independent third-party
extension) are both still `extends`, just different stories for a
narrative. Surfaced in the brief as a `[SELF-EXTENSION — seed's own
team]` tag in "Strongest Evidence" and a `self_extension_count` summary
line in "Nature of Impact" (`impact.json`).

## PDF Acquisition Chain (`wake fetch-pdf`)

Tried in order, all API-based (no scraping publisher landing pages, no
sci-hub-style sources):

1. **OSTI** — direct `fulltext` link (DOE-funded work, no auth wall)
2. **Semantic Scholar** — `openAccessPdf.url` (often a repository/arXiv copy)
3. **Unpaywall** — best-OA-location PDF URL (frequently blocked by
   publisher sites; still worth attempting)
4. **arXiv** — title-search match (always freely downloadable when found)
5. **CORE.ac.uk** — optional, requires `CORE_API_KEY`, silently skipped if unset

A downloaded file that isn't a valid PDF (e.g. a paywall HTML page saved
with a `.pdf` extension) is rejected and the chain falls through. On total
failure, returns human-actionable links: Unpaywall lookup page, Google
Scholar search for the title, publisher DOI link, CORE.ac.uk search URL.

## Verification Lifecycle (provisional → proposed → verified)

| Status | Set by | Meaning |
|---|---|---|
| `provisional` | `classify` (always, unconditionally) | Abstract/title-only guess — a placeholder, not a finding |
| `proposed` | `wake evidence` (full-text LLM read) | What the paper's actual text shows, with quoted passages — not yet human-approved |
| `verified` | `wake override` (agent-run, after human sign-off) | Settled — a human reviewed and accepted it |

`wake evidence "<seed>" <citing-id>` response shape:
```json
{
  "ok": true,
  "data": {
    "ok": true,
    "dossier_path": "wake-out/<seed>/evidence/<citing-id>.md",
    "dossier_json_path": "wake-out/<seed>/evidence/<citing-id>.json",
    "pdf_path": "wake-out/<seed>/pdfs/<citing-id>.pdf",
    "pdf_source": "semanticscholar",
    "extracted_text_path": "wake-out/<seed>/pdfs/<citing-id>.json",
    "provisional": {"relationship": "uses-as-tool", "confidence": 0.4, "justification": "..."},
    "proposed": {
      "relationship": "extends",
      "confidence": 0.9,
      "justification": "...",
      "agrees_with_provisional": false
    },
    "quotes": [
      {"page": 4, "text": "<full paragraph, verbatim>", "note": "<what this shows>"}
    ]
  }
}
```
On failure to acquire a PDF: `{"ok": false, "reason": "no_pdf", "fetch_result": {...}}`
(same shape as `fetch-pdf`'s failure — includes `fallback_links`).

`wake evidence` never calls `wake override` itself — it only proposes.
Promotion to `verified` always requires an explicit `wake override` call
(run by the agent, per SKILL.md step 9-10), optionally tagged
`--verification-source evidence-dossier` to record that the override
followed a dossier rather than an unaided human judgment.

When `--verification-source evidence-dossier` is used, `wake override`
also patches the matching dossier (`pending-human-review` → `verified`,
in both its `.md` and `.json`) and regenerates `evidence/index.md`/
`log.md` — no separate step needed. A plain `--verification-source
human-judgment` override (no dossier behind it) leaves the wiki
untouched. Re-running `wake evidence --force` on an already-verified
dossier resets it back to `pending-human-review` — a fresh full-text read
is a new finding, not a continuation of the old sign-off.

### Diagnosing a surprising finding: check the extraction first

`extracted_text_path` (also linked from the dossier's "Source" section)
points at the raw page-tagged text the LLM was actually given — cached
next to the PDF (`wake-out/<seed>/pdfs/<citing-id>.json`), keyed by the
PDF's sha256 so a re-fetched PDF invalidates it automatically. If a
`proposed` finding looks implausible, read this file **before** concluding
the model reasoned poorly — multi-column academic layouts are a known
source of garbled extraction (see PDF Acquisition notes above), and a bad
extraction looks very different from a bad inference once you see the raw
text. `wake evidence --force` re-runs extraction too, not just the LLM
call, so a garbled extraction can be retried without needing a fresh PDF.

## Output Layout

```
wake-out/<OpenAlex-ID>/
  seed.json               — resolved seed + LLM description
  citing.json             — all citing works (paginated, cached)
  classified.json         — per-citing-work relationship + evidence
                             (verification_status: "provisional" by default)
  impact.json             — aggregated metrics (includes verified_count)
  impact.md               — the impact brief (notes coverage if partial;
                             per-entry [PROVISIONAL]/[VERIFIED via ...] tags)
  .state.json             — stage cache keys
  .classify/              — per-work classification sidecars (resumable)
  .cost.jsonl             — per-LLM-call estimated token/cost log
  .overrides.jsonl        — human-reviewed relationship overrides
                             (verification_status: "verified")
  .manual_abstracts.jsonl — human/PDF-recovered abstracts (wake fill-abstract)
  pdfs/                   — locally-cached PDFs (wake fetch-pdf / wake evidence)
    <citing-id>.pdf         — the PDF itself
    <citing-id>.json        — its extracted text, cached (pdf_sha256-keyed;
                               see Diagnosing a surprising finding, above)
  evidence/                — full-text verification dossiers (wake evidence)
    <citing-id>.md          — OKF concept document (human/agent-readable)
    <citing-id>.json        — same finding, structured (for programmatic reuse)
    index.md                — OKF catalog: Verified / Pending Review, ranked
                               by score; regenerated automatically, no command
    log.md                  — OKF chronological log of every investigation
                               (built, rebuilt, failed, verified); append-only
```

Use `--work-dir DIR` (or `WAKE_WORK_DIR` env var) to control where
`wake-out/` is created — useful when running from a scratch directory.

## Environment Variables

`wake --json config validate` returns all three tiers' set/unset status in
one call (see SKILL.md step 0) — that's the canonical way an agent should
check these, rather than re-deriving this table.

| Tier | Variable | Purpose |
|------|----------|---------|
| Required | `OPENAI_API_KEY` | LLM API key (required for describe/classify) |
| Required | `OPENAI_BASE_URL` | API endpoint (e.g. Argo) |
| Recommended | `OPENALEX_MAILTO` | Your email for OpenAlex/Unpaywall/OSTI polite pool |
| Optional | `SEMANTICSCHOLAR_API_KEY` | Raises Semantic Scholar's unauthenticated rate limit |
| Optional | `CORE_API_KEY` | Enables CORE.ac.uk in `wake fetch-pdf` (free key at core.ac.uk/services/api) |
| Optional | `WAKE_WORK_DIR` | Default root for `wake-out/` cache |

`wake --json config validate` response shape:
```json
{
  "ok": true,
  "data": {
    "ok": true,
    "errors": [],
    "env": {
      "required": {"OPENAI_API_KEY": {"set": true, "value": null, "description": "..."}, ...},
      "recommended": {"OPENALEX_MAILTO": {"set": true, "value": "you@example.com", "description": "..."}},
      "optional": {"SEMANTICSCHOLAR_API_KEY": {"set": false, "value": null, "description": "..."}, ...}
    }
  }
}
```
Sensitive vars (anything with `KEY` in the name) never include their
actual value, even when set — only `"set": true/false`.
