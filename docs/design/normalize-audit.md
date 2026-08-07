# Audit: remaining `_normalize_*` / legacy-shape functions

Closes the Structural Hardening follow-on tracked in `BACKLOG.md` /
`PLAN.md` as "formalize the remaining `_normalize_*`/legacy-shape
functions using the migration-chain pattern." That item's premise —
that these are all deferred schema migrations waiting to be converted
to `migrate_*()` steps like the five persisted-artifact families in
`wake/models.py` — turns out not to hold uniformly once each function
is actually inspected. This audit inventories every remaining
`_normalize_*`/`_legacy_*` function in the codebase, determines which
category it actually belongs to, and records the evidence for that
determination. **Outcome: no schema migrations were missing.** Two
functions got a docstring clarification; everything else was already
correctly handled and needed no code change.

## Method

`rg -n 'def _normalize_|def _legacy|def migrate_|_VERSION\s*='` against
`wake/` found every candidate. Each was checked against its call sites
to determine what kind of data it operates on and when it runs.

## Category 1 — Input normalizers (not schema migrations)

These clean up strings arriving from external APIs or user input. They
have no relationship to on-disk schema versioning: there is no
"legacy shape" being read here, just untrusted/inconsistently-formatted
input being canonicalized before use, every time, regardless of when
the caller was built.

| Function | File | What it normalizes |
|---|---|---|
| `_normalize_doi` | `wake/sources/core.py:40` | DOI string (strip `https://doi.org/` prefix, lowercase) |
| `_normalize_doi` | `wake/sources/openalex.py:59` | same, OpenAlex-side copy |
| `_normalize_doi` | `wake/sources/osti.py:40` | same, OSTI-side copy |
| `_normalize_doi` | `wake/sources/semanticscholar.py:30` | same, Semantic Scholar-side copy |
| `_normalize_doi` | `wake/sources/springer.py:41` | same, Springer-side copy |
| `_normalize_doi` | `wake/sources/unpaywall.py:35` | same, Unpaywall-side copy |
| `_normalize_openalex_id` | `wake/sources/openalex.py:68` | OpenAlex work ID string shape |
| `_normalize_for_match` | `wake/pdf_verify.py:47` | text for fuzzy title/author matching |

**Determination:** out of scope. No action.

(The `_normalize_doi` duplication across six `sources/*.py` files is a
real small wart — six copies of the same ~5-line function — but it's a
DRY/refactor concern, not a schema-migration one, and is not part of
this audit's scope.)

## Category 2 — Legacy filesystem-location migrations (already formalized)

Three dotfile-to-plain-name renames (`.classify/` → `classify/`,
`.overrides.jsonl` → `overrides.jsonl`, `.manual_abstracts.jsonl` →
`manual_abstracts.jsonl`), each done for the same reason: a working
directory the human is explicitly expected to inspect shouldn't hide
files behind a dotfile convention meant for user-home/config
directories. These are *not* schema-shape changes — the file/dir
contents are unchanged, only its name/location — so they were
correctly built as an in-place rename mechanism rather than folded
into `models.py`'s `migrate_*()` pattern, which handles shape, not
location.

Each of the three follows the same verified invariant: the **write
path** calls `_migrate_legacy_*_if_needed()` (renames old → new in
place, no-op if new already exists or nothing to migrate), and the
**read path** falls back to the old name only if the new name doesn't
exist yet (read-only compat; it does not itself migrate).

| Family | Legacy path fn | Migrate-on-write fn (call site) | Read fallback (call site) |
|---|---|---|---|
| classify sidecars | `_legacy_sidecar_dir`/`_legacy_sidecar_path` (`wake/classify.py:388,413`) | `_migrate_legacy_sidecar_dir_if_needed` (`wake/classify.py:398`, invoked at `wake/classify.py:440` in `_write_sidecar`) | `_load_sidecar` (`wake/classify.py:417`) |
| overrides log | `_legacy_overrides_path` (`wake/report.py:26`) | `_migrate_legacy_overrides_if_needed` (`wake/report.py:36`, invoked at `wake/report.py:124,173`) | `load_overrides` (`wake/report.py:47`) |
| manual abstracts | `_legacy_manual_abstracts_path` (`wake/gaps.py:46`) | `_migrate_legacy_manual_abstracts_if_needed` (`wake/gaps.py:57`, invoked at `wake/gaps.py:120`) | `load_manual_abstracts` (`wake/gaps.py:68`) |

**Determination:** already formalized, correctly scoped outside
`models.py` (location migration, not shape migration), invariant
verified for all three. No action.

## Category 3 — Render-time facet-list view-derivers (not migrations)

| Function | File |
|---|---|
| `_normalize_relationships` | `wake/classify.py:347` |
| `_normalize_proposed_relationships` | `wake/evidence.py:489` |

These are the genuinely interesting case, and the reason this audit
was worth doing rather than mechanically converting everything. Both
synthesize a `relationships` facet-list from a pre-multi-facet
sidecar/dossier's legacy scalar `relationship`/`confidence`/
`justification` fields, for callers written after the multi-facet
classify format landed. Surface similarity to the five `migrate_*()`
families made them look like the same pattern. They are not, for three
reasons:

1. **They don't run at the persisted-file load boundary.** Every
   `migrate_*()` function runs once, at read time, on a whole raw
   persisted dict, and its output becomes the canonical in-memory form
   for the rest of that call. These two run at **build/render time**,
   on a **sub-block** (`finding["provisional"]`, a dossier's
   `proposed` block) that may not even be persisted yet —
   `evidence.py:353`'s call site passes `citing_work`, which can be
   data a classify call just produced in memory, never round-tripped
   through disk.

2. **Folding the classify-side one into `migrate_classification_result`
   would change a deliberately-loose contract.** `ClassifiedFile`'s
   docstring (`wake/models.py:182`) explains `works: list[dict[str,
   Any]]` is intentionally not `list[ClassificationResult]` because
   error/unclassified entries have no `relationship` key at all, and
   `migrate_classification_result` (`wake/models.py:214`) deliberately
   only stamps `schema_version` — no shape change. Making it also
   synthesize `relationships` would mean every classify-result read
   path starts guaranteeing a `relationships` key that the model
   doesn't require and some entries structurally can't have.

3. **The two functions aren't symmetric, so they can't collapse into
   one step.** `evidence._normalize_proposed_relationships` additionally
   carries `top_level_quotes` into the synthesized facet (dossier
   quotes have no analogue in a bare classify-result, which is
   abstract-only) — see its docstring's explicit note that it exists
   *because* "classify's generic normalizer doesn't know about
   [quotes], since classify's own facets ... never have quotes."

**Determination:** legitimately not schema migrations; they are
read-compat *view* helpers for callers that need a uniform
multi-facet shape regardless of whether the underlying data predates
the multi-facet format. Correctly kept as plain functions, not
`migrate_*()` steps. Action taken: clarified both docstrings to state
this explicitly and point here, so a future reader doesn't re-raise
the same "shouldn't this be a migration?" question without the
context to answer it. No behavior change; `tests/test_multi_facet_classify.py`'s
existing coverage of both functions (`test_normalize_relationships_*`)
is unaffected.

## Conclusion

All ~15 functions this audit's grep found are correctly implemented
for what they actually are. The backlog item is closed by this audit,
not by additional migration code — the original assessment's count of
"~15 implicit checks" (`docs/build-log.md`, migration-story-complete
summary) is accurate, and all ~15 are now confirmed either genuinely
out of scope (Category 1), already formalized via the appropriate
mechanism for their kind (Category 2), or intentionally not a schema
migration with the reasoning now on record (Category 3).
