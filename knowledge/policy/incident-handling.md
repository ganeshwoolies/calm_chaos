---
type: Policy
title: Incident handling
description: Rules that apply to every incident, recall or label, outside the actions it proposes.
tags: [policy, incident]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T12:19:08Z" }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s10
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on approval, resume and deterministic execution, summarised in the repository's agent spec
dismiss_suppress_hours: 24
---
# Rule

A coordinator who dismisses an incident records a reason. The same candidate is not raised again for
`dismiss_suppress_hours`: a redelivery inside that window is acknowledged without opening a new run[^design-s10]. The
window holds back only that candidate. A later notice about the same product is a new candidate.

[^design-s10]: Team design decision: "Dismissal records a reason; the same candidate is not re-raised" for the window set
    here.
