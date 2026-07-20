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
