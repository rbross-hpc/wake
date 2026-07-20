# Narrative Drafting (`wake narrative`)

Once you have one or more confirmed themes (see [`themes.md`](themes.md)),
draft a narrative from them — one component at a time, then assemble:

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

`wake narrative outline show <seed>`, `wake narrative section show <seed>
<slug>`, and `wake narrative show <seed>` re-print the outline, one
section, and the assembled document, respectively, as-is.

## Verifying the References list against live scholarly databases

`wake narrative refs-check` shells out to the external
[`ref-checker`](https://github.com/rbross-hpc/ref-checker) tool to
independently check each reference's bibliographic details (author
spelling, year, DOI) against OpenAlex, CrossRef, OSTI, DBLP, Semantic
Scholar, and arXiv — a different question from what `[ref:...]`
validation already guarantees (that the source is real and human-
verified for this seed). `wake` never runs `ref-checker` itself:

```bash
wake narrative refs-check export <seed>
# -> wake-out/<seed>/narrative/refs.json

pipx install git+https://github.com/rbross-hpc/ref-checker.git   # once
ref-checker check --refs-json wake-out/<seed>/narrative/refs.json \
  --results-json wake-out/<seed>/narrative/refs.results.json

wake narrative refs-check summarize <seed> wake-out/<seed>/narrative/refs.results.json
```

`export` writes references numbered identically to `narrative.md`'s
`[R1]`/`[R2]`/... so a discrepancy `ref-checker` reports against index
`N` always maps back to `[RN]` in the document. `summarize` separates
the results into a clean-OK count and a flagged list — any
`CLOSEST`/`NO MATCH` status, plus an identifier-confirmed `OK` match
that still carries a note (year mismatch, dead URL, exhausted retries)
worth a second look.
