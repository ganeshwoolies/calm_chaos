---
type: Metric
title: Customers messaged
description: "Whether every exposed online order was messaged, and how soon after approval."
tags: [metric, scoreboard]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
order: 3
computation: /computations/customers-messaged.md
unit: ratio
headline: sent_ratio
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Definition

Per approved incident that messages online orders, the customer messages sent over the orders the approved
actions message, which must be 1, and the minutes from `approved_at` to the last customer message's `sent_at`, against
the incident's `message_minutes` target[^design-s16].

Its value comes only from [the attested computation](/computations/customers-messaged.md); a tile whose computation does not
attest shows a dash, never a number.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
