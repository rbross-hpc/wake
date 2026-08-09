---
name: wake
description: Use when analyzing the citation impact of a research paper with the wake CLI. Covers the full explore-first workflow — resolve, citing, sample, classify, gaps, fetch-pdf, evidence, themes, narrative, timeline, bake — and the provisional → proposed → verified evidence lifecycle. Do not use for general literature search or unrelated citation queries.
---

# Agent Skill: wake — Impact Analysis

## Purpose

`wake` is an analysis instrument you (the agent) wield on the human's behalf.
It is **not** an autopilot — there is no single "do everything" command. You
compose thin primitives (`resolve`, `citing`, `sample`, `classify`, `gaps`,
`fetch-pdf`, `fill-abstract`, `evidence`, `bake`, `rebuild`, `status`,
`cost`, `override`) into an **explore-first workflow**, pausing at natural decision
points so the human can confirm the seed paper, review a sample of
classifications, and approve spend before you scale up.

**Every classification starts out unverified.** `classify` only ever reads
a citing work's title/abstract/venue — never the paper itself — so its
output is always labeled `"verification_status": "provisional"`: a
placeholder guess, not a finding. `wake evidence` reads a citing work's
*actual full text* and proposes a real, quote-backed relationship
(`"proposed"`). Only after a human reviews that proposal does it become
`"verified"` — and **you** (the agent) are the one who runs `wake override`
to record that, never the human. See step 13 below; this lifecycle
(provisional → proposed → verified) is the core epistemic model of the
whole brief, so keep it in mind throughout — a `[PROVISIONAL]`-tagged
relationship in the brief is not settled, no matter how high its
confidence score looks.

Every command supports `--json` and returns a stable envelope:
```json
{ "wake_version": "...", "command": "...", "ok": true, "data": { ... } }
```
Use `--json` for everything you parse programmatically. Errors use
`"ok": false` with `{"error": {"type": ..., "message": ...}}` plus a non-zero
exit code.

For the full command list, output-file layout, environment variables, and
the PDF-acquisition source chain, see `references/reference.md` — an
index into `references/*.md`, one file per workflow phase. This file
(SKILL.md) covers only the workflow — when to run what, and where to
check in with the human.

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
  - Only mention `CORE_API_KEY` right before `fetch-pdf`/`gaps` (step 10),
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

`wake resolve` also automatically tries to acquire the seed paper's own PDF
(same source chain as `wake fetch-pdf`, stored at `wake-out/<seed>/seed.pdf`) —
a silent side effect, resolve never blocks on it. Check the result in the same
breath as everything else you're confirming with the human:

```bash
wake --json status "<seed>"   # shows "Seed PDF: cached at ..." or "not available"
```

**Present both to the human together, as one confirmation step**: the
resolved title/year/venue/OpenAlex ID (title search can mismatch — this is
the cheapest point to catch it), *and* the seed-PDF status. Don't treat the
PDF check as a separate, skippable aside — if the automatic fetch failed
(the paper is behind a paywall not covered by any configured source), ask
the human for a copy right here, before moving to step 2. They should have
one, or can get one from the publisher; `wake status` also surfaces
fallback links (Unpaywall, publisher DOI, Google Scholar) recorded in
`seed.json` from the failed attempt. Once they have a copy:

```bash
wake --json seed fetch-pdf "<seed>" --from-pdf /path/to/paper.pdf
```

wake validates that the supplied PDF matches the seed's metadata before
accepting it. The seed PDF is not yet used in any LLM prompts (it's acquired
now so it's on hand when future commands need it) — but its acquisition
status is surfaced everywhere the packet is: `wake-out/<seed>/README.md`,
`AGENTS.md`, and `impact.md`'s frontmatter (`seed_pdf_status`) all show
whether it's `cached`, `attempted-failed`, or `not-attempted`, so a
still-missing seed PDF stays visible for the life of the packet, not just
at this one step. If the human genuinely doesn't have a copy and can't get
one, that's fine — proceed anyway; nothing downstream requires it yet.

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
`references/classify.md` for the full relationship-class list and what
each one means.)

