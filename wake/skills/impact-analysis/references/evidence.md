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
    "pdf_path": "/abs/path/to/wake-out/<seed>/pdfs/<citing-id>.pdf",
    "pdf_source": "semanticscholar",
    "extracted_text_path": "/abs/path/to/wake-out/<seed>/pdfs/<citing-id>.pdf.json",
    "provisional": {
      "relationship": "uses-as-tool", "confidence": 0.4, "justification": "...",
      "relationships": [{"label": "uses-as-tool", "confidence": 0.4, "justification": "..."}]
    },
    "proposed": {
      "relationship": "extends",
      "confidence": 0.9,
      "justification": "...",
      "agrees_with_provisional": false,
      "relationships": [
        {"label": "extends", "confidence": 0.9, "justification": "...", "quotes": [{"page": 4, "text": "...", "note": "..."}]}
      ]
    },
    "quotes": [
      {"page": 4, "text": "<full paragraph, verbatim>", "note": "<what this shows>"}
    ]
  }
}
```
`relationship`/`confidence`/`justification` are always the top
(most-confident) facet from `relationships` — read those scalars unless
you specifically need every facet. `quotes` at the top level is the
deduplicated union of every facet's own `quotes`, in facet order. See
`classify.md`'s "Multi-Facet Relationships" section for the full schema
and how to opt into it (`evidence.prompt_version: "evidence-2"`); by
default (`evidence-1`) `relationships` is always a single-element list.
`pdf_path`/`extracted_text_path` in this CLI response are always
absolute, ready to open directly. The `evidence/<citing-id>.json`
sidecar written to disk stores the same two paths *relative to its own
directory* instead (e.g. `"../pdfs/<citing-id>.pdf"`), so the wiki stays
self-consistent if `wake-out/<seed>/` is ever moved or shared — see
"Diagnosing a surprising finding" below.

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

For a multi-facet dossier, `--relationship` affirms exactly one facet at
a time: if it matches one of the dossier's existing facets, that facet
is flagged verified and the model's *other* facets are left in place,
untouched, as unaffirmed-but-still-evidenced alternative readings (a
paper can genuinely be both `uses-as-tool` and `applies-to-domain`; the
human affirming one doesn't make the other one wrong, just unconfirmed).
If `--relationship` names a facet the model never proposed (a genuine
correction), it's appended as a new verified facet, again without
deleting the model's original reading — it's still real evidence about
the text, just not the story the human is affirming. There's no way to
affirm two facets in a single `wake override` call; run it again with a
different `--relationship` if a human wants to affirm more than one.

## Re-printing an already-built dossier

`wake show dossier "<seed>" <citing-id>` prints the already-written
`evidence/<citing-id>.md` as-is, no computation -- same convention as
`wake show brief`/`metrics`/`top` for the seed-level artifacts:
```json
{"ok": true, "data": {"markdown": "..."}}
```
Errors (exit 1) with a message naming `wake evidence "<seed>" <citing-id>`
if no dossier exists yet.

## Supplying a manually-obtained PDF (`wake evidence --from-pdf`)

When `wake fetch-pdf` fails and a human hunts down a PDF manually, pass
it directly to `wake evidence` instead of copying it in yourself:

```bash
wake evidence "<seed>" <citing-id> --from-pdf /path/to/paper.pdf
```

Before copying the PDF into the packet, wake validates that it matches the
citing work's metadata using three signals:
- **Title similarity** — SequenceMatcher ratio of the citing work's title
  against the first ~800 characters of the extracted lead text (threshold
  ≥0.55, looser than dedup's 0.85 to account for noisy PDF extraction).
- **Author surname match** — at least one author surname appears in the
  lead text (whole-word, case-insensitive).
- **DOI in text** — the citing work's DOI appears literally in the lead
  text.

At least two signals must fire, and at least one of {title, DOI} must be
among them (author match alone is insufficient). If the check fails, wake
refuses to copy the file and returns an error with the signal breakdown.

If you're confident it's the right paper despite the check failing (e.g.
the title is truncated in the PDF or the DOI is only in the HTML landing
page), override the refusal:

```bash
wake evidence "<seed>" <citing-id> --from-pdf /path/to/paper.pdf --force
```

`--force` bypasses the *copy refusal* but the check still runs and the
mismatch is logged to `evidence/log.md` as `pdf_forced_despite_mismatch`
so there's always an audit trail. The dossier verification itself then
proceeds normally with the supplied PDF.

## Undoing a mistaken verification (`wake unverify`)

`wake unverify "<seed>" <citing-id> [--reason "..."]` response shape:
```json
{"ok": true, "data": {"ok": true, "citing_id": "W111", "reason": "...", "had_dossier": true, "reverted_at": "..."}}
```
Reverses a verification a human never actually reviewed/accepted (e.g.
an agent misreading a bulk go-ahead and auto-verifying works) -- a
separate, explicit action with its own reason, never an implicit side
effect of any other command. Removes the citing work's entry from
`overrides.jsonl` entirely (there's no "unverified" override shape to
append -- the only way a work stops being verified is to have no
override on file at all); if an evidence dossier exists for the work,
also patches it back from `verified` to `pending-human-review`
(undoing any relationship correction the reverted verification made,
restoring the dossier's `proposed` field to the model's own original
reading), writes a `verification_reverted` line to `evidence/log.md`,
and regenerates `evidence/index.md` so the work moves back to Pending
Review. Raises an error if `citing_id` was never verified in the first
place (nothing to undo).

Batch-recovery variant for exactly the failure mode this exists for --
an agent auto-verifies a run of works it shouldn't have:
```bash
wake unverify "<seed>" --since <ISO-8601 timestamp> --reason "..."
wake unverify "<seed>" --last N --reason "..."
```
Exactly one of `--since`/`--last` (mutually exclusive with a `citing-id`
positional and with each other) — `--since` reverts every override
recorded at or after that timestamp, `--last N` reverts the N
most-recently-recorded overrides. Response shape: `{"ok": true, "count":
N, "reverted": [{"ok": true, "citing_id": "...", ...}, ...]}`.

## Cross-links: the dossier's "Referenced by" line

Every dossier `.md` shows a `**Referenced by:**` line right after the
byline naming every theme and narrative section that currently cites
this work, e.g. `theme [PnetCDF's own evolution](themes/pnetcdf-
evolution.md); narrative section [...](../narrative/sections/....md)`.
It's omitted entirely for a work not (yet) pulled into any theme or
narrative section — most `background-mention` dossiers stay this way.

This is a derived view, recomputed at render time from the theme/section
JSON sidecars — nothing new to maintain by hand. It's kept fresh
automatically: `wake theme create`/`confirm` re-render every dossier
they cite, and `wake narrative section create`/`confirm` re-render every
dossier cited in the section's `[ref:...]` markers. If it ever looks
stale (e.g. after hand-editing a theme/section JSON directly, which you
shouldn't normally do), `wake evidence "<seed>" --rerender-all` rescans
every dossier and refreshes this line for all of them at once.

## Re-rendering every dossier (`wake evidence --rerender-all`)

```bash
wake --json evidence "<seed>" --rerender-all
```
Response shape: `{"ok": true, "data": {"ok": true, "rerendered": ["W111", "W222", ...], "count": N}}`.

A rendering-only pass over every `evidence/<citing-id>.json` sidecar
already on disk: no LLM call, no PDF fetch, no change to any dossier's
finding or verification status. Re-emits each `.md` from its `.json`,
recomputing derived content like the "Referenced by" line above. Use
this after a `wake` upgrade changes how dossiers render, to backfill an
existing wiki without re-running any expensive step. `citing_id` is
omitted (mutually exclusive with `--rerender-all`, `--force`, and
`--from-pdf`).

## Diagnosing a surprising finding: check the extraction first

The extraction cache — the raw page-tagged text the LLM was actually
given, cached next to the PDF (`wake-out/<seed>/pdfs/<citing-id>.pdf.json`),
keyed by the PDF's sha256 so a re-fetched PDF invalidates it
automatically — is where to look if a `proposed` finding looks
implausible. Read it **before** concluding the model reasoned poorly:
multi-column academic layouts are a known source of garbled extraction
(see `pdf-acquisition.md`), and a bad extraction looks very different
from a bad inference once you see the raw text. `wake evidence --force`
re-runs extraction too, not just the LLM call, so a garbled extraction
can be retried without needing a fresh PDF.

An agent reads `extracted_text_path` from the dossier's `.json` sidecar
(or from `build_dossier()`'s own return value) to get there
programmatically. A human reviewing the rendered dossier in Obsidian
instead clicks the "Raw extracted text" link under the dossier's
"## Source" heading — the one deliberate case where a wiki `.md` links
directly to a `.json` file, because the extraction cache is the only
artifact that answers "did the model see garbled text?" and there is no
separate human-readable rendering of it (see `output-layout.md`'s "File
format conventions").
