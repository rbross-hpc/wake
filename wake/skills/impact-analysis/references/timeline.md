# Timeline Curation (`wake timeline`) — candidates → periods → stitch

A timeline is a curated view of the seed's story over time: which citing
works mattered when, grouped into periods the agent and human define
together. Like `wake theme`, wake never decides what belongs — it
provides the scored, dated material and persists the team's selections.

| Period status | Set by | Meaning |
|---|---|---|
| `draft` | `wake timeline period create` (always, unconditionally) | Agent's/human's curation — not yet confirmed |
| `confirmed` | `wake timeline period confirm` (agent-run, after human sign-off) | Settled — refuses unless every highlighted work is already `verified` |

## 1. Candidates — the material to choose from

```bash
wake --json timeline candidates "<seed>" [--bucket-years N] [--min-strength S] [--since Y] [--until Y]
```

Returns every dated, classified citing work, bucketed by year (or an
N-year window with `--bucket-years`), each with its `score`
(relationship-strength × log(citations), same formula `impact.md`'s
"Strongest Evidence" table uses) and full verification/exclusion state:

```json
{
  "ok": true,
  "data": {
    "seed": {"openalex_id": "...", "title": "..."},
    "bucket_years": 1, "min_strength": null, "since": null, "until": null,
    "undated_count": 2, "excluded_count": 0, "duplicate_count": 0,
    "buckets": [
      {
        "bucket_start": 2005, "bucket_end": 2005,
        "count": 2, "weighted_intensity": 39.95,
        "works": [
          {"openalex_id": "W111", "title": "...", "year": 2005, "cited_by_count": 300,
           "relationship": "extends", "relationships": [...], "confidence": 0.9,
           "author_overlap": false, "verification_status": "verified",
           "excluded": false, "duplicate": false, "score": 39.95}
        ]
      }
    ]
  }
}
```

**This never pre-selects "the milestones."** Every classified work with a
year is included — background-mention and all — sorted by score within
its bucket. `--min-strength` is a query-time convenience (e.g. "hide
background-mention for this pass"), not a persisted decision; omit it to
see everything and decide the threshold in conversation with the human.
An excluded or confirmed-duplicate work is still shown (flagged, not
hidden) so nothing looks silently missing.

## 2. Periods — the curated unit

```bash
wake --json timeline period create "<seed>" <slug> --highlights ID,ID,... \
  [--label "..."] [--from YEAR] [--to YEAR] [--note "..."] \
  [--highlight-note ID='...']
```

`<slug>` is either:
- **a bare year** (e.g. `2012`) — an emergent single-year period; `--from`/
  `--to` default to that year if omitted.
- **a kebab-case named span** (e.g. `early-adoption`) — pair with
  `--from`/`--to` so the period has a defined place on the timeline.

Both are the same underlying shape; neither is enforced over the other —
sometimes the periodization is obvious up front, sometimes periods only
emerge as highlights get chosen.

Response shape:
```json
{
  "ok": true,
  "data": {
    "ok": true,
    "period_path": "wake-out/<seed>/timeline/periods/<slug>.md",
    "period_json_path": "wake-out/<seed>/timeline/periods/<slug>.json",
    "period_status": "draft",
    "highlights": [
      {"citing_id": "W111", "note": "First major reuse.", "status": "verified",
       "has_dossier": true, "title": "..."}
    ],
    "rebuild_needed": true
  }
}
```
`status` is each highlight's own current verification status (same
provisional/proposed/verified states as `evidence.md`) — `create` never
changes it, only displays it. Raises an error (non-`--json`: prints and
exits 1) if `--highlights` includes a work that's never been classified,
is excluded, or is a confirmed duplicate — same bars `wake theme create`
enforces. Always overwrites the same slug (no `--force`: nothing
expensive to protect against re-doing); `created_at` is preserved across
re-writes.

```bash
wake --json timeline period confirm "<seed>" <slug>
```
Refuses unless every highlighted work is already `verified` (re-resolved
fresh at confirm time, not from the period's own possibly-stale JSON) —
a confirmed period is an evidentiary claim about what mattered at that
point in the story, so it rests on the same bar `wake theme confirm`
enforces. On refusal (exits 1 in both `--json` and text mode):
```json
{"ok": true, "data": {"ok": false, "reason": "unverified_works", "unverified": ["W222"], "message": "..."}}
```
Note `"ok": true` at the envelope level even on refusal — check `data.ok`
for the actual outcome, same convention as `wake theme confirm`.

`wake timeline period show "<seed>" <slug>` re-emits the already-written
`.md` as-is, same as `wake theme show`.

## 3. Stitch — the working artifact and the handoff

```bash
wake --json timeline stitch "<seed>"
```

Assembles every period (chronological by `from_year`) into two files:

- **`timeline.md`** — the working, human-readable artifact (like
  `narrative.md`): every period, confirmed or draft, clearly labeled.
  Keep iterating on periods and re-running `stitch` as the team's
  understanding of the story develops.
- **`timeline.json`** — the **confirmed periods only** (draft periods
  never appear here) — the handoff to a separate Tufte-style
  graphic-rendering tool. A period only enters this file once a human
  has confirmed it rests on verified evidence.

Overlapping period ranges are reported (`data.overlaps`, and a callout in
`timeline.md`) but never blocked or auto-corrected — periodization is the
team's editorial call, same "report, don't enforce" rule as narrative
section reference validation.

`wake timeline show "<seed>"` re-emits the already-stitched `timeline.md`
as-is, same as `wake narrative show`.

Neither `period create`/`confirm` nor `stitch` render Markdown as a
write-time side effect — run `wake rebuild "<seed>"` after a batch of
period writes (see "Rendering the Wiki" in SKILL.md).
