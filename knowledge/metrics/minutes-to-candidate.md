---
type: Metric
title: Minutes to candidate
description: "How long a recall notice takes to become an incident candidate."
tags: [metric, scoreboard]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
order: 1
computation: /computations/minutes-to-candidate.md
unit: minutes
headline: median_minutes
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Definition

Per recall notice that raised a candidate, the minutes from `first_seen` (the poller first saw the notice) to
the candidate's `created_at`, and from the regulator's `published_at`, which also counts the wait for the next poll.
The tile shows the median and the maximum of each[^design-s16].

Its value comes only from [the attested computation](/computations/minutes-to-candidate.md); a tile whose computation does not
attest shows a dash, never a number.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
