---
type: narrative-section
title: "Mofka in Workflow Provenance"
kind: theme
section_status: draft
timestamp: 2026-08-07T12:43:36+00:00
---

# Section: Mofka in Workflow Provenance

**⚠ DRAFT** — this section has not yet been human-confirmed. Present it to the human and run `wake narrative section confirm` on their behalf once they approve it (requires every referenced theme below to be currently confirmed).

**Grounded in themes:** [provenance-capture](../../evidence/themes/provenance-capture.md)

## Prose

HPC workflows increasingly require provenance tracking to enable reproducibility, debugging, and audit. Mofka's persistent event-streaming model provides a natural substrate: workflow events can be published to Mofka topics and consumed asynchronously by provenance collectors without blocking the primary computation [SEED](../../impact.md). An LLM-based interactive provenance system cites Mofka as a candidate HPC-optimized broker for provenance message transport, noting its RDMA-optimized transport makes it well-suited to tightly coupled HPC networks [W4416004498](../../evidence/W4416004498.md).
