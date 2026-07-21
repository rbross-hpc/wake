# Environment Variables

`wake --json config validate` returns all three tiers' set/unset status in
one call (see SKILL.md step 0) — that's the canonical way an agent should
check these, rather than re-deriving this table.

| Tier | Variable | Purpose |
|------|----------|---------|
| Required | `OPENAI_API_KEY` | LLM API key (required for describe/classify) |
| Required | `OPENAI_BASE_URL` | API endpoint (e.g. Argo) |
| Recommended | `OPENALEX_MAILTO` | Your email for OpenAlex/Unpaywall/OSTI polite pool |
| Optional | `SEMANTICSCHOLAR_API_KEY` | Raises Semantic Scholar's unauthenticated rate limit |
| Optional | `CORE_API_KEY` | Enables CORE.ac.uk in `wake fetch-pdf` (free key at core.ac.uk/services/api) |
| Optional | `WAKE_WORK_DIR` | Default root for `wake-out/` cache |

`wake --json config validate` response shape:
```json
{
  "ok": true,
  "data": {
    "ok": true,
    "errors": [],
    "env": {
      "required": {"OPENAI_API_KEY": {"set": true, "value": null, "description": "..."}, ...},
      "recommended": {"OPENALEX_MAILTO": {"set": true, "value": "you@example.com", "description": "..."}},
      "optional": {"SEMANTICSCHOLAR_API_KEY": {"set": false, "value": null, "description": "..."}, ...}
    }
  }
}
```
Sensitive vars (anything with `KEY` in the name) never include their
actual value, even when set — only `"set": true/false`.

## Concurrency assumption

wake is designed for **single-process, serial access per seed directory**.
Running two wake commands against the same seed simultaneously (e.g. in two
shells) is not supported and may produce unexpected results:

- Append-only files (`overrides.jsonl`, `exclusions.jsonl`, `duplicates.jsonl`,
  `evidence/log.md`, etc.) use plain `O_APPEND` writes. Individual line
  writes are atomic on Linux for wake's line sizes (well under `PIPE_BUF`),
  so lines from concurrent writes won't be byte-interleaved — but two
  concurrent writers may land lines out of wall-clock order, and last-write-
  wins resolution (used everywhere) may produce counter-intuitive results.
- `classified.json` and `seed.json` are written atomically via `os.replace`,
  but a concurrent read mid-write will get either the old or new file, never
  a partial one.
- `wake bake` reads multiple files and writes `impact.md`/`impact.json`;
  concurrent modification of inputs between reads and the write can produce
  an inconsistent brief.

The safe usage pattern: run wake commands one at a time per seed, let each
complete before starting the next. Multi-seed parallelism (different seeds
in different work directories) is safe.
