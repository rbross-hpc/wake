# wake — Command & Output Reference

Detailed reference material for the `wake` CLI, split out from `SKILL.md`
(which stays focused on the explore-first workflow). See `SKILL.md` first
for how and when to use these. This file is an index; the detailed
material for each workflow phase lives in its own file alongside this
one, listed below.

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
wake --json missing-pdfs "<seed>" [--min-cited-by N] [--limit N]
wake --json dedup candidates "<seed>" [--min-title-similarity F]
wake --json dedup confirm "<seed>" <duplicate-id> <canonical-id> [--reason "..."]
wake --json dedup reject "<seed>" <id-a> <id-b> [--reason "..."]
wake --json posters candidates "<seed>"
wake --json posters keep "<seed>" <citing-id> --reason "..."
wake --json fetch-pdf "<seed>" <citing-id> [--force]
wake --json fill-abstract "<seed>" <citing-id> --from-pdf PATH | --text TEXT
wake --json evidence "<seed>" <citing-id> [--force]
wake --json evidence "<seed>" <citing-id> --from-pdf PATH [--force]
wake --json theme create "<seed>" <slug> --title "..." --summary "..." --citing-ids ID,ID,...
wake --json theme confirm "<seed>" <slug>
wake --json theme queue "<seed>"
wake --json theme show "<seed>" <slug>
wake --json narrative outline create "<seed>" --components '[{"slug":"...","title":"...","kind":"theme|free","theme_slugs":[...]}]'
wake --json narrative outline show "<seed>"
wake --json narrative section create "<seed>" <slug> --title "..." --prose "..." [--theme-slugs SLUG,SLUG,...]
wake --json narrative section confirm "<seed>" <slug>
wake --json narrative section show "<seed>" <slug>
wake --json narrative stitch "<seed>"
wake --json narrative show "<seed>"
wake --json narrative refs-check export "<seed>"
wake --json narrative refs-check summarize "<seed>" <results.json>
wake --json bake "<seed>"
wake --json override "<seed>" <citing-id> --relationship <class> --justification "..." [--verification-source human-judgment|evidence-dossier]
wake --json exclude "<seed>" <citing-id> --reason "..." [--category not-about-seed|poster-or-abstract|irrelevant|other]
wake --json unexclude "<seed>" <citing-id> --reason "..."
wake --json unverify "<seed>" <citing-id> [--reason "..."]
wake --json unverify "<seed>" --since <timestamp> [--reason "..."]   # batch recovery
wake --json unverify "<seed>" --last N [--reason "..."]              # batch recovery

# Standalone
wake --json describe "<seed>"      # LLM contribution paragraph (independent of classify)
wake --json cost "<seed>"          # cumulative estimated token/cost usage
wake --json show brief "<seed>"    # re-print cached impact.md
wake --json show metrics "<seed>"  # re-print cached impact.json
wake --json show top "<seed>" -n N # top-evidence table only
wake --json show dossier "<seed>" <citing-id> # re-print an already-built evidence dossier
wake config show / validate / init
wake skill show / export PATH
```

Note: `--json` must appear before the subcommand (global flag), e.g.
`wake --json classify "<seed>"`, not `wake classify "<seed>" --json`.

Global flags: `--json`, `--work-dir DIR` (or `WAKE_WORK_DIR` env var, falls
back to cwd), `--verbose` (keep progress banners on stderr even under `--json`).

## Reference files by workflow phase

| File | Covers |
|---|---|
| [`classify.md`](classify.md) | Relationship classes, author-overlap tag |
| [`dedup.md`](dedup.md) | `wake dedup candidates`/`confirm`/`reject`, downstream exclusion from bake/theme/narrative |
| [`posters.md`](posters.md) | `wake posters candidates`/`keep`, surfacing poster/conference-abstract stubs for `wake exclude` |
| [`exclude.md`](exclude.md) | `wake exclude`/`unexclude`, downstream exclusion from bake/theme/narrative/gaps/theme-queue |
| [`pdf-acquisition.md`](pdf-acquisition.md) | The `wake fetch-pdf` source chain and `wake missing-pdfs` and fallback behavior |
| [`evidence.md`](evidence.md) | `wake evidence`/`wake override`/`wake unverify`, the provisional → proposed → verified lifecycle, diagnosing a surprising finding |
| [`themes.md`](themes.md) | `wake theme create`/`confirm`/`queue`, draft → confirmed lifecycle |
| [`narrative.md`](narrative.md) | `wake narrative outline`/`section`/`stitch`, inline `[ref:...]` source references, stitch-time renumbering |
| [`output-layout.md`](output-layout.md) | Full `wake-out/<seed>/` directory tree |
| [`environment.md`](environment.md) | Environment variable tiers, `wake config validate` |
