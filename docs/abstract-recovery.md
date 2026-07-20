# Abstract Recovery

~20% of citing works typically lack an OpenAlex abstract, forcing lower-
confidence title/venue-only classification. `wake` recovers most of these
automatically and lazily (only for works actually selected for
classification, never eagerly for the full citing set):

1. **Automatic backfill** (`classify` does this transparently): tries
   [OSTI](https://www.osti.gov) (DOE-funded work, via its `description`
   field), then [Semantic Scholar](https://www.semanticscholar.org)
   (broader coverage). Free, unauthenticated, no PDF dependency.
2. **Manual escalation** for high-value works that step 1 couldn't resolve:
   ```bash
   wake gaps <seed>                          # surface candidates, ranked by influence
   wake fill-abstract <seed> <id> --from-pdf paper.pdf   # extract from PDF lead pages + LLM cleanup
   wake fill-abstract <seed> <id> --text "..."           # or paste the abstract directly
   wake classify <seed> --ids <id> --force   # re-classify with the recovered abstract
   ```
   `--from-pdf` only ever reads the first few pages (config
   `pdf_extract.max_pages`, default 3) — if the abstract isn't in the front
   matter, it isn't reported as found. Requires the `pdf` extra
   (`pip install 'wake[pdf]'`).

Recovered abstracts are tagged with their source (`abstract_source`:
`osti`, `semanticscholar`, `pdf-extract`, or `human-text`) and the count is
shown in the brief's Reach section.
