---
type: Metric
title: Notice outcomes
description: "What became of the recall notices the desk read."
tags: [metric, scoreboard]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
  - { by: "human:Calm_Chaos_team", at: "2026-10-18T08:31:08Z" }
  - { by: "human:Calm_Chaos_team", at: "2026-10-18T10:27:58Z" }
order: 7
computation: /computations/notice-outcomes.md
unit: notices
headline: notices
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Definition

The recall notices seen, counted by feed and by match status: matched, matched with no exposure, not in the
catalogue, ambiguous, extraction failed or pending[^design-s16].

Its value comes only from [the attested computation](/computations/notice-outcomes.md); a tile whose computation does not
attest shows a dash, never a number.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