Roughly 20% of citing works typically lack an OpenAlex abstract. `classify`
transparently tries OSTI and Semantic Scholar to backfill these before
falling back to lower-confidence title/venue-only classification — no
action needed from you for this. See step 10 below for what to do about the
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
- Stop here and bake a partial brief

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

### 7. (Optional) Check for duplicate citing works

A citing set can contain a preprint alongside its later-published
version, a workshop paper alongside its expanded journal version, or the
same paper independently double-published under two OpenAlex IDs. Left
unmerged, each inflates reach metrics, can end up in two different
themes as if independent evidence, or get cited twice from a narrative
as if two sources agreed rather than one.

```bash
wake --json dedup candidates "<seed>"
```

Pure heuristic scan (title similarity + shared author IDs), no LLM call,
deterministic. **Never auto-merges** — present each candidate pair to the
human one at a time (same rule as everywhere else), then run the
decision on their behalf:

```bash
wake --json dedup confirm "<seed>" <duplicate-id> <canonical-id> --reason "..."
wake --json dedup reject "<seed>" <id-a> <id-b> --reason "..."   # human judged them genuinely distinct
```

A confirmed duplicate is excluded everywhere downstream — dropped from
`wake bake`'s reach metrics, refused by `wake theme create`, refused by
`wake narrative` reference validation — always pointing back at the
canonical work instead. This step is optional and worth a quick pass
once classification is broad enough to surface real candidates; don't
force a decision on a borderline pair the human isn't confident about —
`reject` is always available and just means the same pair won't be
re-surfaced.

### 8. (Optional) Surface posters and conference-abstracts

A classified citing set often includes a few poster-reception blurbs or
short conference abstracts that duplicate a full paper's content
elsewhere in the set — noise the human usually wants dropped, but which
otherwise has to be caught by hand while skimming.

```bash
wake --json posters candidates "<seed>"
```

Pure heuristic scan (OpenAlex `type: conference-abstract`, or a
`Poster:`/`Abstract:` title prefix), no LLM call, deterministic.
**Never auto-excludes** — present each candidate to the human one at a
time, then act on their decision: exclude it (step 9 below, with
`--category poster-or-abstract`) or, if it turns out to be a false
positive (a real paper that happens to be titled "Abstract: ..."), keep
it so it isn't resurfaced by a later scan:

```bash
wake --json posters keep "<seed>" <citing-id> --reason "..."
```

This step is optional — a small citing set may have none, and it's
fine to skip entirely if the human isn't interested in this kind of
cleanup.

### 9. (Optional) Exclude works judged not actually about the seed

A `background-mention` classification means the seed was cited, but not
necessarily meaningfully — some of those are just noise: the seed
appears only in a bibliography, or the citing work is a poster/
conference-abstract that duplicates a full paper's content, or the human
simply doesn't want a work counted for some other reason. `override`ing
these to `background-mention` still leaves them fully usable — nothing
stops a later theme or narrative section from citing one by accident.
For a work that's genuinely out of scope, make that explicit:

```bash
wake --json exclude "<seed>" <citing-id> --reason "..." --category not-about-seed
```

