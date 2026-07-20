# Poster/Conference-Abstract Surfacing (`wake posters`)

A citing set often contains a few poster-reception blurbs or short
conference abstracts that duplicate a full paper's content elsewhere in
the set — this session's "posters are out" rule was established ad hoc
mid-run before this command existed. `wake posters` surfaces these for
explicit human exclusion instead of requiring the human to remember to
ask, or silently dropping them.

`wake posters candidates "<seed>"` response shape:
```json
{
  "ok": true,
  "data": {
    "count": 1,
    "candidates": [
      {
        "citing_id": "W111",
        "title": "Poster: Bringing Task and Data Parallelism to Analysis of Climate Model Output",
        "year": 2012,
        "type": "conference-abstract",
        "matched_reason": "title starts with 'Poster:'"
      }
    ]
  }
}
```
Pure read, deterministic, no LLM call. A work is surfaced when **either**
signal is present: OpenAlex `type: conference-abstract`, or a
`Poster:`/`Abstract:` title prefix (checked regardless of `type`, so a
mistyped or mis-indexed OpenAlex type doesn't hide an obvious
title-prefix case). Ordinary titles that merely happen to start with the
word "Abstract" as English prose (e.g. "Abstraction Layers for..." —
note the colon requirement) don't match; only an exact `Poster:`/
`Abstract:` prefix does.

Already-excluded works (any `wake exclude` category) and
already-reviewed-and-kept works (via `wake posters keep`) are excluded
from the results automatically — a resolved question is never
re-surfaced.

`wake posters keep "<seed>" <citing-id> --reason "..."` response shape:
```json
{"ok": true, "data": {"ok": true, "reviewed_path": "wake-out/<seed>/posters_reviewed.jsonl", "citing_id": "W111", "decision": "keep", "reason": "...", "reviewed_at": "..."}}
```
Records that a human looked at a flagged candidate and decided it
should be kept as-is — e.g. a false positive, a real paper that happens
to be titled "Abstract: ...". No downstream effect beyond excluding it
from future `posters candidates` scans; the work remains fully usable.
`--reason` is required.

## Relationship to `wake exclude`

`wake posters` never excludes anything itself — it only surfaces
candidates. Once a human confirms a candidate really is a poster/
abstract stub worth dropping, exclude it the normal way:

```bash
wake exclude "<seed>" <citing-id> --reason "..." --category poster-or-abstract
```

See [`exclude.md`](exclude.md) for the full downstream-exclusion effect
(dropped from `wake bake`'s reach metrics, refused by `wake theme
create` and `wake narrative` reference validation, no longer surfaced by
`wake gaps`/`wake theme queue`).
