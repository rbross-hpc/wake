# Thematic Synthesis (`wake theme`)

When several citing works together support a broader claim (e.g.
"extensive use in Earth system modeling"), synthesize them into one
document instead of listing them separately:

```bash
wake theme create <seed> earth-system-modeling \
  --title "Extensive use in Earth system modeling" \
  --summary "<synthesis paragraph you write, having read the underlying findings>" \
  --citing-ids W111,W222,W333
```

This is a pure write primitive — no LLM call. You (the agent) decide
which works belong together and write the synthesis after reading their
dossiers/classifications yourself; `wake` validates and persists that
judgment, the same way `wake override` persists a relationship judgment
without making one (see [`evidence.md`](evidence.md)). Always overwrites
(no `--force` needed — there's no expensive call to protect against
re-doing).

A theme carries **two independent verification tracks**, since it makes
two different kinds of claim:

- Each **cited work** keeps its own honest, existing status
  (`[PROVISIONAL]` / `[PROPOSED]` / `[VERIFIED]`) — creating a theme never
  upgrades a work's relationship status.
- The **theme's synthesis itself** starts `draft` and can only be
  promoted to `confirmed` via a human-approved sign-off:
  ```bash
  wake theme confirm <seed> earth-system-modeling
  ```
  Confirmation **refuses unless every cited work is already
  human-verified** (via `wake override`) — a theme can never appear
  settled while resting on unverified findings. Run by the agent on the
  human's behalf, same as `wake override`.

Works with no evidence dossier yet can still be included in a draft
theme (mixed sourcing) — track outstanding work with:
```bash
wake theme queue <seed>
```
which lists, per theme, citing works still needing a `wake evidence`
dossier, and works whose dossier has since appeared but hasn't been
reviewed and re-asserted (re-run `wake theme create` with the same slug
after reading the new dossier — its full-text finding may not actually
support the thematic claim the way the abstract-only guess did).

`wake theme show <seed> <slug>` re-prints an already-written theme
document (draft or confirmed) as-is.
