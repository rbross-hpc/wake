---
type: narrative-section
title: "Resilient HPC Workflows"
kind: theme
section_status: draft
timestamp: 2026-08-07T12:43:43+00:00
---

# Section: Resilient HPC Workflows

**⚠ DRAFT** — this section has not yet been human-confirmed. Present it to the human and run `wake narrative section confirm` on their behalf once they approve it (requires every referenced theme below to be currently confirmed).

**Grounded in themes:** [resilient-workflows](../../evidence/themes/resilient-workflows.md)

## Prose

The most direct evidence of Mofka's impact is the set of systems that build on it as a core architectural component. StreamGuard wraps Mofka as its resilience communication layer, using Mofka topics to implement reliable producer-consumer streaming with exactly-once delivery semantics and QoS guarantees for real-time HPC data streams [W7167027240](../../evidence/W7167027240.md). This tight coupling demonstrates that Mofka's API and persistence guarantees are sufficient to ground a production resilience system, not merely to inform one.
