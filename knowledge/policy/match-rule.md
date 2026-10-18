---
type: Policy
title: Recall notice to catalogue match rule
description: How a recall notice is matched to a CalmChaosRetail product before lineage runs.
tags: [policy, recall, matching]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T12:19:08Z" }
  - { by: "human:Calm_Chaos_team", at: "2026-10-18T08:31:08Z" }
  - { by: "human:Calm_Chaos_team", at: "2026-10-18T10:27:58Z" }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s7
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on matching and match-rule, summarised in the repository's agent spec
barcode_first: true
top_k: 5
max_distance: 0.25
ambiguity_gap: 0.05
require_model_confirmation: true
---
# Rule

Only notices from a feed whose `match` is true in `config/feeds.yaml` are matched. A live feed's notices name real
brands and the catalogue is fictional, so they end as not in the catalogue without being matched.

A notice that lists a barcode the retailer sells matches on the barcode alone (`barcode_first`). Otherwise its brand,
product name and pack sizes are embedded and compared with the catalogue: the `top_k` nearest products within
`max_distance` (cosine) are candidates. When `require_model_confirmation` is true, Gemini confirms or rejects each
candidate as a product the notice recalls[^design-s7]:
- the same brand, where a business named after the brand counts as that brand;
- the same product and variant;
- one of the pack sizes the notice states, or any pack size when it states none.

The outcome:
- **Match:** one product found by barcode, or the nearest confirmed product when no other confirmed product is within
  `ambiguity_gap` of it.
- **Ambiguous:** two or more products found by barcode, or confirmed products within `ambiguity_gap` of the nearest.
  The coordinator picks.
- **None:** `not_in_range`, which the desk shows as "not in catalogue".

A match then runs lineage as the attested recall-lineage computation. A notice whose embedding fails stays pending and
is tried again on the next run.

[^design-s7]: Team design decision: matching; policy values phase 1 starts with.
