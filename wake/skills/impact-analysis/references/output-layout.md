# Output Layout

```
wake-out/<OpenAlex-ID>/
  README.md               — wiki home page: title + byline + links (with counts) to
                             impact.md / narrative.md / evidence/index.md /
                             evidence/themes/index.md, each omitted until its target
                             exists; regenerated automatically as a side effect of
                             bake/evidence/theme/narrative-stitch/override, no
                             separate command
  seed.json               — resolved seed + LLM description + seed_pdf sub-object
  seed.pdf                — the seed paper's own PDF (wake seed fetch-pdf; auto-attempted
                             at wake resolve time, silently skipped if unavailable)
  seed.pdf.json           — seed PDF full text, page-tagged (sibling cache, same format
                             as pdfs/<citing-id>.json)
  citing.json             — all citing works (paginated, cached)
  classified.json         — per-citing-work relationship + evidence
                             (verification_status: "provisional" by default)
  impact.json             — aggregated metrics (includes verified_count)
  impact.md               — the impact brief: OKF-style YAML frontmatter (seed
                             metadata, citing/verified/provisional counts,
                             themes/narrative status) + a "See also" nav line to the
                             evidence wiki/themes/narrative (each conditional on
                             existing); notes coverage if partial; per-entry
                             [PROVISIONAL]/[VERIFIED via ...] tags
  .state.json             — stage cache keys
  classify/               — per-work classification sidecars (resumable)
  .cost.jsonl             — per-LLM-call estimated token/cost log
  overrides.jsonl         — human-reviewed relationship overrides
                             (verification_status: "verified")
  .manual_abstracts.jsonl — human/PDF-recovered abstracts (wake fill-abstract)
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
  narrative.md             — assembled narrative (wake narrative stitch);
                              notes coverage if partial, same as impact.md
```

Use `--work-dir DIR` (or `WAKE_WORK_DIR` env var) to control where
`wake-out/` is created — useful when running from a scratch directory.
