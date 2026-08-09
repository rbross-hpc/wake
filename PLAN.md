# PLAN — wake

## Goal

Given a seed paper (DOI, arXiv ID, OpenAlex ID, or title), produce an evidence-backed impact brief:
describe what the paper contributes, fetch every work that cites it, use an LLM to classify how
each citing work uses the paper, surface the strongest evidence of real impact, and render a
Markdown report.

## Motivation

OpenAlex `filter=cites:<work_id>` returns all citing works with metadata (year, venue, type, own
`cited_by_count`, and ~68% have abstracts via inverted index). Neither existing sibling repo
(ref-checker, pub-analysis) traverses this. Verified working against "Parallel netCDF" (2003),
W2156077349, 408 citing works.

## What We Reuse (vendored, self-contained)

From **ref-checker**:
- `sources/openalex.py` → adapted & extended with citing-works traversal (the new core)
- `sources/_http.py`, `errors.py`, `similarity.py` → copied as-is
- CLI argparse structure & polite-pool rate limiter pattern → template for wake's CLI
- Skill scaffolding → bundled agent skill pattern

From **pub-analysis**:
- `config.py` + `config.yaml` → adapted
- `llm/openai_client.py` (chat_json/chat_text with tenacity retries) → copied
- `state.py` + `io.py` (atomic writes, sha/version cache keying) → adapted for seed-id keying
- Prompt-runner pattern → template for classification & narrative prompts

## New Capability

`sources/openalex.py::iter_citing_works` — cursor-paginated traversal of all citing works,
rate-limited, with per-page=200 for efficiency.

## Architecture

```
wake/
  __init__.py        # __version__
  __main__.py
  config.py          # packaged + local override (wake.config.yaml)
  config.yaml        # packaged defaults
  errors.py          # RateLimited, SeedNotFound, OpenAlexError
  similarity.py      # title_ratio (vendored)
  io.py              # atomic writes, sha256, now_iso
  state.py           # .state.json per-seed cache management
  sources/
    _http.py         # raise_for_rate_limit, parse_retry_after
    openalex.py      # resolve seed + cited_by cursor traversal (NEW)
  seed.py            # resolve + cache seed → seed.json
  citing.py          # fetch + cache all citing works → citing.json
  describe.py        # LLM contribution paragraph → seed.json (description field)
  classify.py        # LLM per-citing-work relationship → .classify/ sidecars + classified.json
  report.py          # assemble impact.md + impact.json
  llm/
    openai_client.py # chat_json / chat_text with tenacity
  cli/
    main.py          # argparse dispatcher
    skill.py         # skill subcommand
  skills/
    impact-analysis/
      SKILL.md       # bundled agent skill
tests/
  conftest.py        # shared fixtures (offline work dicts)
  test_similarity.py
  test_io.py
  test_state.py
  test_seed.py
  test_classify.py
  test_report.py
  test_openalex.py
pyproject.toml
README.md
PLAN.md
LICENSE
```

## Design Decisions

- **Rate limiting**: time.sleep between OpenAlex pages (configurable via `openalex.rate_limit_s`).
- **Resumability**: classification writes an atomic JSON sidecar per work in `.classify/` —
  safe Ctrl-C, re-run skips done works.
- **Graceful degradation**: works lacking abstracts are classified from title+venue only;
  confidence is set ≤ 0.5.
- **Caching**: `.state.json` keyed by seed_id + prompt_version + tool_version + model.
- **No PDF/MinerU**: seed metadata & abstract come from OpenAlex (lightweight).
- **Output dir**: `wake-out/<work-id>/` (avoids name collision with the `wake` package).

## Ranking (Top Evidence)

Score = relationship_strength × log(1 + downstream_cited_by_count)

Relationship strengths (default, highest to lowest — configurable via
`classify.relationship_strength` in `wake.config.yaml`):
  applies-to-domain (7) > uses-method-from (6) = uses-data-from (6) >
  extends (5) > benchmarks (3) > related (2) > cites (1)

---

## Build history moved

Per-version build history (v0.2 through the present) — what was built,
why, bugs found and fixed, and how each phase was verified — now lives
in [`docs/build-log.md`](docs/build-log.md), an append-only engineering
journal. This file (`PLAN.md`) stays a short, current design charter
plus the active forward-looking plan (below); it does not accumulate
retrospective entries.

Existing code/config comments citing `PLAN.md "Phase N"` or `PLAN.md
v0.4.x` refer to entries now in `docs/build-log.md` — heading text and
version numbers are unchanged, so those references still resolve there.

