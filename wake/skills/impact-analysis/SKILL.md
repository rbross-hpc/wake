# Agent Skill: wake — Impact Analysis

## Purpose

`wake` is an analysis instrument you (the agent) wield on the human's behalf.
It is **not** an autopilot — there is no single "do everything" command. You
compose thin primitives (`resolve`, `citing`, `sample`, `classify`, `gaps`,
`fetch-pdf`, `fill-abstract`, `render`, `status`, `cost`, `override`) into an
**explore-first workflow**, pausing at natural decision points so the human
can confirm the seed paper, review a sample of classifications, and approve
spend before you scale up.

Every command supports `--json` and returns a stable envelope:
```json
{ "wake_version": "...", "command": "...", "ok": true, "data": { ... } }
```
Use `--json` for everything you parse programmatically. Errors use
`"ok": false` with `{"error": {"type": ..., "message": ...}}` plus a non-zero
exit code.

For the full command list, output-file layout, environment variables, and
the PDF-acquisition source chain, see `references/reference.md`. This file
covers only the workflow — when to run what, and where to check in with
the human.

## The Workflow

Follow this sequence. **Do not skip straight to classifying everything** —
the whole point of this tool is that you explore before you spend.

### 0. Setup check (once per session, before the first `resolve`)

```bash
wake --json config validate
```

Read the structured result rather than just the pass/fail:

- **`ok: false`** (a required var is missing) — **stop**. Tell the human
  exactly which of `OPENAI_API_KEY`/`OPENAI_BASE_URL` is unset and why
  it's blocking (nothing in wake works without an LLM endpoint). Don't
  proceed to `resolve`.
- **`env.recommended.OPENALEX_MAILTO.set: false`** — ask the human for an
  email address once, briefly: *"I don't have an email set for the
  OpenAlex/Unpaywall/OSTI polite pool — faster and more reliable with one.
  What should I use?"* Not blocking; proceed either way, but ask before
  you start racking up unauthenticated API calls.
