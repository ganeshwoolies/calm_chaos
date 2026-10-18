---
type: Metric
title: Listing fix minutes
description: "How long a label defect stays in the online listing after a store finds it."
tags: [metric, scoreboard]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
order: 6
computation: /computations/listing-fix-minutes.md
unit: minutes
headline: median_minutes
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Definition

Per listing fix the executor applied, the minutes from the first label check that raised the incident's candidate
(`checked_at`) to the fix's `applied_at`. The tile shows the median and the maximum[^design-s16].

Its value comes only from [the attested computation](/computations/listing-fix-minutes.md); a tile whose computation does not
attest shows a dash, never a number.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
