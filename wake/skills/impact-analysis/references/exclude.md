# Explicit Exclusion (`wake exclude` / `wake unexclude`)

A citing work judged not actually about the seed — e.g. a
`background-mention` where the seed appears only in a bibliography, a
poster/conference-abstract, or a work the human simply doesn't want
counted — previously had no way to be marked "considered and
deliberately out of scope" beyond an `override` to `background-mention`.
That leaves the work still fully usable: nothing stops a later theme or
narrative section from citing it, and nothing stops `wake gaps`/`wake
theme queue` from surfacing it again.

`wake exclude "<seed>" <citing-id> --reason "..." [--category CATEGORY]`
response shape:
```json
{
  "ok": true,
  "data": {
    "ok": true,
    "exclusions_path": "wake-out/<seed>/exclusions.jsonl",
    "citing_id": "W111",
    "excluded": true,
    "reason": "General HPC storage-architecture paper, not a domain-science adoption story.",
    "category": "irrelevant",
    "excluded_at": "..."
  }
}
```
`--reason` is required — an exclusion always needs a stated
justification. `--category` is one of `not-about-seed`,
`poster-or-abstract`, `irrelevant`, `other` (default `other`) — informal
grouping for at-a-glance review of `exclusions.jsonl`, no behavioral
difference between categories. Appends to `exclusions.jsonl`
(append-only, last-write-wins, same shape as `overrides.jsonl`/
`duplicates.jsonl`). Always run by the agent one work at a time after
explicit human sign-off — never a bulk operation.

`wake unexclude "<seed>" <citing-id> --reason "..."` response shape:
```json
{"ok": true, "data": {"ok": true, "exclusions_path": "...", "citing_id": "W111", "excluded": false, "reason": "...", "excluded_at": "..."}}
```
Reverses a prior exclusion — a separate, explicit action with its own
required justification, never an implicit side effect of some other
command. Raises an error if `citing_id` was never excluded in the first
place (nothing to undo).

## Downstream exclusion

An excluded work is unusable everywhere else in the packet:

| Where | Effect |
|---|---|
| `wake bake` | Dropped from reach metrics entirely. |
| `wake theme create` | Refuses if any `--citing-ids` entry is excluded, naming it explicitly. |
| `wake narrative section create` | Refuses if any `[ref:...]` marker names an excluded work — even if that work is itself independently human-verified (the realistic sequence: a work gets verified, and only later does a human notice on reflection that it shouldn't count). |
| `wake gaps` | Never surfaces an excluded work as an abstract-recovery candidate. |
| `wake theme queue` | Never surfaces an excluded work still in some theme's `needs_evidence` list as something worth chasing evidence for — computed fresh at query time, same as the existing `dossier-available-unreviewed` check, so an exclusion recorded *after* a theme was created is still honored. |

Excluding a work does not retroactively remove it from a theme's
`citing_ids` list if it was already cited there before the exclusion —
`create_theme()` only refuses *new* additions. If a theme already cites
a work that later gets excluded, re-run `wake theme create` with the
work dropped from `--citing-ids` (the same "re-assert, never silently
upgraded" pattern used for dossier changes via `wake theme queue`).
