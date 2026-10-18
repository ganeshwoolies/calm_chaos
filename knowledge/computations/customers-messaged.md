---
type: Attested Computation
title: Customers messaged
description: "Per approved incident that messages online orders: customer messages sent over orders to message, which must be 1, and minutes from approval to the last message, against the policy target."
tags: [metric, scoreboard, attested]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
stale_after: 2027-04-30T00:00:00Z
runtime: bigquery
parameters: []
computation: /computations/sql/customers_messaged.sql
executor: { resource: /references/run-on-bigquery.md, receipt: [job_id, executed_sql, result] }
attester: { resource: /attesters/sql_equality.py }
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Computation

[customers_messaged.sql](/computations/sql/customers_messaged.sql) takes no parameters and reads [desk_records](/tables/desk_records.md)[^design-s16]. It is
the computation behind the [Customers messaged](/metrics/customers-messaged.md) tile.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
