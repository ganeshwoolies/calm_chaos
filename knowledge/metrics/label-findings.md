---
type: Metric
title: Label findings
description: "What the stores' label checks found."
tags: [metric, scoreboard]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
order: 8
computation: /computations/label-findings.md
unit: checks
headline: n
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Definition

The label checks stores sent, the label candidates they raised, and their findings counted by label rule and
severity[^design-s16].

Its value comes only from [the attested computation](/computations/label-findings.md); a tile whose computation does not
attest shows a dash, never a number.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
