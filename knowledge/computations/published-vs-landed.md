---
type: Attested Computation
title: Published versus landed
description: "Each hour of the last two days: distinct events published to psd-events, how many landed in events, the gap, and the duplicate rows the dedup view leaves out."
tags: [metric, scoreboard, attested]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
  - { by: "human:Calm_Chaos_team", at: "2026-10-18T08:31:08Z" }
  - { by: "human:Calm_Chaos_team", at: "2026-10-18T10:27:58Z" }
stale_after: 2027-04-30T00:00:00Z
runtime: bigquery
parameters: []
computation: /computations/sql/published_vs_landed.sql
executor: { resource: /references/run-on-bigquery.md, receipt: [job_id, executed_sql, result] }
attester: { resource: /attesters/sql_equality.py }
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Computation

[published_vs_landed.sql](/computations/sql/published_vs_landed.sql) takes no parameters and reads [publish_log](/tables/publish_log.md), [events](/tables/events.md)[^design-s16]. It is
the computation behind the [Published versus landed](/metrics/published-vs-landed.md) tile.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
