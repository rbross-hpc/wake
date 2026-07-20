# Agent Skill: wake — Impact Analysis

## Purpose

`wake` is an analysis instrument you (the agent) wield on the human's behalf.
It is **not** an autopilot — there is no single "do everything" command. You
compose thin primitives (`resolve`, `citing`, `sample`, `classify`, `gaps`,
`fetch-pdf`, `fill-abstract`, `evidence`, `bake`, `status`, `cost`,
`override`) into an **explore-first workflow**, pausing at natural decision
points so the human can confirm the seed paper, review a sample of
classifications, and approve spend before you scale up.

**Every classification starts out unverified.** `classify` only ever reads
a citing work's title/abstract/venue — never the paper itself — so its
output is always labeled `"verification_status": "provisional"`: a
placeholder guess, not a finding. `wake evidence` reads a citing work's
*actual full text* and proposes a real, quote-backed relationship
(`"proposed"`). Only after a human reviews that proposal does it become
`"verified"` — and **you** (the agent) are the one who runs `wake override`
to record that, never the human. See step 10 below; this lifecycle
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
  - Only mention `CORE_API_KEY` right before `fetch-pdf`/`gaps` (step 8),
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
`references/classify.md` for the full relationship-class list and what
each one means.)

Roughly 20% of citing works typically lack an OpenAlex abstract. `classify`
transparently tries OSTI and Semantic Scholar to backfill these before
falling back to lower-confidence title/venue-only classification — no
action needed from you for this. See step 8 below for what to do about the
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

### 8. (Optional) Resolve high-value abstract gaps

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

### 9. Bake and present the brief

```bash
wake --json bake "<seed>"
```

Works on partial data — if not everything is classified, the brief notes
coverage (e.g. "based on 50 of 408 citing works"). Read `impact.md` and
summarize it for the human; don't just dump the raw file unless asked.

### 10. (Optional) Deep-dive verification of a specific finding

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
it writes a dossier (`wake-out/<seed>/evidence/<citing-id>.md`) and returns
a structured `proposed` finding + `quotes` for you to act on.

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
automatically updates the dossier itself (`pending-human-review` →
`verified`) and the evidence wiki's `index.md`/`log.md` — no separate
step needed. `evidence/index.md` is a standing catalog of every
investigated citing work, grouped **Verified** / **Pending Review**; skim
it if you want a sense of what's already been checked before spending
another `wake evidence` call on a work you may have already covered.
`evidence/log.md` is the full chronological record (built, rebuilt,
failed, verified) if you need to reconstruct what happened and when.

If `wake evidence` can't get a PDF, it returns the same human-actionable
fallback links as `fetch-pdf` (Unpaywall, Google Scholar, publisher DOI,
CORE) — offer those rather than giving up on verifying that work.

**If a `proposed` finding looks wrong or implausible, check the extraction
before doubting the reasoning.** The `extracted_text_path` field in the
response (also linked from the dossier's "Source" section) points at the
raw page-tagged text the model was actually given, cached at
`wake-out/<seed>/pdfs/<citing-id>.json`. Read it yourself before telling
the human "the model got this wrong" — multi-column academic PDF layouts
are a known source of garbled extraction, and a bad extraction produces a
very different-looking problem than a bad inference once you've seen the
raw text. `wake --json evidence "<seed>" <citing-id> --force` re-runs
extraction too (not just the LLM verification call), so a garbled
extraction can be retried without needing a fresh PDF. If the dossier had
already been verified, `--force` resets it back to pending — the fresh
read is a new finding, not a continuation of the old sign-off, so it
needs a fresh look before you re-run `override`.

This step is optional and selective — don't try to verify every citing
work full-text; that defeats the purpose of the provisional/abstract-only
tier existing at all. Reserve it for works where the narrative genuinely
hinges on getting the relationship right.

### 11. (Optional) Synthesize a theme from related evidence

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

### 12. (Optional) Draft a narrative from confirmed themes

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

### 13. Refine

If the human disagrees with a specific classification (with or without a
`wake evidence` dossier backing it up):
```bash
wake --json override "<seed>" <citing-openalex-id> --relationship extends --justification "..."
```
`--verification-source` defaults to `human-judgment`; pass
`--verification-source evidence-dossier` when the override follows a
`wake evidence` finding the human accepted (step 10). Then re-bake
(`wake --json bake "<seed>"`) — overrides always win over the LLM
classification and are marked `[VERIFIED via ...]` in the brief.

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
