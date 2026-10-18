---
type: Metric
title: Minutes to approve
description: "How long an incident waits for the coordinator's approval."
tags: [metric, scoreboard]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
order: 2
computation: /computations/minutes-to-approve.md
unit: minutes
headline: median_minutes
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Definition

Per approved incident, the minutes from its candidate's `created_at` to the incident's `approved_at`: the
drafting run and the coordinator's review together. The tile shows the median and the maximum[^design-s16].

Its value comes only from [the attested computation](/computations/minutes-to-approve.md); a tile whose computation does not
attest shows a dash, never a number.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
