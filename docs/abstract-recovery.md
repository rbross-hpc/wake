# Abstract Recovery

~20% of citing works typically lack an OpenAlex abstract, forcing lower-
confidence title/venue-only classification. `wake` recovers most of these
automatically and lazily (only for works actually selected for
classification, never eagerly for the full citing set):

1. **Automatic backfill** (`classify` does this transparently): tries, in
   config order (`abstract_backfill.sources`, default
   `[primo, osti, semanticscholar]`):
   - **Primo** (opt-in, see below) — an institutional Ex Libris discovery-
     layer endpoint aggregating publisher metadata (Elsevier, Springer,
     IEEE, ACM, ...). Tried first when configured, since it tolerates a
     much higher request rate in practice than OSTI/Semantic Scholar and
     frequently covers publishers OpenAlex's own abstract reconstruction
     misses.
   - [OSTI](https://www.osti.gov) (DOE-funded work, via its `description`
     field).
   - [Semantic Scholar](https://www.semanticscholar.org) (broader
     coverage).

   All three are free, unauthenticated, and no-op quickly on a miss.
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
`primo`, `osti`, `semanticscholar`, `pdf-extract`, or `human-text`) and the
count is shown in the brief's Reach section.

## Primo (opt-in institutional discovery-layer backfill)

[`wake/sources/primo.py`](../wake/sources/primo.py) can query an Ex Libris
Primo instance — the discovery-layer catalog many university and lab
libraries run in front of their journal subscriptions — for a citing
work's abstract, and (for works with no DOI at all) attempt to recover
one via a title-similarity-guarded search.

**This is entirely opt-in and disabled by default.** A Primo endpoint is
specific to one institution's library subscription — there is no shared
default, and no wake install ever contacts a Primo instance unless you
explicitly configure one. Set these environment variables (in your own
`.env` or shell profile — never in a committed `wake.config.yaml`):

| Variable | Purpose |
|---|---|
| `WAKE_PRIMO_BASE_URL` | Your institution's Primo host, e.g. `https://your-institution.primo.exlibrisgroup.com` |
| `WAKE_PRIMO_VID` | Primo view ID, e.g. `01YOUR_INST:01YOUR_INST` |
| `WAKE_PRIMO_INST` | Primo institution code, e.g. `01YOUR_INST` |
| `WAKE_PRIMO_SCOPE` | Search scope (optional, default `MyInst_and_CI`) |

`wake config validate` surfaces `WAKE_PRIMO_BASE_URL` as an optional env
var once set. Alternatively (or in addition — env vars always win), set
the equivalent fields under `abstract_backfill.primo` in
`wake.config.yaml`; see that file's commented-out example block for the
exact shape. Two config knobs worth knowing:

- `title_similarity_threshold` (default `0.85`) — how closely a title-only
  search hit must match before its abstract/DOI is trusted, since a
  generic title can return many loosely-related results.
- `prefer_over_openalex` (default `false`) — when `true`, Primo's
  abstract is looked up for *every* citing work, not just ones OpenAlex
  left abstract-less, and preferred over OpenAlex's own (reconstructed-
  from-inverted-index) abstract when Primo has one. A Primo miss in this
  mode keeps whatever abstract OpenAlex already supplied rather than
  falling through to OSTI/Semantic Scholar — those remain gap-fillers,
  not a second-guessing cascade.

**Primo also contributes a PDF URL**, captured as a side effect of
whichever abstract/DOI call above already ran — never an extra Primo
request of its own. When Primo's record for a work is marked
`free_for_read`, its `linktopdf` link is saved as `primo_pdf_url` on the
work (see `wake/models.py`'s `Work.primo_pdf_url`). `wake fetch-pdf`
tries this (falling back to a live Primo lookup if it wasn't captured)
fairly late in its own source chain — see `docs/pdf-sources.md` — because
Primo's OA links only ever cover records already open access, which
OpenAlex's own `best_oa_location.pdf_url` (captured separately, at
`wake citing` time, as `oa_pdf_url` — see `docs/pdf-sources.md`'s first
entry) and OSTI/arXiv/Unpaywall typically reach first and for free. Both
URLs are kept as independent fields rather than one overwriting the
other, since they come from different sources at different times and
may disagree.
