# Output Layout

```
wake-out/<OpenAlex-ID>/
  README.md               — human-oriented wiki home page: title + byline, a "What
                             this folder is" paragraph, a "What was done" summary
                             (counts, only for stages that have actually run --
                             including a call-out if the seed's own PDF was
                             auto-attempted and failed to acquire), a "Where to
                             start" section linking impact.md / narrative.md /
                             evidence/index.md / evidence/themes/index.md /
                             evidence/log.md (each omitted until its target exists),
                             reading conventions, and the four human-editable .jsonl
                             files; regenerated automatically as a side effect of
                             bake/evidence/theme/narrative-stitch/override, no
                             separate command -- same trigger as AGENTS.md below,
                             both built by evidence_wiki.rebuild_wiki_orientation()
  AGENTS.md                — agent-oriented orientation: for an agent handed just
                             this folder, with no access to wake's own source and
                             possibly wake not even installed. Terse schema
                             reference (every artifact type's fields, the .md=human/
                             .json=agent surface convention, relative-path rule,
                             regeneration verbs, a "Seed PDF: cached/attempted and
                             failed/not attempted yet" status line, and a handful
                             of concrete query recipes) rather than README.md's
                             explanatory prose. Carries no YAML frontmatter (unlike
                             every other rendered .md here) -- it's a plain
                             reference doc, not an OKF concept doc. Same
                             regeneration trigger as README.md
  seed.json               — resolved seed + LLM description + seed_pdf sub-object
                             (path/source on success; tried/fallback_links on
                             failure -- see evidence_wiki.seed_pdf_status(), the
                             single source of truth README.md/AGENTS.md/impact.md
                             all read this from)
  seed.pdf                — the seed paper's own PDF (wake seed fetch-pdf; auto-attempted
                             at wake resolve time, silently skipped if unavailable --
                             a failed attempt is never invisible for long, though:
                             it's surfaced in README.md/AGENTS.md/impact.md's
                             seed_pdf_status until someone supplies a copy)
  seed.pdf.json           — seed PDF full text, page-tagged (sibling cache, same format
                             as pdfs/<citing-id>.json)
  citing.json             — all citing works (paginated, cached)
  classified.json         — per-citing-work relationship + evidence
                             (verification_status: "provisional" by default)
  impact.json             — aggregated metrics (includes verified_count)
  impact.md               — the impact brief: OKF-style YAML frontmatter (seed
                             metadata, citing/verified/provisional counts,
                             themes/narrative status, seed_pdf_status) + a "See
                             also" nav line to the evidence wiki/themes/narrative
                             (each conditional on existing); notes coverage if
                             partial; per-entry
                             [PROVISIONAL]/[VERIFIED via ...] tags. Each "Strongest
                             Evidence" entry's title links to its evidence dossier
                             (when one exists), and its DOI/OpenAlex ID are both
                             rendered as links
  .state.json             — stage cache keys
  classify/               — per-work classification sidecars (resumable)
  .cost.jsonl             — per-LLM-call estimated token/cost log
  overrides.jsonl         — human-reviewed relationship overrides
                             (verification_status: "verified")
  manual_abstracts.jsonl  — human/PDF-recovered abstracts (wake fill-abstract)
  pdfs/                   — locally-cached PDFs (wake fetch-pdf / wake evidence)
    <citing-id>.pdf         — the PDF itself
    <citing-id>.json        — its extracted text, cached (pdf_sha256-keyed;
                               see evidence.md's "Diagnosing a surprising finding")
  evidence/                — full-text verification dossiers (wake evidence)
    <citing-id>.md          — OKF concept document (human/agent-readable); shows a
                               "Referenced by:" line naming every theme/narrative
                               section currently citing this work, when any do
                               (derived at render time, refreshed automatically by
                               theme/section writes and `wake evidence rerender-all`)
    <citing-id>.json        — same finding, structured (for programmatic reuse)
    index.md                — OKF catalog: Verified / Pending Review, ranked
                               by score; regenerated automatically, no command
    log.md                  — OKF chronological log of every investigation
                               (built, rebuilt, failed, verified, pdf_fetched,
                               pdf_fetch_failed); append-only. All append-only
                               files in this directory assume single-process
                               serial access per seed -- see environment.md.
    themes/                 — combined-evidence syntheses (wake theme create)
      <slug>.md               — OKF concept doc; draft or confirmed; shows a
                                 "## Referenced By" section naming narrative
                                 sections grounded in it (when any exist) and a
                                 permanent back-link to themes/index.md
      <slug>.json              — same theme, structured (citing_works, needs_evidence)
      index.md                 — OKF catalog: Confirmed / Draft
  narrative/               — narrative drafting (wake narrative)
    outline.md               — planned section order/status (wake narrative outline create)
    outline.json              — same, structured (components)
    sections/
      <slug>.md                — one section's prose; draft or confirmed. Every
                                 [ref:ID] marker in the rendered prose (only here,
                                 not in the .json or the stitched narrative.md) is
                                 a link to that work's evidence dossier (or
                                 impact.md for SEED) when the dossier exists;
                                 otherwise left as the raw marker
      <slug>.json               — same section, structured (kind, theme_slugs, prose)
  narrative.md             — assembled narrative (wake narrative stitch): OKF-style
                              YAML frontmatter (seed + confirmed/draft/missing
                              section counts, reference_count) + the R-numbered
                              stitched prose; notes coverage if partial, same as
                              impact.md
```

