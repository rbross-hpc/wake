# Agent Skill: wake — Impact Analysis

## Purpose

`wake` is an analysis instrument you (the agent) wield on the human's behalf.
It is **not** an autopilot — there is no single "do everything" command. You
compose thin primitives (`resolve`, `citing`, `sample`, `classify`, `render`,
`status`, `cost`, `override`) into an **explore-first workflow**, pausing at
natural decision points so the human can confirm the seed paper, review a
sample of classifications, and approve spend before you scale up.

Every command supports `--json` and returns a stable envelope:
```json
{ "wake_version": "...", "command": "...", "ok": true, "data": { ... } }
```
Use `--json` for everything you parse programmatically. Errors use
`"ok": false` with `{"error": {"type": ..., "message": ...}}` plus a non-zero
exit code.

## The Workflow

Follow this sequence. **Do not skip straight to classifying everything** —
the whole point of this tool is that you explore before you spend.

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
is the cheapest point to catch a systematically wrong assumption.

Relationship classes (strongest signal of impact first):
- `extends` — directly extends the method/framework/theory of the seed
- `builds-on` — builds a new system/tool that depends on the seed
- `uses-as-tool` — uses the seed's software/tool/dataset as-is
- `benchmarks` — benchmarks against the seed as a baseline
- `applies-to-domain` — applies the seed's approach to a new domain
- `background-mention` — cites only as background/related work

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

### 7. Render and present the brief

```bash
wake --json render "<seed>"
```

Works on partial data — if not everything is classified, the brief notes
coverage (e.g. "based on 50 of 408 citing works"). Read `impact.md` and
summarize it for the human; don't just dump the raw file unless asked.

### 8. Refine

If the human disagrees with a specific classification:
```bash
wake --json override "<seed>" <citing-openalex-id> --relationship extends --justification "..."
```
Then re-render (`wake --json render "<seed>"`) — overrides always win over
the LLM classification and are marked "(human-reviewed)" in the brief.

## Seed ID Formats

| Format | Example |
|--------|---------|
| DOI | `10.1145/1048935.1050189` |
| arXiv ID | `2301.04567` |
| OpenAlex ID | `W2156077349` |
| Paper title | `"Parallel netCDF: A High-Performance Scientific I/O Interface"` |

## Other Commands

```bash
wake --json describe "<seed>"      # LLM contribution paragraph (independent of classify)
wake --json cost "<seed>"          # cumulative estimated token/cost usage
wake --json show brief "<seed>"    # re-print cached impact.md
wake --json show metrics "<seed>"  # re-print cached impact.json
wake --json show top "<seed>" -n N # top-evidence table only
wake config show / validate / init
```

## Output Layout

```
wake-out/<OpenAlex-ID>/
  seed.json          — resolved seed + LLM description
  citing.json        — all citing works (paginated, cached)
  classified.json    — per-citing-work relationship + evidence
  impact.json        — aggregated metrics
  impact.md          — the impact brief
  .state.json        — stage cache keys
  .classify/         — per-work classification sidecars (resumable)
  .cost.jsonl        — per-LLM-call estimated token/cost log
  .overrides.jsonl   — human-reviewed relationship overrides
```

Use `--work-dir DIR` (or `WAKE_WORK_DIR` env var) to control where
`wake-out/` is created — useful when running from a scratch directory.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM API key (required for describe/classify) |
| `OPENAI_BASE_URL` | API endpoint (e.g. Argo) |
| `OPENALEX_MAILTO` | Your email for OpenAlex polite pool (recommended) |
| `WAKE_WORK_DIR` | Default root for `wake-out/` cache |

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
