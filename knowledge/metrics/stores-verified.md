---
type: Metric
title: Stores verified
description: "How many tasked stores have verified their shelf clear, per incident and overall."
tags: [metric, scoreboard]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
order: 5
computation: /computations/stores-verified.md
unit: stores
headline: stores_verified
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Definition

Per incident, and over all incidents, the stores given a hold or pull task and the stores whose shelf was verified
clear, with the tasks issued, open and verified clear. A task issued again after a shelf was not clear counts as one
more task issued, not as one more store[^design-s16].

Its value comes only from [the attested computation](/computations/stores-verified.md); a tile whose computation does not
attest shows a dash, never a number.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
