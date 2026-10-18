---
type: Metric
title: Minutes to shelf clear
description: "How long after approval every affected shelf is verified clear."
tags: [metric, scoreboard]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
order: 4
computation: /computations/minutes-to-shelf-clear.md
unit: minutes
headline: median_minutes
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Definition

Per approved incident with store tasks and no task still open, the minutes from `approved_at` to the last
task's `verified_at`, against the incident's `shelf_minutes` target. Incidents with an open task are counted as still
verifying and not timed[^design-s16].

Its value comes only from [the attested computation](/computations/minutes-to-shelf-clear.md); a tile whose computation does not
attest shows a dash, never a number.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
