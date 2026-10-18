---
type: Metric
title: Detection quality
description: "How well the desk finds the planted recalls and label defects."
tags: [metric, scoreboard]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
order: 10
computation: /computations/match-eval.md
unit: precision and recall
headline: precision
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Definition

Detection against the truth tables. Recall matching: each test-feed notice, joined to its truth_recalls scenario by
the third part of its guid, counts as predicted when it matched a product, expected when its scenario names one, and
correct when they agree; the share whose match status agrees is shown too. Label findings: each label check of a
truth_labels product and lot, rule by rule against the expected rules. Precision is correct over predicted, recall
correct over expected[^design-s16].

Its value comes only from [the attested computation](/computations/match-eval.md); a tile whose computation does not
attest shows a dash, never a number.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
