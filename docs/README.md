# wake docs

Topic pages that used to live inline in the top-level `README.md`,
split out once it grew past a comfortable single-screen overview.

| Page | Covers |
|---|---|
| [`workflow.md`](workflow.md) | Full command list, quick-start walkthrough, seed ID formats, relationship classes |
| [`abstract-recovery.md`](abstract-recovery.md) | How `wake` backfills missing OpenAlex abstracts (automatic + manual escalation) |
| [`pdf-sources.md`](pdf-sources.md) | The `wake fetch-pdf` source chain and fallback behavior |
| [`evidence.md`](evidence.md) | The provisional → proposed → verified lifecycle, the evidence wiki, diagnosing a surprising finding |
| [`themes.md`](themes.md) | Combined-evidence thematic synthesis (`wake theme`) |
| [`narrative.md`](narrative.md) | Narrative drafting from confirmed themes (`wake narrative`), inline source references |

For the agent-facing equivalent of this material (the same content,
organized for an LLM to load selectively during a session), see
[`wake/skills/impact-analysis/references/`](../wake/skills/impact-analysis/references/)
instead — that directory serves a different reader and is kept
independent of this one.

[`design/`](design/) holds design-discussion documents captured
mid-session for larger changes that need a live conversation before
being executed — see [`design/theme-workflow-reframe.md`](design/theme-workflow-reframe.md)
for the current one. These are deliberately not "how it works today"
documentation; check `BACKLOG.md` for whether a linked design has
actually been built yet.
