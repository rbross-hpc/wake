# Trust Model: Where Hallucinations Can (and Can't) Enter

`wake`'s core design premise is separating *what an LLM guessed* from
*what has actually been checked* (see the top-level `README.md`). This
page maps that boundary exhaustively: every point where model output
enters the workflow, the structural gates that contain it before it can
reach a human as a settled claim, and the parts of the pipeline that
involve no model at all and so carry no hallucination risk.

## The three LLM call sites — the hallucination surface

This is the complete list. Every other command in `wake` makes no model
call.

- **`wake describe`** (`describe.describe_seed`) — one paragraph
  summarizing the seed's contribution, grounded in its abstract and (if
  acquired) an excerpt of the seed's own PDF text. Purely descriptive:
  its output feeds no downstream classification, scoring, or
  verification logic, so an inaccurate description can mislead a reader
  but can't propagate into a "finding."
- **`wake classify`** — reads a citing work's *title/abstract/venue
  only* (never the full paper) and emits a relationship label,
  confidence, and justification. This is the highest-volume LLM surface
  and the least-grounded one. Every result is stamped
  `"verification_status": "provisional"` — see
  [`evidence.md`](evidence.md) for the full lifecycle this triggers.
- **`wake evidence`** — reads the citing work's *entire extracted PDF
  text* and independently judges the relationship, quoting passages
  verbatim with page numbers. Better grounded than `classify` (full text,
  not just an abstract), but carries two distinct residual risks: the
  model's relationship judgment can still be wrong, and — more subtly —
  a quoted passage is a *string the model asserts appears in the source*,
  not something `wake` itself verifies character-for-character (see
  "Known limitation" below).
- **`wake fill-abstract --from-pdf`** — a small, narrowly-scoped LLM call
  that pulls an abstract from a PDF's front matter when OpenAlex has none.
  Minor in isolation, but its output feeds back into `classify`, so an
  inaccurate recovered abstract can propagate the same way a bad OpenAlex
  abstract would.

## The containment structure — why none of this reaches a human unchecked

- **provisional → proposed → verified.** `classify` output is always
  `provisional`; `evidence` output is always `proposed`. Neither state is
  ever treated as settled anywhere else in the codebase. The *only* path
  to `verified` is a human-approved `wake override` call, always run by
  the agent on the human's behalf, never by the human directly — see
  [`evidence.md`](evidence.md).
- **`wake theme confirm` and `wake timeline period confirm` both refuse
  to promote unless every cited/highlighted work is already `verified`**,
  re-checked fresh at confirm time rather than trusted from a
  possibly-stale JSON snapshot. This means a confirmed theme and a
  confirmed timeline period — and therefore `timeline.json`, the
  confirmed-only handoff to a graphic-rendering tool — rest only on
  human-checked evidence, never on an LLM's classification guess alone.
  See [`themes.md`](themes.md) and [`timeline.md`](timeline.md).
- **`wake narrative section create` refuses any `[ref:...]` marker** that
  names an ID other than `SEED` or a currently human-verified citing
  work. A narrative can cite a real, checked source or the seed itself —
  never a still-provisional, LLM-only claim. See
  [`narrative.md`](narrative.md).

## What is *not* a hallucination surface

Everything that renders the wiki's Markdown makes **no LLM or network
call** — see `build.py`'s module docstring. This includes `wake bake`,
`wake rebuild`, every `rerender_*`/`stitch` function, `wake assess`, and
`wake timeline candidates`. Scores, rankings, year-bucketing,
Chicago-style reference entries, and every coverage count are computed
mechanically from fields already persisted in JSON — there is no
generative step between "data on disk" and "Markdown on screen."

The `wake narrative refs-check` integration deserves a specific
callout since it's easy to assume otherwise: translating the stitched
narrative's References list into `refs.json`, and later folding a
`ref-checker` results file back into a human-facing summary, involves
no model call in either direction — both are plain field-shuffling over
data already in `classified.json`. See "Verifying the References list
against live scholarly databases" in [`narrative.md`](narrative.md).

## A related but distinct risk: data provenance, not hallucination

Two failure modes look similar to a hallucination but have a different
root cause and a different fix:

- **Bibliographic metadata** (author names, year, venue, DOI, citation
  counts) comes from **OpenAlex**, not from an LLM. An error here is a
  data-quality problem in an upstream source, not a model invention —
  the fix is the external `ref-checker` tool
  (`wake narrative refs-check export`/`summarize`, see
  [`narrative.md`](narrative.md)), a deterministic cross-check against
  live scholarly databases, not tighter model prompting.
- **PDF extraction fidelity.** `wake evidence`'s full-text reading is
  only as good as the page-tagged text extracted from the PDF; a garbled
  multi-column academic layout can produce a bad extraction that then
  causes the model to reason over corrupted input — a problem that
  *looks* like a hallucination in the dossier but actually originates
  before the model ever runs. Every dossier's "Source" section links to
  the cached extraction (`extracted_text_path`) specifically so this can
  be ruled in or out before doubting the model's reasoning — see
  "Inspecting what the model actually read" in
  [`evidence.md`](evidence.md).

## Known limitation

`wake evidence`'s quoted passages are strings the model asserts are
verbatim from the source text. `wake` stores the page number and the raw
extraction alongside every quote, which lets a human check a quote by
hand, but it does not currently **programmatically** verify that each
quoted string actually appears in the extracted text before writing the
dossier. That check is left to the human reviewer today. Closing this
gap — a deterministic substring/fuzzy-match guard between a dossier's
quotes and its `extracted_text_path` — is a plausible future
hardening step, not something currently built.
