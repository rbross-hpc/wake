# Thematic Synthesis (`wake theme`) — draft → confirmed

A theme combines several citing works into one synthesis document. It
has its own two-level lifecycle, independent of but layered on top of
each cited work's own provisional/proposed/verified status (see
`evidence.md`):

| Theme status | Set by | Meaning |
|---|---|---|
| `draft` | `wake theme create` (always, unconditionally) | Agent's synthesis judgment — not yet human-approved |
| `confirmed` | `wake theme confirm` (agent-run, after human sign-off) | Settled — refuses unless every cited work is already `verified` |

`wake theme create "<seed>" <slug> --title "..." --summary "..."
--citing-ids ID,ID,...` response shape:
```json
{
  "ok": true,
  "data": {
    "ok": true,
    "theme_path": "wake-out/<seed>/evidence/themes/<slug>.md",
    "theme_json_path": "wake-out/<seed>/evidence/themes/<slug>.json",
    "theme_status": "draft",
    "citing_works": [
      {"citing_id": "W111", "status": "verified", "has_dossier": true, "title": "..."},
      {"citing_id": "W222", "status": "proposed", "has_dossier": true, "title": "..."},
      {"citing_id": "W333", "status": "provisional", "has_dossier": false, "title": "..."}
    ],
    "needs_evidence": ["W333"]
  }
}
```
`status` here is each work's own current relationship-verification status
(same three values as the table above) — `create` never changes it, only
displays it. `needs_evidence` lists cited works with `status != "verified"`
and no dossier yet; a work verified via a plain `human-judgment` override
(no dossier at all) is correctly excluded from this list since it already
meets the confirmation bar. Raises an error (non-`--json`: prints and
exits 1) if any `--citing-ids` entry has never been classified.

Always overwrites the same slug — no `--force` flag exists for this
command, since there's no expensive LLM/network call to protect against
re-doing. `created_at` is preserved across re-writes; `updated_at` always
refreshes. Writes only `theme_json_path` -- `theme_path` (the `.md`) is
not rendered by this call; run `wake rebuild "<seed>"` (or `wake theme
rerender-all`) to render it (see "Rendering the Wiki" in SKILL.md).

`wake theme confirm "<seed>" <slug>` response shape on success:
```json
{"ok": true, "data": {"ok": true, "theme_path": "...", "theme_json_path": "...", "theme_status": "confirmed"}}
```
On refusal (exits 1 in both `--json` and text mode):
```json
{"ok": true, "data": {"ok": false, "reason": "unverified_works", "unverified": ["W222", "W333"], "message": "..."}}
```
Note `"ok": true` at the envelope level even on refusal — this is a
well-formed, expected response (like `fetch-pdf`'s `no_pdf` result), not
a crash; check `data.ok` for the actual outcome. Confirmation re-resolves
every cited work's status fresh at confirm time (not from the theme's own
possibly-stale JSON), so a work verified after the theme was created
still counts.

`wake theme queue "<seed>"` response shape:
```json
{
  "ok": true,
  "data": {
    "queue": [
      {"theme_slug": "earth-system-modeling", "citing_id": "W333", "status": "needs-evidence"},
      {"theme_slug": "earth-system-modeling", "citing_id": "W222", "status": "dossier-available-unreviewed"}
    ]
  }
}
```
`needs-evidence` — no dossier exists yet for this cited work.
`dossier-available-unreviewed` — a dossier has appeared (via an unrelated
`wake evidence` call) since the theme was last created/updated, but
hasn't been reviewed and re-asserted. This is computed fresh at query
time by cross-referencing each theme's `needs_evidence` list against
current dossier existence — **the theme's own JSON is never
auto-updated** when a dossier appears; only an explicit `wake theme
create` re-run (after reading the new dossier) changes it, so a
full-text finding that contradicts the original abstract-only guess can
never silently get folded into the theme unreviewed.

`wake theme show "<seed>" <slug>` prints the already-written
`evidence/themes/<slug>.md` (draft or confirmed) as-is — no computation,
just a re-emit, same as `wake show brief` re-emits `impact.md`:
```json
{"ok": true, "data": {"markdown": "..."}}
```
Errors (non-existent slug) the same way `wake show brief` does when
`impact.md` doesn't exist yet — a clear message naming the exact command
to run first, exit 1.

## Cross-link: "## Referenced By" in the rendered theme

Every theme `.md` shows a `## Referenced By` section listing every
narrative section grounded in it (i.e. naming this slug in its own
`theme_slugs`), plus a permanent `**See also:** [themes index](index.md)`
back-link. The "Referenced By" section is omitted entirely if no
narrative section grounds in this theme yet. Like the evidence dossier's
"Referenced by" line, this is a derived view, recomputed at render time
from narrative section JSON sidecars — never itself a separate thing to
maintain, but only recomputed when the theme is next rendered.
`wake narrative section create`/`confirm` write JSON only and do not
themselves re-render any theme `.md` -- run `wake rebuild "<seed>"` (or
`wake theme rerender-all`) to bring this section up to date.

## Re-rendering every theme (`wake theme rerender-all`)

```bash
wake --json theme rerender-all "<seed>"
```
Response shape: `{"ok": true, "data": {"ok": true, "rerendered": ["slug1", "slug2", ...], "count": N}}`.

A rendering-only pass over every `evidence/themes/<slug>.json` sidecar
already on disk: no change to any theme's own status, summary, or
citing-works list. Re-emits each `.md` from its `.json`, recomputing
derived content like the "Referenced By" section above. Use this after a
`wake` upgrade changes how themes render, to backfill an existing wiki.
