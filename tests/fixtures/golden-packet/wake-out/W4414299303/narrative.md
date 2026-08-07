---
type: narrative
title: "Narrative: Toward a persistent event-streaming system for high-performance computing applications"
seed_openalex_id: W4414299303
confirmed_sections: 1
draft_sections: 2
missing_sections: []
reference_count: 3
timestamp: 2026-08-07T12:43:51+00:00
---

# Narrative: Toward a persistent event-streaming system for high-performance computing applications

*Assembled by wake on 2026-08-07T12:43:51+00:00*

> **Partial narrative** — 2 section(s) still draft (not yet human-confirmed).

## Introduction

Mofka introduces a persistent event-streaming layer purpose-built for HPC environments, addressing the long-standing tension between the persistence of parallel file systems and the speed of direct inter-component communication [R1](#^r1). By providing Kafka-style topic-based publish/subscribe with RDMA-optimized transport, Mofka enables HPC workflows to adopt event-driven patterns previously impractical at supercomputer scale [R1](#^r1). This narrative surveys how Mofka has been adopted and cited in the literature, organized by two emergent themes: its role as infrastructure for workflow provenance systems, and its use as a building block for resilient streaming workflows.

## Mofka in Workflow Provenance

**⚠ DRAFT — not yet human-confirmed.**

HPC workflows increasingly require provenance tracking to enable reproducibility, debugging, and audit. Mofka's persistent event-streaming model provides a natural substrate: workflow events can be published to Mofka topics and consumed asynchronously by provenance collectors without blocking the primary computation [R1](#^r1). An LLM-based interactive provenance system cites Mofka as a candidate HPC-optimized broker for provenance message transport, noting its RDMA-optimized transport makes it well-suited to tightly coupled HPC networks [R2](#^r2).

## Resilient HPC Workflows

**⚠ DRAFT — not yet human-confirmed.**

The most direct evidence of Mofka's impact is the set of systems that build on it as a core architectural component. StreamGuard wraps Mofka as its resilience communication layer, using Mofka topics to implement reliable producer-consumer streaming with exactly-once delivery semantics and QoS guarantees for real-time HPC data streams [R3](#^r3). This tight coupling demonstrates that Mofka's API and persistence guarantees are sufficient to ground a production resilience system, not merely to inform one.

## References

1. Matthieu Dorier, Amal Gueroudji, Valérie Hayot-Sasson, Hai Duc Nguyen, Seth Ockerman, Renan Souza, Tekin Biçer, Haochen Pan, Philip Carns, Kyle Chard, Ryan Chard, Maxime Gonthier, E. A. Huerta, Ben Lenard, Bogdan Nicolae, Parth Patel, Justin M. Wozniak, Ian Foster, Nageswara S. V. Rao, and Robert Ross. 2025. "Toward a persistent event-streaming system for high-performance computing applications." Frontiers in High Performance Computing. DOI: [10.3389/fhpcp.2025.1638203](https://doi.org/10.3389/fhpcp.2025.1638203). ^r1

2. Renan Souza, Timothy Poteet, Brian D. Etz, Daniel Rosendo, Amal Gueroudji, Woong Shin, Prasanna Balaprakash, and Rafael Ferreira da Silva. 2025. "LLM Agents for Interactive Workflow Provenance: Reference Architecture and Evaluation Methodology." DOI: [10.1145/3731599.3767582](https://doi.org/10.1145/3731599.3767582). ^r2

3. Hai Thanh Nguyen, Bogdan Nicolae, Tekin Biçer, Amal Gueroudji, Matthieu Dorier, Kyle Chard, and Ian Foster. 2026. "StreamGuard: Low-Overhead Resilience for Real-time HPC Data Streams." DOI: [10.1145/3797905.3807872](https://doi.org/10.1145/3797905.3807872). ^r3