`--reason` is required — never exclude without a stated justification,
and always get explicit human sign-off first, one work at a time (same
rule as everywhere else). Once excluded, the work is refused by `wake
theme create` and `wake narrative` reference validation, dropped from
`wake bake`'s reach metrics, and no longer surfaced by `wake gaps`/`wake
theme queue` — even if the work was already independently human-
verified (the realistic sequence: verify first, then notice on
reflection it shouldn't count). If a human later decides an exclusion
was a mistake, reverse it with its own justification:

```bash
wake --json unexclude "<seed>" <citing-id> --reason "..."
```

This step is optional and should be reserved for works genuinely out of
scope, not a general cleanup pass — most `background-mention` works are
fine left as-is, just correctly classified as weak evidence.

### 10. (Optional) Resolve high-value abstract gaps

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

This tries OSTI, Semantic Scholar, Unpaywall, Springer (direct URL, no
API key), arXiv, and (if configured) CORE.ac.uk in order, and caches the
result. If it succeeds, feed the local path straight into `fill-abstract`:

```bash
wake --json fill-abstract "<seed>" <citing-id> --from-pdf wake-out/<seed>/pdfs/<citing-id>.pdf
```

Every fetch attempt (success or failure) is logged to `evidence/log.md`, so
you can always check where things stand without re-running fetches:

```bash
wake --json missing-pdfs "<seed>" [--min-cited-by N]
```

Reports every classified work with no cached PDF, its fetch state
(`never-attempted`, `exhausted`, or `fetched-but-gone`), and which sources
were tried. Useful before a deep-dive session to know exactly what's left to
hunt down.

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

### 11. Bake and present the brief

```bash
wake --json bake "<seed>"
```

Works on partial data — if not everything is classified, the brief notes
coverage (e.g. "based on 50 of 408 citing works"). Read `impact.md` and
summarize it for the human; don't just dump the raw file unless asked.
`wake bake`/`wake rebuild` (see "Rendering the Wiki" below) are the only
two commands that render `impact.md`; everything else in this workflow
writes JSON only.

## Rendering the Wiki

Every command in this workflow beyond `wake bake`, `wake narrative
stitch`, and `wake timeline stitch` — `wake evidence`, `wake override`,
`wake unverify`, `wake theme create`/`confirm`, `wake narrative outline
create`, `wake narrative section create`/`confirm`, `wake timeline
period create`/`confirm` — writes only the artifact's JSON sidecar. It
never touches that artifact's rendered `.md`, `evidence/index.md`,
`evidence/themes/index.md`, or `README.md`/`AGENTS.md`. You don't need
the rendered `.md` to keep working — every one of those commands already
returns the structured data you need (a `proposed` finding, a theme's
`citing_works`, etc.) directly in its response, and the next command in
the chain reads the same JSON, not the `.md`.

Rendering is one single, separate, explicit step:
```bash
wake --json rebuild "<seed>"
```
This re-derives every dossier/theme/section/period `.md`, both indexes,
`narrative.md`, `timeline.md`/`timeline.json`, `impact.md`, and
`README.md`/`AGENTS.md` from whatever JSON is currently on disk, in the
right dependency order. No LLM or network call — pure re-render, safe to
run any time. Run it:
- Whenever you're about to hand the human a link into the wiki (a
  dossier, a theme, `README.md`) and want it to reflect what you've
  built up so far.
- After a batch of JSON-only writes (e.g. several `wake evidence` calls
  in a row), rather than after each one individually.
- At the natural end of a session, so the packet you leave behind is
  fully rendered, not just fully recorded.

Every `wake rebuild` call also reports a `changes` block: which JSON
sources (dossiers, themes, sections, outline, timeline periods, overrides,
seed/citing/classified) were added, changed, or removed since the *previous*
`wake rebuild` call for this seed (persisted in
`rebuild-manifest.json`). This is purely informational — it never skips
a render step, every artifact type is always re-rendered — but it's a
quick way to tell the human (or yourself, resuming a session) what's
new since the wiki was last brought up to date.

### 12. Triage what's worth verifying next

Every classification in the brief is `[PROVISIONAL]` by default, but not
every provisional work is worth the cost of a full-text `wake evidence`
call. Before picking which ones to deep-dive, get a complete, ranked
picture of the gap between classify and verification:

```bash
wake --json assess "<seed>"
```

This joins everything a full triage decision needs — relationship,
confidence, citation count, dossier existence, theme membership, and PDF
fetch state — into one document, per classified work, rather than
requiring you to cross-reference `classified.json`, `evidence/`, theme
sidecars, and `impact.json`'s (truncated) `top_evidence` yourself. Two
fields matter most:

- `data.themes` — per-theme evidence coverage; a theme with zero
  `verified` works is not yet backed by anything a human has actually
  signed off on, however many provisional works are cited in it.
- `data.triage` — every provisional (not excluded, not a duplicate) work's
  OpenAlex ID, ranked by the same relationship-strength × log(citations)
  score `impact.md`'s "Strongest Evidence" table uses, highest first.
  `data.works` has the full per-work detail (including `pdf.fetch_state`
  and `score_inputs`) for each ID in `data.triage`, keyed by
  `openalex_id`, if you want to re-rank by different criteria than the
  default score.

Work down `data.triage` with step 10 (abstract gaps) and step 13 (deep-dive
verification) rather than picking works ad hoc or working strictly by
citation count alone — a lower-cited work that's the sole support for an
otherwise-thin theme can matter more than a highly-cited one already
backed by two verified works. `wake assess` never mutates anything; re-run
it any time to see how the picture has changed after a batch of
`wake evidence`/`wake theme create` calls.

### 13. (Optional) Deep-dive verification of a specific finding

Every classification in the brief is `[PROVISIONAL]` by default — an
abstract-only guess, not a checked fact. For works that matter to the
narrative (usually the top few in "Strongest Evidence," or ones the human
specifically asks about), you can verify the actual relationship by
reading the full paper:

```bash
wake --json evidence "<seed>" <citing-id>
```

This automatically fetches a PDF (same chain as `fetch-pdf`), reads the
*entire* document (not just the abstract), and proposes a relationship
backed by quoted, page-cited passages — an independent judgment, not a
rubber-stamp of the provisional guess. It never modifies the brief itself;
it writes the dossier's JSON sidecar (`wake-out/<seed>/evidence/<citing-id>.json`)
and returns a structured `proposed` finding + `quotes` for you to act on
directly from that response — you don't need to read the rendered `.md`
to act on a finding. The dossier's `.md` itself is not rendered by this
call; run `wake rebuild "<seed>"` (see "Rendering the Wiki" below) whenever you want the
human-readable wiki to reflect what you've built up so far.

**You always run the promotion step yourself — never ask the human to run
a command.** Two ways to close the loop, both ending the same way (you
call `wake override`):

- **Human reviews independently**: point them at the dossier file or the
  local PDF; they tell you what they accept; you translate that into an
  `override` call.
- **You walk them through it**: present the finding conversationally, but
  **paste the actual quoted passage(s) from the `quotes` field verbatim,
  in a blockquote, with the page number** — not a paraphrase or a summary
  of what the quote says. The human needs to read the real sentences in
  context to judge the claim themselves, exactly as they would if they'd
  found the passage on their own. Then ask a plain yes/adjust/no, and act
  on the answer yourself:
  ```bash
  wake --json override "<seed>" <citing-id> \
    --relationship <the-agreed-relationship> \
    --justification "<the quoted evidence, or the human's own reasoning>" \
    --verification-source evidence-dossier
  ```

When `--verification-source evidence-dossier` is used, `wake override`
automatically updates the dossier's JSON sidecar (`pending-human-review`
→ `verified`) and appends to the evidence wiki's `log.md` — but does
**not** re-render the dossier's `.md` or `evidence/index.md`; run `wake
rebuild "<seed>"` (see "Rendering the Wiki" below) to bring the rendered wiki up to date with
whatever JSON you've accumulated. `evidence/index.md`, once rebuilt, is
a standing catalog of every investigated citing work, grouped
**Verified** / **Pending Review**; skim it if you want a sense of what's
already been checked before spending another `wake evidence` call on a
work you may have already covered.

(A dossier may propose more than one facet — e.g. a paper that's both
`uses-as-tool` and `applies-to-domain`, see `references/classify.md`'s
"Multi-Facet Relationships" — in which case `--relationship` affirms
just one of them; the model's other facet stays in the dossier as an
unaffirmed reading, not deleted. Run `override` again with a different
`--relationship` if the human wants to affirm more than one.)
`evidence/log.md` is the full chronological record (built, rebuilt,
failed, verified) if you need to reconstruct what happened and when.
`wake-out/<seed>/README.md` is the wiki's human entry point — what the
folder is, what's been done so far, and where to start reading, ending
in links to `impact.md`, `narrative.md`, and both indexes with counts.
`wake-out/<seed>/AGENTS.md` is the equivalent entry point for an agent
handed just the folder, with no other context: a terse schema
reference (every artifact type, the `.md`=human/`.json`=agent surface
convention, and query recipes) rather than README.md's explanatory
prose — see `references/output-layout.md`. Neither is regenerated as a
side effect of any of the commands above — `wake rebuild "<seed>"`
(see "Rendering the Wiki" below) is what refreshes both, together, from whatever JSON is
currently on disk; run it before pointing a human at README.md, or
before an agent session that expects AGENTS.md to be current. The same
is true of a dossier's "Referenced by:" line (naming every theme/
section that currently cites it) and a theme's "## Referenced By"
section (naming every narrative section grounded in it) — both are
recomputed only when that document is next rendered, so run `wake
rebuild` first if you're relying on either to be current.

If `wake evidence` can't get a PDF, it returns the same human-actionable
fallback links as `fetch-pdf` (Unpaywall, Google Scholar, publisher DOI,
CORE) — offer those rather than giving up on verifying that work. If a
human finds a PDF manually (e.g. via the publisher or a preprint server),
pass it directly instead of copying it yourself:

```bash
wake --json evidence "<seed>" <citing-id> --from-pdf /path/to/paper.pdf
```

wake validates that the PDF matches the citing work's metadata (title
similarity, author surname, DOI in text) before copying it into the packet
and running verification. On mismatch, it refuses and explains what failed.
If you're confident it's the right paper despite the check failing, use
`--force` — the check still runs and the mismatch is logged.

**If a `proposed` finding looks wrong or implausible, check the extraction
before doubting the reasoning.** The `extracted_text_path` field in the
response (an absolute path; the dossier's `.json` sidecar stores the same
file relative to its own directory) points at the raw page-tagged text
the model was actually given, cached at `wake-out/<seed>/pdfs/<citing-id>.pdf.json`.
Read it yourself before telling the human "the model got this wrong" —
multi-column academic PDF layouts are a known source of garbled
extraction, and a bad extraction produces a very different-looking
problem than a bad inference once you've seen the raw text. A human
reviewing the dossier directly can instead click the "Raw extracted
text" link under its "## Source" heading. `wake --json evidence "<seed>"
<citing-id> --force` re-runs extraction too (not just the LLM
verification call), so a garbled extraction can be retried without
needing a fresh PDF. If the dossier had already been verified, `--force`
resets it back to pending — the fresh
read is a new finding, not a continuation of the old sign-off, so it
needs a fresh look before you re-run `override`.

This step is optional and selective — don't try to verify every citing
work full-text; that defeats the purpose of the provisional/abstract-only
tier existing at all. Use `wake assess`'s `data.triage` (step 12) rather
than eyeballing citation counts to decide which works are worth it.

### 14. (Optional) Synthesize a theme from related evidence

When several citing works together support a broader claim (e.g.
"extensive use in Earth system modeling"), write a combined-evidence
theme instead of listing them separately in your summary to the human:

```bash
wake --json theme create "<seed>" earth-system-modeling \
  --title "Extensive use in Earth system modeling" \
  --summary "<your synthesis paragraph, written after reading the underlying dossiers/classifications>" \
  --citing-ids W111,W222,W333
