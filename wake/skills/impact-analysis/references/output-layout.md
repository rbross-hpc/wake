# Output Layout

```
wake-out/<OpenAlex-ID>/
  seed.json               — resolved seed + LLM description
  citing.json             — all citing works (paginated, cached)
  classified.json         — per-citing-work relationship + evidence
                             (verification_status: "provisional" by default)
  impact.json             — aggregated metrics (includes verified_count)
  impact.md               — the impact brief (notes coverage if partial;
                             per-entry [PROVISIONAL]/[VERIFIED via ...] tags)
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
    <citing-id>.md          — OKF concept document (human/agent-readable)
    <citing-id>.json        — same finding, structured (for programmatic reuse)
    index.md                — OKF catalog: Verified / Pending Review, ranked
                               by score; regenerated automatically, no command
    log.md                  — OKF chronological log of every investigation
                               (built, rebuilt, failed, verified); append-only
    themes/                 — combined-evidence syntheses (wake theme create)
      <slug>.md               — OKF concept doc; draft or confirmed
      <slug>.json              — same theme, structured (citing_works, needs_evidence)
      index.md                 — OKF catalog: Confirmed / Draft
  narrative/               — narrative drafting (wake narrative)
    outline.md               — planned section order/status (wake narrative outline create)
    outline.json              — same, structured (components)
    sections/
      <slug>.md                — one section's prose; draft or confirmed
      <slug>.json               — same section, structured (kind, theme_slugs, prose)
  narrative.md             — assembled narrative (wake narrative stitch);
                              notes coverage if partial, same as impact.md
```

Use `--work-dir DIR` (or `WAKE_WORK_DIR` env var) to control where
`wake-out/` is created — useful when running from a scratch directory.
