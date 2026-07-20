# Design discussion: reframing the theme workflow

> **Status: DESIGN CAPTURE ONLY — DO NOT EXECUTE.**
> This document exists to preserve the full context of a design
> conversation before it falls out of an agent's working context. No
> code, tests, or docs referenced here should change until this has been
> walked through live with the human and the open questions below are
> answered. `BACKLOG.md` links here and says the same thing.

## Where this came from

During the first live end-to-end validation run (Parallel netCDF,
408 citing works, 3 themes eventually confirmed), the workflow in
practice was: verify individual citing works one at a time via
`wake evidence` + `wake override`, and only once a meaningful cluster of
verified works existed, retroactively group them into a theme via
`wake theme create --citing-ids ...`. Themes were *discovered* after the
fact, not planned before the fact.

Partway through a later session, working through backlog notes, the
question came up directly: **"wait: what does `wake theme create`
*do*?"** The honest answer is that it's a pure write primitive — it
validates a `(title, summary, citing_ids)` triple the agent supplies and
persists it as `theme_status: draft`; it does no analysis, computes no
summary, and decides nothing about what belongs together. That's by
design (same trust model as `wake override`), but the *sequencing* it
implies — evidence first, theme identity second — was called into
question.

The reframe, in the human's words:

> "We get an outline first, with a set of themes in that outline. No
> wake steps there, just human and agent. Then we assign documents to
> the themes."

That is: **decide what the story's themes are going to be, as a planning
conversation between agent and human with no `wake` involvement at all**,
and only afterward start assigning specific citing works to those
themes as evidence accumulates. This is close to how a human researcher
actually writes a survey or a related-work section — you sketch the
shape of the argument first, then go find/organize evidence for each
part of it — and it's the opposite order from what `wake theme create`
currently forces.

## Current model

`wake theme create <seed> <slug> --title T --summary S --citing-ids
id,id,id,...`:

- Single atomic call. The theme's identity (slug, title, summary) and
  its evidence membership (citing_ids) are established in the same
  step.
- Always writes `theme_status: draft`, always overwrites (no `--force`
  — nothing expensive to protect against redoing).
- Every cited work is resolved to its own honest, current status
  (verified / proposed / provisional / unclassified) via
  `_resolve_work_status()` — `create_theme()` never upgrades a work's
  status, it just reports it.
- `needs_evidence` (cited works with no dossier yet) is tracked
  alongside — the design already tolerates a theme referencing
  not-yet-verified works, so partial evidence is not new. What's new in
  the reframe is tolerating a theme with *no evidence at all yet*, as a
  legitimate, nameable, plannable thing.
- `wake theme confirm` promotes `draft` → `confirmed`, refusing unless
  every cited work is currently verified (re-resolved fresh, not
  cached).

The friction: because identity and membership are the same write, there
is no way to say "I know this narrative needs an earth-system-adoption
theme, I haven't found the works for it yet, but I want to start
planning around its existence" without either (a) prematurely picking a
citing_ids list before you've actually verified anything, or (b)
waiting until evidence exists before the theme can be named at all.
Both are awkward for planning-first workflows.

## What stays the same under any version of the reframe

To keep the delta clearly visible:

- `wake theme confirm` — unchanged. Still refuses unless every cited
  work is currently verified, still re-checked fresh at confirm time.
- The "verified works only" bar for confirmation — unchanged. A theme
  can never appear settled while resting on unverified findings.
- `.overrides.jsonl` as the source of truth for "is this work verified"
  — unchanged (see `wake/themes.py`'s `_resolve_work_status()`,
  reused as-is by `wake/narrative.py`'s reference validation this
  session).
- `wake theme queue` — unchanged; still surfaces cited works needing a
  dossier or needing re-review.
