---
type: Attested Computation
title: Minutes to candidate
description: "Per notice that raised a candidate: minutes from the poller first seeing it, and from the regulator publishing it, to the candidate; median and maximum."
tags: [metric, scoreboard, attested]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
stale_after: 2027-04-30T00:00:00Z
runtime: bigquery
parameters: []
computation: /computations/sql/minutes_to_candidate.sql
executor: { resource: /references/run-on-bigquery.md, receipt: [job_id, executed_sql, result] }
attester: { resource: /attesters/sql_equality.py }
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Computation

[minutes_to_candidate.sql](/computations/sql/minutes_to_candidate.sql) takes no parameters and reads [recall_notices](/tables/recall_notices.md), [incident_candidates](/tables/incident_candidates.md)[^design-s16]. It is
the computation behind the [Minutes to candidate](/metrics/minutes-to-candidate.md) tile.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
