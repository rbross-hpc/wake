# AGENTS.md — orientation for an agent handed this folder

This folder is a **citation-impact analysis** of one seed paper, produced by [wake](https://github.com/rbross-hpc/wake). Every file here is one of a small number of artifact types, each with a stable schema described below. This file is self-contained — you do not need wake installed, or access to its source, to read the data in this folder.

## Seed paper

- Title: Toward a persistent event-streaming system for high-performance computing applications
- Year: 2025
- DOI: 10.3389/fhpcp.2025.1638203
- OpenAlex ID: W4414299303
- Citing works fetched: 4
- Citing works classified: 4
- Full-text-verified: 2
- Confirmed themes: 0
- Narrative status: assembled
- Seed PDF: cached

## Two-surface convention

- **`.md` files** are the human surface: rendered prose, meant to be read by a person in Obsidian, GitHub, or a plain editor.
- **`.json` sidecars** are the agent surface. Every `.md` concept doc (dossier, theme, narrative section, impact brief) has a `.json` alongside it with the same information in structured form. **If you're programmatically extracting a finding, read the `.json`, never scrape prose out of the `.md`.**
- Exception: `README.md`, `evidence/index.md`, `evidence/log.md`, and `evidence/themes/index.md` are pure catalogs with no JSON of their own — every fact in them is already in some other file's JSON sidecar.

## Frontmatter `type:` values

Every rendered `.md` in this folder (except this file and README.md) opens with a YAML frontmatter block whose `type:` key is one of:

- `wiki-home` — README.md
- `impact-brief` — impact.md
- `narrative` — narrative.md
- `narrative-outline` — narrative/outline.md
- `narrative-section` — narrative/sections/<slug>.md
- `theme` — evidence/themes/<slug>.md
- `citing-work-evidence` — evidence/<id>.md
- `index` — evidence/index.md, evidence/themes/index.md
- `log` — evidence/log.md

## File map

```
seed.json               resolved seed metadata + LLM description
citing.json             every citing work fetched from OpenAlex
classified.json         per-citing-work relationship classification
impact.json / .md       aggregated reach metrics + ranked evidence
narrative.md            assembled prose (sections live in narrative/)
overrides.jsonl         human-reviewed relationship corrections
duplicates.jsonl        citing works marked as duplicates of another
exclusions.jsonl        citing works excluded from theme synthesis
manual_abstracts.jsonl  human/PDF-recovered abstracts
pdfs/<id>.pdf           cached PDF for a citing work
pdfs/<id>.pdf.json      its extracted text, page-tagged
evidence/<id>.md/.json  full-text verification dossier for a citing work
evidence/index.md       dossier catalog: Verified / Pending Review
evidence/log.md         chronological investigation history
evidence/themes/*.md/.json     combined-evidence theme docs
evidence/themes/index.md      theme catalog: Confirmed / Draft
narrative/sections/*.md/.json  individual narrative section prose
narrative/outline.md/.json     planned section order/status
```

## Schemas

### `citing-work-evidence` — `evidence/<id>.json`

Keys: `citing_openalex_id`, `verification_status` (`verified` | `pending-human-review`), `provisional` (abstract-only guess: `relationship`, `confidence`, `justification`), `proposed` (full-text reading: `relationships` — a list of up to 3 facets, each `{label, confidence, justification, quotes, verified}` — plus legacy `relationship`/`confidence`/`justification` scalars mirroring the top facet), `quotes` (page-numbered supporting passages), `pdf_path`, `extracted_text_path`, `author_overlap`.
Relationship labels (fixed set of 7): `extends`, `builds-on`, `uses-as-tool`, `benchmarks`, `applies-to-domain`, `related-infrastructure`, `background-mention`. A citing work can have more than one facet (e.g. both `uses-as-tool` and `applies-to-domain`); ranking uses the strongest facet, not a sum.
The `.md`'s own frontmatter carries the same status at a glance: `verification_status`, `provisional_relationships` (label list), `proposed_relationships` (label list), and `author_overlap` (present only when `true`) — enough to filter dossiers without opening the `.json`.

### `theme` — `evidence/themes/<slug>.json`

Keys: `slug`, `title`, `theme_status` (`draft` | `confirmed`), `summary` (synthesis prose), `citing_works` (list of `{citing_id, status, has_dossier, title}`), `needs_evidence`.
The `.md`'s frontmatter mirrors `theme_status` directly.

### `narrative-section` — `narrative/sections/<slug>.json`

Keys: `slug`, `title`, `kind`, `theme_slugs`, `status` (`draft` | `confirmed`), `prose` (with `[ref:ID]` markers, resolved to dossier links only in the rendered `.md`).
The `.md`'s frontmatter carries `kind` and `section_status` (the JSON's `status`, renamed to avoid colliding with a dossier's `verification_status` in a vault-wide query).

### `impact-brief` — `impact.json`

Keys: `seed_openalex_id`, `total_citing_works`, `classified_count`, `verified_count`, `self_extension_count`, `coverage`, `by_year`, `by_relationship` (counts per label, one work may count under more than one), `by_venue_type`, `top_fields`, `top_evidence` (ranked list).

### Append-only decision logs (`*.jsonl`)

One JSON object per line; later lines for the same `citing_id` win on replay. Never rewritten in place, only appended to.

- `overrides.jsonl` — `{citing_id, relationship, justification, confidence, verification_status, overridden_at}`
- `duplicates.jsonl` — `{duplicate_id, canonical_id, reason, confirmed_at}`
- `exclusions.jsonl` — `{citing_id, excluded, reason, category, excluded_at}`
- `manual_abstracts.jsonl` — `{citing_id, abstract, source, added_at}`

## Cross-file references

All paths inside this folder are relative to the file containing them, both in `.md` link syntax and in JSON path fields (e.g. a dossier's `pdf_path` reads `../pdfs/<id>.pdf`, relative to `evidence/`).

## Regenerating derived files

If you have wake installed (`pip install wake`), `wake rebuild <seed>` resyncs every derived file below (dossiers, evidence/index.md, theme docs + their index, narrative outline/sections/narrative.md, impact.md, and this folder's own README.md/AGENTS.md) from whatever JSON is already on disk, in one call, with no LLM/network calls — e.g. after hand-editing a JSON sidecar, or restoring from a partial backup. It skips any artifact type that has no JSON backing yet for this seed.

Individual verbs remain available for a narrower, targeted re-render instead of the full `wake rebuild`:

- `wake bake` — regenerate impact.md/json and this folder's orientation files
- `wake evidence --rerender-all` — regenerate all dossier .md files from .json
- `wake theme rerender-all` — regenerate all theme .md files from .json
- `wake narrative section rerender-all` — regenerate all section .md files from .json
- `wake narrative stitch` — regenerate narrative.md from sections

If wake is not installed, every `.md`/`.json` file here remains directly readable — none of them require wake to interpret, only to regenerate.

## Query patterns

- **Which works cite the seed as `uses-as-tool`?** Read `classified.json`, filter `relationships[].label == "uses-as-tool"` (or the legacy `relationship` scalar).
- **Show me all verified findings.** Read `evidence/<id>.json` for each entry in `evidence/index.md`, filter `verification_status == "verified"`. Or read `overrides.jsonl` for only the human-signed-off ones.
- **What did the citing paper actually say?** Read `pdfs/<id>.pdf.json` — the raw, page-tagged extracted text, the same input the LLM was given.
- **Show provenance of a specific finding.** A dossier's `proposed.relationships[].quotes` list carries page-numbered verbatim passages.
- **Is this citing work independent, or the same team's own follow-on?** Check `author_overlap` / `overlapping_authors` on the classified/dossier entry.