```

This makes no LLM call — **you** decide which works belong together and
write the synthesis yourself, the same way you decide a relationship
before recording it with `override`. `wake` validates the citing IDs and
persists your judgment; it never does the clustering or writing for you.
Always overwrites the same slug (no `--force` needed — nothing expensive
to protect against re-doing), so feel free to iterate the summary/
citing-ids with the human and re-run.

**A theme is always written as a draft** — creating or re-asserting it is
your judgment, not the human's, so it can never itself count as settled.
Works with no evidence dossier yet can still be included (mixed
sourcing); each is shown in the doc with its own honest status
(`[PROVISIONAL]`/`[PROPOSED]`/`[VERIFIED]`) — theme creation never
upgrades a work's own relationship status.

To promote a theme to `confirmed`, get the human's explicit approval of
the synthesis, then run the confirmation yourself — never ask the human
to run the command:

```bash
wake --json theme confirm "<seed>" earth-system-modeling
```

This **refuses unless every cited work is already human-verified** (via
`override`) — if some aren't, it tells you exactly which ones, and you'll
need `wake evidence` + `override` on each before confirmation can
succeed. A theme should never appear settled while resting on unverified
findings.

Check `wake --json theme queue "<seed>"` periodically for outstanding
work across all themes: citing works still needing a `wake evidence`
dossier, and — importantly — works whose dossier has appeared *since* the
theme was last created (via an unrelated `wake evidence` call) but hasn't
been reviewed and re-asserted. **Read that new dossier before reflexively
re-running `wake theme create`** — the full-text finding may not actually
support the thematic claim the abstract-only guess suggested it did.

This step is optional — only synthesize themes that genuinely help tell
the impact story; don't force citing works into artificial groupings.

### 15. (Optional) Draft a narrative from confirmed themes

Once you have one or more confirmed themes, draft a fuller narrative
instead of relying on the brief's "Strongest Evidence" list alone. Plan
the structure first — an ordered list of components, each backed by one
or more themes (`kind: "theme"`) or free-form framing prose with no
evidence claim (`kind: "free"`, e.g. an intro/conclusion):

```bash
wake --json narrative outline create "<seed>" --components '[
  {"slug":"intro","title":"Introduction","kind":"free"},
  {"slug":"earth-adoption","title":"Adoption in Earth System Modeling","kind":"theme","theme_slugs":["earth-system-modeling"]},
  {"slug":"conclusion","title":"Conclusion","kind":"free"}
]'
```

The outline is a plan, not a claim — referenced themes don't need to be
confirmed yet (only at section-confirm time), and you can freely revise
it as drafting proceeds. Then draft one section at a time, having read
the underlying theme(s)/dossiers yourself:

```bash
wake --json narrative section create "<seed>" earth-adoption \
  --title "Adoption in Earth System Modeling" \
  --prose "<your prose, grounded in the theme's confirmed findings, each factual sentence ending with [ref:ID,ID,...]>" \
  --theme-slugs earth-system-modeling