Use `--work-dir DIR` (or `WAKE_WORK_DIR` env var) to control where
`wake-out/` is created — useful when running from a scratch directory.

## File format conventions

Every wiki concept doc (dossier, theme, narrative section, `impact.md`,
`narrative.md`) is a **`.md` + `.json` pair**: the `.json` is the source
of truth (structured, safe to regenerate the `.md` from — see each
subsystem's `rerender-all` verb), the `.md` is the derived human view,
opening with an OKF-style YAML frontmatter block (`type`, `status`/
counts, `timestamp`) so a human or tool can skim structured metadata
without parsing prose. `README.md`, `AGENTS.md`, and the `index.md`/
`log.md`/`themes/index.md` catalogs are the only `.md` files with no
`.json` sidecar of their own — they're 100% derived from other files
that already have one, so a sidecar would just duplicate data.
`AGENTS.md` additionally carries no YAML frontmatter at all (unlike
every other file in this list) — it's a plain reference doc in the
same spirit as a project's own `AGENTS.md`, not an OKF concept doc.

Append-only human/agent decisions (`overrides.jsonl`, `duplicates.jsonl`,
`exclusions.jsonl`, `manual_abstracts.jsonl`) use `.jsonl`, one JSON
object per line, last-write-wins on replay — never rewritten in place,
only appended to.

A working directory under `wake-out/<seed>/` is explicitly meant for a
human to inspect directly, so anything **human-facing** (the human's own
verification decisions, human-supplied data, debuggable raw per-work LLM
output) is a plain, visible filename — never hidden behind a dotfile.
Only genuinely internal bookkeeping the human isn't expected to read
directly (`.state.json`'s stage-cache keys, `.cost.jsonl`'s per-call
token/cost ledger) stays a dotfile.

**`.md` is the human surface, `.json` is the agent surface.** An agent
should always read a subsystem's `.json` (or a verb's `--json` response),
never scrape prose out of a rendered `.md` — the `.md` exists so a human
can browse the wiki (in a plain editor or Obsidian) without needing to
run any tooling. The one deliberate exception is an evidence dossier's
extraction cache (`pdfs/<citing-id>.json`): it's linked directly from the
dossier's "## Source" section because it's the only artifact that
answers "did the model see garbled text?", and there's no separate
human-readable rendering of it to link instead (the PDF itself is
already linked as a *different* bullet in the same section). Every other
`.json` in the tree is agent-only.

**Cross-file paths inside `wake-out/<seed>/` are always relative to the
file that contains them**, both in a `.md`'s frontmatter/body links and
in a `.json` sidecar's own path-valued fields (e.g. an evidence
dossier's frontmatter `pdf:` key and its `.json` sidecar's `pdf_path`
field both read `../pdfs/<citing-id>.pdf`, relative to `evidence/`) — so
the whole seed directory stays self-consistent if it's ever moved,
copied, or shared as a zip. `wake evidence --rerender-all` opportunistically
normalizes any older, absolute-path dossier JSON it encounters the next
time it re-renders that dossier.

**Persisted JSON records evidence, not derived scores.** A classify
sidecar or an override records the relationship *label* the LLM/human
assigned — never a "strength" or rank score computed from that label.
Anything computable from a label plus the current config
(`classify.relationship_strength`) is recomputed fresh every time it's
needed (`report.relationship_score()`), not baked into the stored
record. This is what makes reweighting relationship strengths a pure
config edit: change `classify.relationship_strength` in
`wake.config.yaml`, re-run `wake bake`, and every ranking (impact.md's
"Strongest Evidence" table, the evidence wiki's Verified/Pending
ordering) reflects the new weights immediately — no re-classification,
no touching a single sidecar on disk.
