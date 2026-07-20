# Classification (`wake classify`)

## Relationship Classes

Ordered by strength, strongest first:

| Class | Meaning |
|-------|---------|
| `extends` | Directly extends the method/framework/theory of the seed |
| `builds-on` | Builds a new system/tool that depends on the seed |
| `uses-as-tool` | Uses the seed's software/tool/dataset as-is |
| `benchmarks` | Benchmarks against the seed as a baseline |
| `applies-to-domain` | Applies the seed's approach to a new domain |
| `related-infrastructure` | Complementary tooling in the same ecosystem, no direct dependency |
| `background-mention` | Cites only as background/related work (including unclear/indirect relationships) |

### Author-Overlap Tag (orthogonal to relationship)

Every `classify` and `evidence` result also carries `author_overlap`
(bool) + `overlapping_authors` (list of names) — computed deterministically
by intersecting OpenAlex author IDs between the seed and citing work, no
LLM call. Not a relationship class of its own: `extends` +
`author_overlap: true` (the original team's own follow-on paper) and
`extends` + `author_overlap: false` (an independent third-party
extension) are both still `extends`, just different stories for a
narrative. Surfaced in the brief as a `[SELF-EXTENSION — seed's own
team]` tag in "Strongest Evidence" and a `self_extension_count` summary
line in "Nature of Impact" (`impact.json`).