```

Like `wake theme create`, this makes no LLM call — you write the prose
yourself; `wake` validates and persists it. Every section starts `draft`.

**End every factual sentence with a `[ref:ID,...]` marker** naming its
source(s) — `SEED` for the seed paper, or a citing work's OpenAlex ID for
anything else. `create_section` refuses the whole call if any marker
names an ID that isn't `SEED` or isn't currently human-verified for this
seed (same bar as `wake theme confirm`), and refuses outright if the
packet itself is inconsistent (a work `overrides.jsonl` calls verified
but has no dossier file on disk). This guarantees every citation in the
final narrative points at a real, checked source — it does not, by
itself, guarantee the source actually supports that sentence's claim;
that judgment is yours when drafting and the human's at confirm time.
Framing sentences with no factual content don't need a marker.

For sentences describing what the **seed paper itself** did (marked
`[ref:SEED]`), read `wake-out/<seed>/seed.pdf` directly if it's been
acquired (see `seed.json`'s `seed_pdf` sub-object, or `wake status`) —
don't rely on the abstract alone for claims about the seed's own method
or contribution. No `wake` command surfaces this for you; it's a plain
file to open like any other source PDF.

Present the drafted section to the human, then confirm it on their behalf:

```bash
wake --json narrative section confirm "<seed>" earth-adoption
```

For a theme-backed section, confirmation **refuses unless every
referenced theme is currently confirmed** — re-checked fresh each time,
so if a theme is later reopened to draft (e.g. someone adds a new
unverified work to it), a section built on it is caught rather than left
silently stale. A section can reference multiple themes if it synthesizes
across them. Free-form sections go through the same draft → confirmed
step (framing prose can still make claims worth a human's eye) but
confirm immediately since there's no theme to check.

Once satisfied with the sections drafted so far, assemble them:

```bash
wake --json narrative stitch "<seed>"
```

`narrative.md` works on partial data, like `bake` — not-yet-drafted
sections show a placeholder with the exact command to draft them,
drafted-but-unconfirmed sections carry a `⚠ DRAFT` banner, and the whole
document is flagged "Partial narrative" at the top whenever anything is
incomplete. Never present a partial stitch to the human as a finished
narrative.

Stitching is also when `[ref:ID,...]` markers get renumbered into
`[R1]`, `[R2]`, ... in reading order (stable across reuse — the same
source cited twice keeps one number), with a Chicago-style `##
References` list appended at the bottom. This only happens at stitch
time, once the whole document is available; every earlier per-section
preview keeps the raw `[ref:...]` form.

This step is optional — only draft a narrative once the underlying
themes are solid; a narrative built on shaky, unconfirmed themes will
just need to be redone.

**Optional follow-up: verify the References list against live scholarly
databases** using the external `ref-checker` tool
(https://github.com/rbross-hpc/ref-checker). This checks the
bibliographic details themselves (author spelling, year, DOI), which is
a different question from what `[ref:...]` validation already
guarantees (that the source is real and human-verified for this seed —
see `references/narrative.md`). wake never runs `ref-checker` itself:

```bash
wake --json narrative refs-check export "<seed>"
pipx install git+https://github.com/rbross-hpc/ref-checker.git   # once per environment
ref-checker check --refs-json wake-out/<seed>/narrative/refs.json \
  --results-json wake-out/<seed>/narrative/refs.results.json