- **`env.optional.*`** (`SEMANTICSCHOLAR_API_KEY`, `CORE_API_KEY`,
  `WAKE_WORK_DIR`) — **do not ask about these upfront.** They're pure
  feature-gates for specific commands later in the workflow:
  - Only mention `SEMANTICSCHOLAR_API_KEY` if the analysis looks
    large-scale (hundreds of citing works) and abstract backfill speed
    will actually matter (step 4).
  - Only mention `CORE_API_KEY` right before `fetch-pdf`/`gaps` (step 7),
    and only as an FYI ("CORE.ac.uk isn't configured — I'll skip it as a
    PDF source unless you have a key") — never block on it.
  - Only ask about `WAKE_WORK_DIR`/`--work-dir` once, if the human hasn't
    indicated a preference and you're about to write the first cache file
    (step 2) — cwd is a fine default otherwise, don't make a big deal of it.

This check costs nothing (no network calls, no LLM spend) — always run it
first, but keep the human-facing part of it brief. Most of the time
there's nothing to report beyond "looks good."

### 1. Resolve and confirm

```bash
wake --json resolve "<seed>"
```

Show the human the resolved title/year/venue/OpenAlex ID. **Confirm this is
the paper they meant** before proceeding — title search can mismatch.

### 2. Fetch citing works and report scale

```bash
wake --json citing "<seed>" --sort cited-by
```

Report the total count to the human. If it's large (hundreds+), say so —
this is the point to discuss scope (e.g. `--min-year` to focus on recent
impact, or classifying only the most-cited works).

### 3. Sample before spending

```bash
wake --json sample "<seed>" -n 10 --sort cited-by
```

Show the human this sample (title, year, citation count, whether it has an
abstract). This is free — no LLM calls yet.

### 4. Classify the sample, then check in

```bash
wake --json classify "<seed>" --limit 10 --sort cited-by
```

Show the human the classification results and a couple of justifications.
**Ask if the relationship categories make sense** before scaling up — this
is the cheapest point to catch a systematically wrong assumption. (See
`references/reference.md` for the full relationship-class list and what
each one means.)

Roughly 20% of citing works typically lack an OpenAlex abstract. `classify`
transparently tries OSTI and Semantic Scholar to backfill these before
falling back to lower-confidence title/venue-only classification — no
action needed from you for this. See step 6 below for what to do about the
high-value works that backfill *can't* resolve.

### 5. Check cost before scaling up

```bash
wake --json status "<seed>"
```

This reports `pending_classify` and `estimated_remaining_classify_cost`
(estimate-only — token counts are heuristic, not metered). **Present this
estimate to the human and ask how to proceed**:
- Classify everything (`wake classify "<seed>"`, no `--limit`)
- Cap at the top-N most-cited (`wake classify "<seed>" --limit N --sort cited-by`)
- Stop here and render a partial brief

You can always dry-run first to preview without spending:
```bash
wake --json classify "<seed>" --dry-run [--limit N]
```

### 6. Classify the agreed scope

```bash
wake --json classify "<seed>" [--limit N] [--sort cited-by]
```

This is resumable — safe to Ctrl-C and re-run; already-classified works are
skipped (matched by prompt version + model, so changing either invalidates
the cache for those works only).

### 7. (Optional) Resolve high-value abstract gaps

After classifying, some influential citing works may still lack an
abstract (automatic OSTI/Semantic Scholar backfill couldn't recover one).
Check whether any are worth the extra effort:

```bash
wake --json gaps "<seed>" --min-cited-by 50
```

Try to get a PDF automatically before asking the human for one:

```bash
wake --json fetch-pdf "<seed>" <citing-id>
```

This tries OSTI, Semantic Scholar, Unpaywall, arXiv, and (if configured)
CORE.ac.uk in order, and caches the result. If it succeeds, feed the local
path straight into `fill-abstract`:

```bash
wake --json fill-abstract "<seed>" <citing-id> --from-pdf wake-out/<seed>/pdfs/<citing-id>.pdf
```

If `fetch-pdf` fails, it returns a set of human-actionable links (Unpaywall
lookup page, Google Scholar search, publisher DOI, CORE search) — present
these to the human rather than giving up, or fall back to asking them to
paste the abstract directly:

```bash
wake --json fill-abstract "<seed>" <citing-id> --text "..."

wake --json classify "<seed>" --ids <citing-id> --force   # re-classify with the recovered abstract
```

`--from-pdf` only reads the first few pages (the abstract is always in the
front matter, never further in) and makes one small, targeted LLM call —
not a full-document summarization. This step is optional and should only
be offered for works that are clearly consequential (high citation count);
don't suggest it for background-mention-tier works.

### 8. Render and present the brief

```bash
wake --json render "<seed>"
```

Works on partial data — if not everything is classified, the brief notes
coverage (e.g. "based on 50 of 408 citing works"). Read `impact.md` and
summarize it for the human; don't just dump the raw file unless asked.

### 9. Refine

If the human disagrees with a specific classification:
```bash
wake --json override "<seed>" <citing-openalex-id> --relationship extends --justification "..."
```
Then re-render (`wake --json render "<seed>"`) — overrides always win over
the LLM classification and are marked "(human-reviewed)" in the brief.

## Principles for Agents

1. **Never jump straight to full classification.** Sample first, check with
   the human, then scale.
2. **Report cost estimates before spending** at scale (`wake status`).
   Estimates are heuristic (char-count based), not metered — say so.
3. **Trust the cache.** Re-running `citing`/`classify`/`render` is cheap and
   safe; it skips completed work. Only use `--force` when the human asks for
   a fresh pull or the prompt/model changed.
4. **Partial briefs are valid.** `render` works on however much is
   classified and says so — you don't need 100% coverage to show something
   useful.
5. **Overrides are how the human corrects you.** If they push back on a
   classification, use `override`, don't just apologize and move on.
6. **Don't chase every missing abstract.** `gaps` + `fill-abstract` is for
   the small number of high-value, highly-cited works where a better
   abstract meaningfully changes the evidence — not a general cleanup pass
   over all no-abstract works.
