# Classification (`wake classify`)

## Relationship Classes

Ordered by default strength, strongest first (also noting the nearest
[CiTO](https://sparontologies.github.io/cito/current/cito.html) (Citation
Typing Ontology) property, where one exists — this taxonomy was
deliberately aligned toward CiTO's naming in v0.4.21; see the
"CiTO Correspondence" section below):

| Class | Meaning | Nearest CiTO |
|-------|---------|--------------|
| `applies-to-domain` | Applies the seed's method to a new domain/problem (a special case of `uses-method-from`, kept distinct because domain transfer is its own useful signal) | `cito:usesMethodIn` |
| `uses-method-from` | Uses the seed's method, algorithm, or software tool — applied as-is or incorporated as a component/dependency of a new system | `cito:usesMethodIn` (exact) |
| `uses-data-from` | Uses the seed's dataset/data | `cito:usesDataFrom` (exact) |
| `extends` | Directly extends/modifies the seed's OWN method, framework, or theory | `cito:extends` (exact) |
| `benchmarks` | Benchmarks against the seed as a baseline | `cito:citesAsPotentialSolution` (weak — CiTO has no dedicated "baseline comparison" property) |
| `related` | Complementary work/infrastructure in the same ecosystem, an affirmative "these are related" judgment, without direct dependency | `cito:citesAsRelated` |
| `cites` | The fallback: cites the seed, but no more specific relationship is determinable (including unclear/indirect/merely contextual mentions) | `cito:cites` (exact — CiTO's own root "cites, unspecified" property) |

This exact set of seven labels is fixed — the LLM prompts spell each one
out verbatim, so the label set itself isn't configurable. What IS
configurable is how much each label counts when ranking citing works
(the "strength" in `strength × log(1 + cited_by_count)`, used by
`impact.md`'s "Strongest Evidence" and the evidence wiki's Verified/
Pending ordering — see `wake.config.yaml`'s
`classify.relationship_strength`). If an analysis cares more about
tooling adoption than domain reach, weight `uses-method-from` above
`applies-to-domain` there and re-run `wake bake` — no re-classification
needed, since strength is always recomputed from the stored relationship
label, never persisted alongside it. `wake config validate` catches a
typo'd or incomplete strength map before it silently misranks anything.

**`extends` vs. `uses-method-from`:** `extends` means the citing paper
changes the seed's method itself (a new variant, an improvement, a
theoretical generalization). `uses-method-from` means the citing paper
uses the seed's method unchanged — whether applying it as-is or
incorporating it as a dependency of something new it builds. A paper
that builds a new system on top of the seed's algorithm without
modifying that algorithm is `uses-method-from`, not `extends`.

**`related` vs. `cites`:** `related` is an affirmative judgment — the
citing work is genuinely adjacent (e.g. complementary tooling in the
same ecosystem) even though it doesn't depend on the seed. `cites` is
the true fallback — used when the text doesn't support any more
specific judgment at all, including `related`.

### CiTO Correspondence

wake's relationship classes are not a subset or superset of CiTO's ~40
citation sub-properties — they're purpose-built for bibliometric impact
analysis, and most have no CiTO equivalent (`applies-to-domain`,
`benchmarks`'s baseline-comparison sense) because CiTO doesn't model
domain transfer or performance benchmarking as citation types. Where a
real correspondence exists, wake's v0.4.21 refactor adopted CiTO's
naming/semantics directly (`extends`, `uses-method-from` ↔
`usesMethodIn`, `uses-data-from` ↔ `usesDataFrom`, `cites` ↔ CiTO's own
root property) rather than inventing parallel vocabulary. This is
documentation only — wake never emits a `cito:` IRI into any artifact.

## Multi-Facet Relationships (opt-in)

A citing paper's relationship to the seed is sometimes genuinely more
than one story — most commonly a paper that both uses the seed's
tool/software as-is *and* applies it to a new domain (`uses-method-from` +
`applies-to-domain`). Reducing that to a single label loses signal that's
right there in the abstract or full text. `classify` and `evidence` can
each return up to 3 facets — realistically almost always 1, occasionally
2, very rarely 3 — instead of forcing one:

```json
{
  "relationship": "uses-method-from",
  "confidence": 0.95,
  "justification": "...",
  "relationships": [
    {"label": "uses-method-from", "confidence": 0.95, "justification": "..."},
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
`uses-method-from` + `applies-to-domain` scores by whichever facet's
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