- Two independent verification tracks (per-work relationship claims vs.
  the theme's synthesis claim) — unchanged; this reframe only touches
  *when* a theme can start existing, not the verification model itself.
- The trust model — wake still never decides what's thematically
  related and never writes synthesis prose; it validates and persists
  agent/human judgment. The reframe changes *how many steps* that
  judgment gets recorded in, not *who* makes the judgment.

## Design candidates

### (a) Two-phase themes: `theme declare` + `theme add` — leaning toward this

Split `wake theme create` into two distinct operations:

- **`wake theme declare <seed> <slug> --title T --description D`** — a
  scoping stub. No citing_ids at all (not even empty — the verb simply
  doesn't take that argument). No confirmation of its own, same as
  `narrative outline create`: a plan, not a claim. Always overwritable;
  `created_at` preserved across rewrites. Writes `theme_status: draft`
  with an explicit `citing_ids: []`.
- **`wake theme add <seed> <slug> <citing-id>`** — incrementally attach
  one already-classified work to an already-declared theme. Refuses if
  the theme doesn't exist yet (must `declare` first) or if the citing
  id isn't a real classified work for this seed. Appends to the
  theme's `citing_ids`, re-renders the theme markdown. Does not require
  the work to be verified yet (mirrors today's tolerance for
  `needs_evidence` members) — but see 5b below on whether `add` should
  accept more than one id per call.
- **`wake theme create`** retained, unchanged, as a compat shortcut
  equivalent to `declare` + repeated `add` calls in one shot — useful
  for the (still valid) case where evidence was gathered first and the
  theme is being named in a single retroactive step, as happened this
  session.

This makes the two operations conceptually distinct: **declaring what a
theme is** (pure planning, no evidence commitment, agent+human
conversation) vs. **assigning a specific work to a theme** (an evidence
commitment, each addition its own small claim). The declaring step is
naturally where an "outline of themes" lives — a set of `theme declare`
calls *is* the outline the human described.

### (b) Lighter `theme create`: allow empty `citing_ids`

Keep one verb. Let `--citing-ids` be optional/empty at creation time;
allow it to be extended by re-running `theme create` with an updated,
longer list.

Simpler diff (no new verb), but conflicts with `theme create`'s existing
"always overwrites" semantics: if re-running `create` with a longer
`citing_ids` list is how you add works one at a time, the caller has to
resupply the *entire* accumulated list every time (title and summary
included), which is exactly the kind of bulk, hard-to-audit-incrementally
operation the "human confirms one at a time" rule exists to prevent. You
could add a separate `theme add-works` verb on top of this to avoid that
problem — at which point you've arrived at candidate (a) anyway, just
with an extra no-op "create with nothing in it" step instead of a
purpose-built `declare`.

## Rejected alternative (worked through, not chosen)

**"Why not just let `theme create`'s `citing_ids` be empty and call it
done?"** — worked through under candidate (b) above. The core problem
isn't whether an empty list is *representable* (it easily is); it's that
`theme create`'s overwrite-with-full-payload semantics are wrong for an
*incremental, one-at-a-time* usage pattern once citing_ids is meant to
grow over multiple separate calls. An explicit `add` verb that appends
one id per call, refusing to blindly overwrite, is a better match to
"human confirms one at a time" than reusing `create` for both jobs.
Candidate (a) was chosen for the writeup's lean specifically because it
keeps `create`'s existing "always overwrite the whole payload" behavior
for the one case where it's actually correct (evidence gathered first,
theme named after) rather than stretching it to also handle incremental
growth.

## Open questions — unanswered, preserved verbatim for the eventual discussion

- **5a.** Explicit `theme declare` as a new verb (candidate a), or a
  lighter `theme create` that just accepts an empty/omitted
  `--citing-ids` (candidate b)? Current lean: (a), explicit verb,
  because declaring and assigning are different operations with
  different trust implications.
- **5b.** Should `wake theme add <seed> <slug> <citing-id>` accept
  multiple IDs in one call (`add ... W1 W2 W3`), or strictly one at a
  time? Given the standing "human confirms one at a time" rule
  (violated once this session via a mistaken bulk-verify, recovered via
  full revert), current lean is strictly one at a time — bulk `add`
  reopens the same failure mode in a new location.
- **5c.** When does a theme's `summary` get written: at `declare` time
  (a rough scoping paragraph, revisable), incrementally as works are
  `add`ed, or only once at `confirm` time when the theme is closed and
  all evidence is in? Current lean: rough summary at declare time,
  freely overwritable via re-running `declare` up to confirm time — the
  human needs *some* claim in mind to scope a theme even before evidence
  is attached, and it should be allowed to sharpen as evidence
  accumulates.
- **5d.** Does this reframe change `wake narrative outline` at all? A
  narrative outline's `kind: "theme"` components already reference
  declared-but-not-yet-confirmed themes (this was explicitly allowed
  from Theme F1's original design — "planning ahead of confirmation is
  fine"). Current lean: no change — a narrative outline is about
  presentation order and free-form framing, which is a different
  concern from evidence scoping, and the two structures should stay
  distinct even though they can end up looking similar in practice (a
  narrative planned around 3 themes, and a theme set with those same 3
  themes declared).

## Consequences for `wake narrative outline` (related to 5d, expand on resolution)

Once themes can be declared before any evidence exists, the *set of
declared themes* and the *set of narrative outline components* can
start to look very similar — both are, in effect, "the shape of the
argument, decided up front." It's tempting to imagine `narrative
outline create` deriving its `theme`-kind components directly from
whatever's been declared via `theme declare`, rather than requiring the
same theme slugs to be typed twice.

Resist collapsing them, at least initially: a narrative outline
legitimately contains `kind: "free"` components (intro, conclusion,
transitional framing) that have no theme backing at all, and a set of
declared themes may exist for a seed without any narrative ever being
drafted from them (e.g. themes used only to structure `wake bake`'s
evidence wiki, no narrative work planned). Keeping them as two related
but independent structures avoids forcing every theme to imply a
narrative and every narrative component to imply a theme. If, after
using two-phase themes for a while, it turns out `narrative outline
create` is *always* just "list the currently declared themes plus some
free framing," a convenience command (e.g. `wake narrative outline
from-themes <seed>`) could auto-populate an outline draft from declared
themes — but that's a follow-up optimization, not a structural merge,
and should wait until the two-phase theme workflow has actually been
used for a second real seed.

## Backward compatibility

Existing packets (including this session's live Parallel netCDF dry-run
packet) were built entirely with today's single-shot `theme create` —
every existing theme's JSON already has both identity fields and a
non-empty `citing_ids` in one document, indistinguishable from what a
`declare` + several `add` calls would eventually produce. Two options if
candidate (a) is chosen:

1. **No migration needed, by construction.** If `theme declare` and
   `theme add` write to the *same* `theme_json_path()`/`theme_path()`
   locations and the *same* JSON shape as today's `theme create` (just
   populated across multiple calls instead of one), an existing
   theme's JSON is already valid input to every downstream reader
   (`confirm_theme`, `narrative.py`'s theme-confirmation check,
   `wake theme queue`) with zero changes. `theme create` keeps working
   unmodified as the single-shot compat path. This is the cleaner
   option and should be the default assumption going in.
2. **Explicit migration command**, only if candidate (a)'s
   implementation ends up needing a schema change that (1) can't
   accommodate (e.g. a new required field distinguishing "declared, no
   evidence yet" from "created with evidence"). If needed: a `wake
   theme migrate <seed>` one-time pass that rewrites old-shape theme
   JSON into new-shape, run automatically and silently by any
   `theme add`/`theme declare` call that encounters an old-shape file,
   the same "migrate on first touch, no separate migration ceremony"
   pattern used elsewhere in wake for schema evolution.

Preference, pending implementation: option 1. Design `theme declare`
and `theme add`'s JSON output to be a strict subset/superset match of
today's `theme create` output, so no migration step is ever needed.

## Cross-references

- `BACKLOG.md`, Theme F1 section — Theme F1 (narrative drafting)
  explicitly allows a narrative outline to reference a theme "not
  required to be confirmed yet, since planning ahead of confirmation is
  fine." This reframe extends that same philosophy one level earlier:
  a theme need not even have evidence yet to be nameable.
- `wake/themes.py` docstring — the existing "two independent
  verification tracks" model (per-work status vs. theme synthesis
  status) is the foundation this reframe builds on top of, not a
  replacement for it.
- `wake/narrative.py`'s reference-marker validation (`_verified_ids`,
  `_check_packet_consistency`) — added the same session this reframe
  was proposed; reuses `themes.py`'s "verified means present in
  `.overrides.jsonl`" definition exactly. Any two-phase theme
  implementation should keep reusing that single definition rather than
  introducing a second one.
