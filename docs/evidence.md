# Verification Lifecycle (provisional → proposed → verified)

`classify` only ever reads a citing work's title/abstract/venue — never
the actual paper — so every classification it produces is labeled
`"verification_status": "provisional"`: a placeholder guess, not a
finding, regardless of how high its confidence score looks. See
[`trust-model.md`](trust-model.md) for the complete map of every point an
LLM's output can enter the workflow and how each one is contained.

```bash
wake evidence <seed> <citing-id>
```

`wake evidence` fetches a PDF (same chain as `fetch-pdf`; see
[`pdf-sources.md`](pdf-sources.md)), reads the *entire* document, and
independently judges the relationship — quoting full paragraphs verbatim,
with page numbers, for every claim it makes. It never fabricates a
passage: if the seed paper isn't actually discussed in the text, it says
so and returns an empty quote list rather than inventing evidence. The
result is a `"proposed"` finding, written to the dossier's JSON sidecar
(`wake-out/<seed>/evidence/<citing-id>.json`) — the OKF-style `.md`
rendering of it is produced separately by `wake rebuild` (see "The
evidence wiki" below), not by this call. The finding is **never
auto-applied**. Only a human-approved `wake override` call promotes a
finding to `"verified"`:

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

If a work ends up verified without the human actually having reviewed
it — e.g. an agent misreading a bulk go-ahead — `wake unverify <seed>
<citing-id> --reason "..."` undoes it: removes the override entirely and,
if a dossier exists, reverts it back to `pending-human-review`. Batch
variants (`--since <timestamp>` / `--last N`) cover recovering from a
whole run of mistaken verifications at once.

Full-text extraction is page-level only (no MinerU, no paragraph-boundary
detection — multi-column academic layouts don't extract reliably enough
for that); the LLM is asked to quote the full containing paragraph
verbatim around any passage it relies on. Requires the `pdf` extra
(`pip install 'wake[pdf]'`), same as `fill-abstract --from-pdf`.

## The evidence wiki (`index.md` / `log.md`)

Every dossier is also a node in a small OKF-style wiki. `wake-out/<seed>/evidence/index.md`
is a standing catalog of every investigated citing work, grouped
**Verified** / **Pending Review** and ranked within each group by the same
relationship-strength × reach score the brief uses for "Strongest
Evidence." `evidence/log.md` is the full chronological history: every
dossier built or rebuilt, every failed investigation (no PDF found,
extraction produced no text), and every human verification, newest at
the bottom.

`log.md` is append-only and updated immediately by `wake evidence`/`wake
override`/`wake unverify` — but `index.md` and every dossier's own `.md`
are rendered only by `wake rebuild <seed>`, a separate explicit step, not
a side effect of those commands. `wake evidence`/`wake override
--verification-source evidence-dossier`/`wake unverify` all write their
JSON immediately (the dossier's `pending-human-review`/`verified` status
flip included) and return the data you need directly — run `wake rebuild
<seed>` afterward to bring the rendered `.md` files up to date. A plain
`--verification-source human-judgment` override has no dossier behind it
and leaves the evidence wiki untouched. Re-running `wake evidence
--force` on an already-verified dossier resets it back to
`pending-human-review` in the JSON — a fresh full-text read is a new
finding, not a continuation of the old sign-off.

## Inspecting what the model actually read

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
