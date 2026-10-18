---
type: Metric
title: Published versus landed
description: "Whether every event the desk published to psd-events reached BigQuery, and how many arrived twice."
tags: [metric, scoreboard]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T21:09:55Z" }
  - { by: "human:Calm_Chaos_team", at: "2026-10-18T08:31:08Z" }
  - { by: "human:Calm_Chaos_team", at: "2026-10-18T10:27:58Z" }
order: 9
computation: /computations/published-vs-landed.md
unit: events
headline: missing
sources:
  - id: design-s16
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on the scoreboard, summarised in the repository's agent spec
---
# Definition

Per hour of the last two days, the distinct event ids published to psd-events with `ok` in publish_log, how many of
them landed in events, the gap (dead-lettered or dropped) and the duplicate rows, which the table holds and
v_events_dedup leaves out[^design-s16]. Incident candidates are published to psd-incident-candidates for psd-agents and
never land in events, so they are not counted.

Its value comes only from [the attested computation](/computations/published-vs-landed.md); a tile whose computation does not
attest shows a dash, never a number.

[^design-s16]: Team design decision: "Every tile is an Attested Computation in the bundle. GET /metrics runs them through
    run_attested and returns each value with its receipt id; a tile whose attestation fails shows a dash, never a number."
