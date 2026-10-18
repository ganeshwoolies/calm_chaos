---
type: Attested Computation
title: Detection quality
description: "Test-feed notices against truth_recalls by scenario, and label checks against truth_labels by product and lot: predicted, expected and correct, precision and recall."
tags: [metric, scoreboard, attested]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
stale_after: 2027-04-30T00:00:00Z
runtime: bigquery
parameters: []
computation: /computations/sql/match_eval.sql
executor: { resource: /references/run-on-bigquery.md, receipt: [job_id, executed_sql, result] }
attester: { resource: /attesters/sql_equality.py }
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Computation

[match_eval.sql](/computations/sql/match_eval.sql) takes no parameters and reads [recall_notices](/tables/recall_notices.md), [truth_recalls](/tables/truth_recalls.md), [label_checks](/tables/label_checks.md), [truth_labels](/tables/truth_labels.md)[^design-s16]. It is
the computation behind the [Detection quality](/metrics/match-eval.md) tile.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