wake --json narrative refs-check summarize "<seed>" wake-out/<seed>/narrative/refs.results.json
```

Report any flagged entries to the human — a `CLOSEST`/`NO MATCH` status,
or even an `OK` match carrying a year-mismatch or dead-URL note — and
let them decide whether to fix the citing work's metadata or accept it
as a known limitation.

### 16. (Optional) Curate a timeline of key developments

Once you have some verified works, you and the human may want a
timeline showing how the seed's story unfolded over time — for a "See
also" link in the wiki, or as structured input to a separate
Tufte-style graphic-rendering tool. This is a selection exercise, like
narrative sections, not something `wake` computes for you: `wake`
provides the scored, dated material; you and the human choose what
counts as a highlight and how to group it into periods.

Start by reading the candidate material — every dated, classified work,
scored the same way `impact.md`'s "Strongest Evidence" table is:

```bash
wake --json timeline candidates "<seed>" [--bucket-years N] [--min-strength S]
```

This never pre-selects "the milestones" — every classified work with a
year is included, weakest relationships too, so the threshold for
what's worth highlighting stays a conversation with the human, not a
config default. `--bucket-years` groups the view into coarser windows
(e.g. `--bucket-years 5`) if the year-by-year shape is too granular to
reason about; this is purely a way of looking at the data, not a
decision that affects anything you create afterward.

Then curate one period at a time — a bare year (an emergent
single-year period) or a named span you and the human define up front:

```bash
wake --json timeline period create "<seed>" early-adoption \
  --label "Early adoption in Earth system modeling" --from 2003 --to 2007 \
  --highlights W111,W222 \
  --note "<why this span matters to the story>" \
  --highlight-note W111='<why this specific work matters here>'
