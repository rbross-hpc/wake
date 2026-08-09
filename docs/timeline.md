# Timeline Curation (`wake timeline`)

A timeline shows how the seed paper's story unfolded over time: which
citing works mattered when, grouped into periods the agent and human
define together. Like `wake theme`, `wake` never decides what belongs —
it hands over the scored, dated material and persists the team's
selections, one period at a time.

Start by reading the candidate material, not a pre-picked "top N":

```bash
wake timeline candidates <seed> [--bucket-years N] [--min-strength S] [--since Y] [--until Y]
```

This returns **every** dated, classified citing work, bucketed by year
(or an N-year window), each scored the same way `impact.md`'s "Strongest
Evidence" table is. It deliberately never filters out weak relationships
or picks a shortlist — the threshold for what counts as a "key
development" is a conversation between the agent and the human, not a
config default. `--bucket-years`/`--min-strength`/`--since`/`--until` are
just different ways of looking at the same data; none of them are
persisted anywhere.

Then curate one period at a time:

```bash
wake timeline period create <seed> early-adoption \
  --label "Early adoption in Earth system modeling" --from 2003 --to 2007 \
  --highlights W111,W222 \
  --note "<why this span matters to the story>" \
  --highlight-note W111="<why this specific work matters here>"
```

A period's `<slug>` can be a bare year (e.g. `2012`, an emergent
single-year bucket with the range defaulted automatically) or a
kebab-case named span with an explicit `--from`/`--to` — the periodization
can be decided up front or emerge as highlights get chosen; both produce
the same kind of document. Every period starts `draft` — curating or
re-curating one is an agent/human judgment, not itself a sign-off.

A period carries the same trust model as a theme:

- **Highlighted works keep their own honest, existing status**
  (`[PROVISIONAL]` / `[PROPOSED]` / `[VERIFIED]`) — creating a period
  never upgrades a work's relationship status.
- **The period's own selection starts `draft`** and can only be promoted
  via a human-approved sign-off:
  ```bash
  wake timeline period confirm <seed> early-adoption
  ```
  Confirmation **refuses unless every highlighted work is already
  human-verified** (via `wake override`), re-checked fresh at confirm
  time — a confirmed period is a claim about what mattered at that point
  in the story, so it can never rest on an unverified guess.

Once satisfied with the periods drafted so far, assemble them:

```bash
wake timeline stitch <seed>
```

This writes two files with different audiences. `timeline.md` is the
working artifact — every period, confirmed or draft, clearly labeled,
same "works on partial data" philosophy as `narrative.md`
(see [`narrative.md`](narrative.md)). `timeline.json` carries the
**confirmed periods only** — the handoff to a separate Tufte-style
graphic-rendering tool, so nothing still being decided leaks into
whatever gets drawn from it. Periods with overlapping year ranges are
reported (a callout in `timeline.md`) but never blocked or
auto-corrected — periodization, like theme membership, is the team's
editorial call.

`wake timeline period create`/`confirm` write only the period's JSON
sidecar; the rendered `.md` files and the stitched `timeline.md`/
`timeline.json` are produced by `wake rebuild <seed>` or an explicit
`wake timeline stitch`, not as a write-time side effect — see
[`workflow.md`](workflow.md#rendering-the-wiki).

`wake timeline period show <seed> <slug>` and `wake timeline show <seed>`
re-print an already-written period or the stitched timeline as-is.
