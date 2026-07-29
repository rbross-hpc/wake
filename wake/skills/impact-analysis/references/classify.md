# Classification (`wake classify`)

## Relationship Classes

Ordered by default strength, strongest first:

| Class | Meaning |
|-------|---------|
| `extends` | Directly extends the method/framework/theory of the seed |
| `builds-on` | Builds a new system/tool that depends on the seed |
| `uses-as-tool` | Uses the seed's software/tool/dataset as-is |
| `benchmarks` | Benchmarks against the seed as a baseline |
| `applies-to-domain` | Applies the seed's approach to a new domain |
| `related-infrastructure` | Complementary tooling in the same ecosystem, no direct dependency |
| `background-mention` | Cites only as background/related work (including unclear/indirect relationships) |

This exact set of seven labels is fixed — the LLM prompts spell each one
out verbatim, so the label set itself isn't configurable. What IS
configurable is how much each label counts when ranking citing works
(the "strength" in `strength × log(1 + cited_by_count)`, used by
`impact.md`'s "Strongest Evidence" and the evidence wiki's Verified/
Pending ordering — see `wake.config.yaml`'s
`classify.relationship_strength`). If an analysis cares more about
domain reach than tooling adoption, weight `applies-to-domain` above
`uses-as-tool` there and re-run `wake bake` — no re-classification
needed, since strength is always recomputed from the stored relationship
label, never persisted alongside it. `wake config validate` catches a
typo'd or incomplete strength map before it silently misranks anything.

## Multi-Facet Relationships (opt-in)

A citing paper's relationship to the seed is sometimes genuinely more
than one story — most commonly a paper that both uses the seed's
tool/software as-is *and* applies it to a new domain (`uses-as-tool` +
`applies-to-domain`). Reducing that to a single label loses signal that's
right there in the abstract or full text. `classify` and `evidence` can
each return up to 3 facets — realistically almost always 1, occasionally
2, very rarely 3 — instead of forcing one:

```json
{
  "relationship": "uses-as-tool",
  "confidence": 0.95,
  "justification": "...",
  "relationships": [
    {"label": "uses-as-tool", "confidence": 0.95, "justification": "..."},
    {"label": "applies-to-domain", "confidence": 0.80, "justification": "..."}
  ]
}
```

`relationship`/`confidence`/`justification` are always the top
(most-confident) facet — every existing consumer (themes, narrative,
report metrics, CLI display) keeps reading these scalars unchanged
whether or not multi-facet is enabled. `relationships` is the full
ordered list (confidence-descending), for anything facet-aware. Every
facet has confidence ≥ 0.5; a facet the model isn't confident about
simply isn't returned rather than being included at low confidence.

**Ranking uses MAX across facets, not sum or average**: a work with
`uses-as-tool` + `applies-to-domain` scores by whichever facet's
configured strength is higher, not their combination — a second facet
adds signal to the dossier and the impact brief's display, but doesn't
by itself inflate a work's rank. `impact.md`'s "Relationship | Count | %"
table counts a multi-facet work under *every* facet it has, so rows can
sum to more than the classified total — the rendered brief footnotes
this when it happens (rare, since most works have exactly one facet).

**Opt-in, not a default.** The packaged `classify.prompt_version` /
`evidence.prompt_version` stay at the original single-label prompts
(`classify-2` / `evidence-1`) — multi-facet (`classify-3` / `evidence-2`)
is enabled per project by setting these in `wake.config.yaml`:
```yaml
classify:
  prompt_version: "classify-3"
evidence:
  prompt_version: "evidence-2"
```
Switching prompt versions invalidates every existing sidecar's cache
(same mechanism as any other prompt-version bump — see `classify_all`'s
prompt_version check), so this is deliberately not flipped on by an
upgrade alone; a seed already analyzed under classify-2 keeps its
single-label sidecars until re-classified.

A dossier's "## Provisional Classification" / "## Full-Text Reading"
sections render one subsection per facet when there's more than one
(each with its own justification and, for the full-text reading, its
own supporting passages) — invisible when there's only one facet, which
is the overwhelmingly common case.

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
