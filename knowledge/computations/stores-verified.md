---
type: Attested Computation
title: Stores verified
description: "Per incident and over all incidents: stores tasked and stores verified clear, and tasks issued, counting a task issued again after a shelf was not clear."
tags: [metric, scoreboard, attested]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
stale_after: 2027-04-30T00:00:00Z
runtime: bigquery
parameters: []
computation: /computations/sql/stores_verified.sql
executor: { resource: /references/run-on-bigquery.md, receipt: [job_id, executed_sql, result] }
attester: { resource: /attesters/sql_equality.py }
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Computation

[stores_verified.sql](/computations/sql/stores_verified.sql) takes no parameters and reads [desk_records](/tables/desk_records.md)[^design-s16]. It is
the computation behind the [Stores verified](/metrics/stores-verified.md) tile.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