For the open product/engineering roadmap (deferred features, held
designs, not-yet-built items), see [`BACKLOG.md`](BACKLOG.md). For the
design rationale behind already-shipped BACKLOG-tracked product themes,
see
[`docs/design/backlog-built-history.md`](docs/design/backlog-built-history.md).

---

## Current Plan — What's Next

The Structural Hardening effort (`docs/build-log.md`, "Phase 3") closed
its six original phases plus a four-phase migration-story follow-on
(v0.4.0–v0.4.12): CI/lint/typecheck, explicit Pydantic domain models,
`WakeContext`, a centralized build layer (`wake rebuild`), the
`cli/main.py` split, LLM retry-policy hardening, and schema-versioning
(with migration) across all five persisted artifact families (dossiers,
themes, narrative outline+sections, classification, overrides).

v0.4.15 closed the remaining item from that follow-on: an audit of every
`_normalize_*`/legacy-shape function found none actually missing a
migration — see
[`docs/design/normalize-audit.md`](docs/design/normalize-audit.md) for
the full determination.

v0.4.16 was Phase 1 of the persisted dirty/revision manifest item:
rendering became a single explicit step (`wake rebuild`), not a
write-time side effect of `wake evidence`/`override`/`unverify`/`theme
create`/`confirm`/`narrative outline create`/`section create`/`confirm`
— a prerequisite for a manifest that reports what changed *between*
renders, per the user's framing (a diff/report, not an incremental-skip
optimization).

v0.4.17 closed Phase 2, the manifest itself: `wake rebuild` now persists
a sha256-per-JSON-source `rebuild-manifest.json` and reports a
`changes` block (added/changed/removed sources since the previous
rebuild) in its return value and human/`--json` output.
`rebuild_seed()` remains fully unconditional — the manifest is
report-only, never a gate. This closes the second of the two remaining
Structural Hardening follow-ons.

v0.4.18 built Theme K Pass 2 (wire seed-PDF consumers): `wake describe`
and `wake evidence` both now include an excerpt of the seed paper's own
extracted PDF text (via new shared `seed_pdf.load_seed_excerpt()`) as
context, falling back cleanly to abstract-only when no seed PDF text
exists. `describe-2`/`evidence-3` prompt versions. `wake narrative
section create` got a documentation-only note (open `seed.pdf` directly
for `[ref:SEED]` sentences); `wake narrative section audit` remains
separately deferred.

Full `WakeContext` threading through the ~137 existing `base:`-taking
domain functions remains the one open Structural Hardening follow-on,
deliberately not prioritized: `WakeContext.settings`/`.llm_client_factory`
have zero real consumers today, so threading it now would be pure
mechanical churn with no realized payoff — see `BACKLOG.md`'s "Theme L
follow-on" section. Revisit only if a concrete driver appears (hermetic
LLM-client injection for tests, or multi-config embedding).

v0.4.19 built `wake assess`: a read-only evidence-gap triage report
(`report.build_assessment()`) joining classified.json, override/dossier
status (via `themes._resolve_work_status()`), theme membership, and PDF
fetch state into one per-work document, plus a `triage` worklist ranked
by the same `report._score()` formula `impact.md` already uses. Closes
the highest-leverage remaining carried-forward item — previously an
agent had to read `classified.json` directly, stat `evidence/`, and
re-derive the ranking formula from config by hand.

v0.4.20 built Theme G (`wake timeline`): re-scoped mid-design from a
one-shot `report.py`-style metrics renderer to the same "candidate
material -> curated units -> stitch" pattern as `wake theme`/`wake
narrative`, once framed around who actually uses it -- an agent and
human choosing together what belongs on the timeline and how to
periodize it, not wake computing a timeline on its own. `wake timeline
candidates` is a read-only, complete, scored/dated/bucketed feed (never
pre-selecting a "top N"); `period create`/`confirm` curate one period
(bare-year or named span) at a time, confirming only once every
highlighted work is human-verified; `stitch` produces `timeline.md` (the
working artifact, all periods) and `timeline.json` (confirmed periods
only -- the handoff to a separate graphic-rendering tool). Wired into
`wake rebuild` and the rebuild manifest.

**Next phase:** product features — Theme B (DOE-relevance signals), Theme
H (non-publication evidence search). See `BACKLOG.md`'s "Open / Not Yet
Built" section for current sequencing.

**Deferred, real, not forgotten:**
- Product features: Theme B (DOE-relevance signals), Theme H
  (non-publication evidence search).

Explicitly **not** planned: replacing the filesystem-artifact model with
a database. Both the original external assessment and independent
review agree file-first is a real strength of wake's design, not a
symptom needing a fix.