```

Present the period to the human, then confirm it on their behalf —
**confirmation refuses unless every highlighted work is currently
human-verified** (re-checked fresh, same bar `wake theme confirm`
enforces), since a confirmed period is an evidentiary claim about what
mattered at that point in the story, not just your classification guess:

```bash
wake --json timeline period confirm "<seed>" early-adoption
```

Once satisfied with the periods drafted so far, assemble them:

```bash
wake --json timeline stitch "<seed>"
```

This writes two files with different audiences: `timeline.md` is the
working artifact (every period, confirmed or draft, clearly labeled —
same "works on partial data" philosophy as `narrative.md`), and
`timeline.json` carries the **confirmed periods only** — the handoff to
a graphic-rendering tool, so nothing still-being-decided leaks into
what gets drawn. Periods with overlapping year ranges are reported (a
callout in `timeline.md`, `data.overlaps` in the JSON) but never
blocked — periodization is the team's editorial call.

This step is optional, and independent of narrative/themes — a timeline
can highlight works that aren't part of any confirmed theme, and vice
versa.

### 17. Refine

If the human disagrees with a specific classification (with or without a
`wake evidence` dossier backing it up):
```bash
wake --json override "<seed>" <citing-openalex-id> --relationship extends --justification "..."
```
`--verification-source` defaults to `human-judgment`; pass
`--verification-source evidence-dossier` when the override follows a
`wake evidence` finding the human accepted (step 13). Then re-bake
(`wake --json bake "<seed>"`) — overrides always win over the LLM
classification and are marked `[VERIFIED via ...]` in the brief.

**If you (the agent) ever verify a work by mistake** — e.g. misreading a
bulk go-ahead and running `override` on works the human never actually
reviewed — undo it explicitly rather than leaving a false verification
in place:
```bash
wake --json unverify "<seed>" <citing-id> --reason "..."
```
If the mistake affected a whole run of works at once, use the batch
form instead of calling this one at a time: `wake --json unverify
"<seed>" --since <timestamp> --reason "..."` or `--last N --reason
"..."`. This is a real recovery action, not a cleanup nicety — a work
left falsely `verified` can end up cited in a theme or narrative
section as if a human had actually signed off on it.

## Principles for Agents

1. **Never jump straight to full classification.** Sample first, check with
   the human, then scale.
2. **Report cost estimates before spending** at scale (`wake status`).
   Estimates are heuristic (char-count based), not metered — say so.
3. **Trust the cache.** Re-running `citing`/`classify`/`bake` is cheap and
   safe; it skips completed work. Only use `--force` when the human asks for
   a fresh pull or the prompt/model changed.
4. **Partial briefs are valid.** `bake` works on however much is
   classified and says so — you don't need 100% coverage to show something
   useful.
5. **Overrides are how the human corrects you.** If they push back on a
   classification, use `override`, don't just apologize and move on.
6. **Don't chase every missing abstract.** `gaps` + `fill-abstract` is for
   the small number of high-value, highly-cited works where a better
   abstract meaningfully changes the evidence — not a general cleanup pass
   over all no-abstract works.
7. **You run `wake override`, never the human.** Whether the human reviewed
   a `wake evidence` dossier on their own or you walked them through it,
   *you* translate their decision into the `override` call. Don't hand a
   human a CLI command to type themselves.
8. **When presenting evidence, quote it — don't paraphrase it.** `wake
   evidence`'s `quotes` field contains full-paragraph passages exactly as
   they appear in the source. Paste that text verbatim (as a blockquote,
   with the page number) so the human is judging the paper's actual words,
   not your summary of them.
9. **Provisional is not verified, no matter the confidence score.** A
   `classify`-only relationship with confidence 0.9 is still just an
   abstract-only guess. Don't describe provisional classifications to the
   human as settled findings — reserve that language for `verified` ones.
10. **Before blaming the model's reasoning, check the extraction.** A
    surprising `wake evidence` finding may just mean the PDF extracted
    badly (common with multi-column layouts). Read `extracted_text_path`
    yourself first — it's a plain cached JSON file, no re-run needed —
    before telling the human the model got something wrong.
11. **A theme is your judgment until a human confirms it — and confirming
    it requires every member work to already be verified.** Don't present
    a draft theme as settled, and don't try to talk a human into
    confirming one while some cited works are still only provisional or
    proposed — `wake theme confirm` will refuse anyway, so get those
    verified first.
12. **A narrative section is only as solid as its themes, re-checked at
    confirm time, not when it was drafted.** If a theme a section relies
    on gets reopened to draft after the section was written (e.g. a new
    unverified work was added to it), `wake narrative section confirm`
    will refuse — that's a real inconsistency to fix (re-confirm the
    theme first), not a bug to work around.
13. **Every `create`/`confirm`/`override` command validates and persists
    a judgment you already made — it never makes the judgment itself.**
    `theme create` doesn't decide which works belong together; `narrative
    section create` doesn't decide what the prose should say; `override`
    doesn't decide the relationship; `theme confirm`/`section confirm`
    don't decide whether the evidence is good enough. wake's job in all
    of these is to check the specific structural facts it can check (are
    the citing IDs real, is every cited work verified, is the JSON
    well-formed) and write the result down — the actual thinking already
    happened, either in your read of the evidence or in the human's
    sign-off. If you find yourself expecting one of these commands to
    tell you whether something is a good idea, that's a sign the command
    is being asked to do a job it doesn't do.
14. **JSON is written immediately; Markdown is rendered on demand.**
    `evidence`, `override`, `unverify`, `theme create`/`confirm`,
    `narrative outline create`, `narrative section create`/`confirm` all
    write their JSON sidecar right away and return the data you need in
    their response — you never have to wait for or read a `.md` file to
    keep working. Run `wake rebuild "<seed>"` (see "Rendering the Wiki")
    before pointing a human at any rendered file (a dossier, a theme,
    `README.md`) so what they see reflects what you've actually recorded.
