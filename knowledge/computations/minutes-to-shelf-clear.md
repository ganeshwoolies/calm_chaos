---
type: Attested Computation
title: Minutes to shelf clear
description: "Per approved incident with store tasks: minutes from approval to the last shelf verified, once no task is open, against the policy target; incidents still verifying are counted apart."
tags: [metric, scoreboard, attested]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
stale_after: 2027-04-30T00:00:00Z
runtime: bigquery
parameters: []
computation: /computations/sql/minutes_to_shelf_clear.sql
executor: { resource: /references/run-on-bigquery.md, receipt: [job_id, executed_sql, result] }
attester: { resource: /attesters/sql_equality.py }
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Computation

[minutes_to_shelf_clear.sql](/computations/sql/minutes_to_shelf_clear.sql) takes no parameters and reads [desk_records](/tables/desk_records.md)[^design-s16]. It is
the computation behind the [Minutes to shelf clear](/metrics/minutes-to-shelf-clear.md) tile.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
