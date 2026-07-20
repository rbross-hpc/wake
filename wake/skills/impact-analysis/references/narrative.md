# Narrative Drafting (`wake narrative`) — outline → sections (draft → confirmed) → stitch

A narrative is built from confirmed themes (see `themes.md`), one
component at a time. Three stages, none of which involve `wake` writing
prose itself:

| Stage | Command | What it does |
|---|---|---|
| Outline | `wake narrative outline create` | Plan the ordered section list before drafting any prose |
| Section | `wake narrative section create` / `section confirm` | Draft one section's prose, then get human sign-off |
| Stitch | `wake narrative stitch` | Assemble the outline order + every section into `narrative.md` |

`wake narrative outline create "<seed>" --components '[...]'` response shape:
```json
{
  "ok": true,
  "data": {
    "ok": true,
    "outline_path": "wake-out/<seed>/narrative/outline.md",
    "outline_json_path": "wake-out/<seed>/narrative/outline.json",
    "components": [
      {"slug": "intro", "title": "Introduction", "kind": "free", "theme_slugs": []},
      {"slug": "earth-adoption", "title": "Adoption in Earth System Modeling", "kind": "theme", "theme_slugs": ["earth-system-modeling"]}
    ]
  }
}
```
Each component needs `slug`/`title`/`kind` (`"theme"` or `"free"`).
`kind: "theme"` requires a non-empty `theme_slugs` list, each referencing
an already-existing theme (loadable via `wake theme create`) — it does
**not** need to be confirmed yet, only at section-confirm time.
`kind: "free"` must not include `theme_slugs`. Always overwrites (no
`--force` — nothing expensive to protect against re-doing); `created_at`
preserved across rewrites. Raises an error on a malformed component list
(bad kind, missing/extra theme_slugs, duplicate slug, or a theme
reference that doesn't exist).

`wake narrative section create "<seed>" <slug> --title "..." --prose
"..." [--theme-slugs SLUG,SLUG,...]` response shape:
```json
{
  "ok": true,
  "data": {
    "ok": true,
    "section_path": "wake-out/<seed>/narrative/sections/<slug>.md",
    "section_json_path": "wake-out/<seed>/narrative/sections/<slug>.json",
    "section_status": "draft",
    "kind": "theme",
    "theme_slugs": ["earth-system-modeling"]
  }
}
```
`kind` is inferred from whether `--theme-slugs` was passed (non-empty →
`"theme"`, else `"free"`). Always writes `"draft"` — drafting/redrafting
is an agent judgment, never itself a sign-off. A section can reference
*multiple* themes (e.g. a synthesis section spanning two of them). Always
overwrites the same slug; `created_at` preserved across rewrites.

## Inline source references

Every factual sentence in `--prose` should end with a `[ref:ID,ID,...]`
marker naming its source(s) — `SEED` for the seed paper itself, or a
citing work's OpenAlex ID for anything else. Framing sentences with no
factual claim don't need one. `create_section` validates every marker
before writing anything, in two passes:

1. **Packet consistency.** Every citing work this seed's own bookkeeping
   (`overrides.jsonl`) currently calls human-verified must have an
   actual dossier file on disk. If any are missing, the whole packet is
   refused as inconsistent — fix it (re-run `wake evidence`/`wake
   override`) before drafting any section.
2. **Per-marker validity.** Each ID named in a `[ref:...]` marker must be
   `SEED` or a citing work that is *currently* human-verified for this
   seed (same "verified" definition `wake theme confirm` uses: it went
   through `overrides.jsonl`, whether via a full evidence dossier or a
   plain `wake override` judgment call — `classified.json`'s own
   `verification_status` field is never updated in place and is not
   trusted here). Unknown or unverified IDs are rejected, naming every
   bad ID at once.

This guarantees every reference in the stitched narrative points at a
real, human-checked source. It does **not** guarantee the source actually
supports the sentence's specific claim — that remains an agent/human
judgment when drafting and confirming. A future `wake narrative section
audit` command (not yet built) is the intended place for a
claim-vs-dossier semantic check, kept deliberately separate.

The raw `[ref:...]` marker form is what's stored and shown everywhere
except the final stitched document: `section.json`'s `prose` field, the
per-section preview `section.md`, and `outline.md`'s status column all
keep markers as-written, so an agent/human iterating on one section can
see exactly which sources it cites.

`wake narrative section confirm "<seed>" <slug>` response shape on success:
```json
{"ok": true, "data": {"ok": true, "section_path": "...", "section_json_path": "...", "section_status": "confirmed"}}
```
On refusal (theme-backed section only; exits 1 in both `--json` and text mode):
```json
{"ok": true, "data": {"ok": false, "reason": "unconfirmed_themes", "unconfirmed": ["earth-system-modeling"], "message": "..."}}
```
Note `"ok": true` at the envelope level even on refusal, same convention
as `theme confirm` — check `data.ok`. Every referenced theme's status is
re-resolved **fresh** at confirm time (not from the section's own
possibly-stale JSON), so a theme that was confirmed when the section was
drafted but has since been reopened to draft (e.g. a new unverified work
was added to it) is caught, not silently ignored. A `"free"`-kind section
has no themes to check and confirms unconditionally.

`wake narrative stitch "<seed>"` response shape:
```json
{
  "ok": true,
  "data": {
    "ok": true,
    "narrative_path": "wake-out/<seed>/narrative.md",
    "confirmed_sections": 1,
    "draft_sections": 0,
    "missing_sections": ["conclusion"],
    "reference_count": 4
  }
}
```
Assembles every component in outline order. A component with no section
yet is rendered as a placeholder naming the exact `section create`
command to run. A drafted-but-unconfirmed section is rendered with its
prose plus a `⚠ DRAFT` banner — shown, not hidden, but clearly flagged.
Whenever anything is missing or still draft, the top of `narrative.md`
carries a "Partial narrative" note summarizing what's incomplete — same
"works on partial data, marks coverage" convention as `wake bake`.
Raises an error if no outline exists yet.

## Reference renumbering, stitch-time only

Every `[ref:ID,...]` marker across the whole document is renumbered to
`[R1]`, `[R2]`, ... in reading (outline) order — the first time a source
is cited, anywhere in the document, it gets the next number; every later
reuse of the same ID (even in a different section) reuses that same
number rather than getting a new one. This can only happen at stitch
time, once the whole document is assembled — earlier, per-section
previews don't know the final reading order, so they keep the raw
`[ref:...]` form. A Chicago-author-date-style `## References` section is
appended at the bottom, one entry per distinct ID in `R1...Rn` order,
e.g.:
```
1. Draxl, C., A. Clifton, B.-M. Hodge, and J. McCaa. 2015. "The Wind
   Integration National Dataset (WIND) Toolkit." Applied Energy. DOI:
   [10.1016/j.apenergy.2015.03.121](https://doi.org/10.1016/j.apenergy.2015.03.121).
```
Fields wake doesn't have for a given work (venue, DOI) are omitted
cleanly rather than rendered blank. `SEED` resolves to the seed's own
bibliographic fields; every other ID resolves to its entry in
`classified.json`. wake has no persisted OSTI identifier for any citing
work (OSTI is used only transiently, as one candidate PDF-acquisition
source, never written back into `classified.json`), so no OSTI suffix is
ever rendered. If no section uses any `[ref:...]` marker, no References
section is appended at all.
