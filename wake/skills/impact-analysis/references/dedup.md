# Duplicate Detection (`wake dedup`)

Three duplicate shapes a citing set can contain: a preprint and its
later-published version, a workshop paper and its expanded journal
version, and the same paper independently double-published (re-indexed
under two OpenAlex IDs). Left unmerged, each inflates reach metrics
(double-counted in "how many distinct works cite this"), can end up in
two different themes as if independent evidence, and can be cited twice
from a narrative as if two sources agreed rather than one.

`wake dedup candidates "<seed>"` response shape:
```json
{
  "ok": true,
  "data": {
    "count": 1,
    "candidates": [
      {
        "citing_id_a": "W111", "title_a": "...", "year_a": 2014, "type_a": "preprint", "venue_a": null,
        "citing_id_b": "W222", "title_b": "...", "year_b": 2015, "type_b": "article", "venue_b": "Some Journal",
        "title_similarity": 1.0,
        "likely_kind": "preprint-vs-published",
        "overlapping_authors": ["Alice Smith", "Bob Jones"]
      }
    ]
  }
}
```
Pure read, deterministic, no LLM call. A pair is surfaced only when
**both** conditions hold: title similarity (Unicode-normalized
SequenceMatcher ratio, same metric `wake/similarity.py` uses elsewhere)
≥ `--min-title-similarity` (default `0.85`), **and** at least one shared
OpenAlex author ID. Title similarity alone is deliberately insufficient
— live-tested against a real citing set, two unrelated "Reply on
RC1"/"Reply on RC2" peer-review threads by different single authors
would otherwise false-positive at 0.92 similarity purely from their
generic short titles.

`likely_kind` is `"preprint-vs-published"` when exactly one side has
OpenAlex `type: preprint` or is missing a venue entirely while the other
has a real one; otherwise `"possible-double-publication"` (e.g. two full
journal/conference venues, same title/authors). This is informational
only — both kinds go through the identical confirm/reject flow.

Pairs already decided (confirmed duplicate, or explicitly rejected as
not-a-duplicate) are excluded from future scans automatically — a
resolved question is never re-asked.

`wake dedup confirm "<seed>" <duplicate-id> <canonical-id> [--reason
"..."]` response shape:
```json
{"ok": true, "data": {"ok": true, "duplicates_path": "wake-out/<seed>/duplicates.jsonl", "duplicate_id": "W111", "canonical_id": "W222", "reason": "...", "confirmed_at": "..."}}
```
Appends one entry to `duplicates.jsonl` (append-only, last-write-wins,
same shape as `overrides.jsonl`). Always run by the agent one pair at a
time after explicit human sign-off — never a bulk operation. Raises an
error if `duplicate_id == canonical_id`, or if `canonical_id` is itself
already recorded as someone else's duplicate (duplicates are never
chained — every reference always points straight at the real canonical
work).

`wake dedup reject "<seed>" <id-a> <id-b> [--reason "..."]` response
shape:
```json
{"ok": true, "data": {"ok": true, "rejected_path": "wake-out/<seed>/dedup_rejected.jsonl", "id_a": "W111", "id_b": "W222", "reason": "...", "rejected_at": "..."}}
```
Records that a human looked at the pair and judged them genuinely
distinct — no downstream effect beyond excluding the pair from future
`dedup candidates` scans.

## Downstream exclusion

A confirmed duplicate is unusable everywhere else in the packet, always
pointing back at the canonical work:

| Where | Effect |
|---|---|
| `wake bake` | The duplicate is dropped from reach metrics entirely (the canonical work is already counted in its own right, so no re-merging is needed — just excluding the duplicate avoids double-counting). |
| `wake theme create` | Refuses if any `--citing-ids` entry is a confirmed duplicate, naming the canonical to cite instead. |
| `wake narrative section create` | Refuses if any `[ref:...]` marker names a confirmed duplicate, naming the canonical to cite instead — even if the duplicate ID is itself independently human-verified (a duplicate confirmed *after* both sides were separately verified is exactly the case this guards against). |

Duplicate resolution (`dedup.canonical_id_for()`) uses the same
`.jsonl`-log-and-resolve pattern as `overrides.jsonl`/`.overrides`
resolution elsewhere in the codebase — no special-casing per caller.
