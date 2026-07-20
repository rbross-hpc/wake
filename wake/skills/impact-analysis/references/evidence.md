# Full-Text Verification (`wake evidence` / `wake override`)

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
(same shape as `fetch-pdf`'s failure — includes `fallback_links`). See
`pdf-acquisition.md` for the source chain.

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

## Re-printing an already-built dossier

`wake show dossier "<seed>" <citing-id>` prints the already-written
`evidence/<citing-id>.md` as-is, no computation -- same convention as
`wake show brief`/`metrics`/`top` for the seed-level artifacts:
```json
{"ok": true, "data": {"markdown": "..."}}
```
Errors (exit 1) with a message naming `wake evidence "<seed>" <citing-id>`
if no dossier exists yet.

## Diagnosing a surprising finding: check the extraction first

`extracted_text_path` (also linked from the dossier's "Source" section)
points at the raw page-tagged text the LLM was actually given — cached
next to the PDF (`wake-out/<seed>/pdfs/<citing-id>.json`), keyed by the
PDF's sha256 so a re-fetched PDF invalidates it automatically. If a
`proposed` finding looks implausible, read this file **before** concluding
the model reasoned poorly — multi-column academic layouts are a known
source of garbled extraction (see `pdf-acquisition.md`), and a bad
extraction looks very different from a bad inference once you see the raw
text. `wake evidence --force` re-runs extraction too, not just the LLM
call, so a garbled extraction can be retried without needing a fresh PDF.
