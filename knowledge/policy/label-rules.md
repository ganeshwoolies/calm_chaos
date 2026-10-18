---
type: Policy
title: Label rules
description: How a label check's differences between the pack, the online listing and the supplier spec become findings, severities and actions.
tags: [policy, label]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T12:19:08Z" }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s8
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on diff rules, summarised in the repository's agent spec
  - id: fsanz-allergen-labelling
    resource: https://www.foodstandards.gov.au/business/labelling/allergen-labelling
    title: Food Standards Australia New Zealand, Allergen labelling for food businesses
  - id: erac-marking
    resource: https://www.erac.gov.au/equipment/equipment-marking/
    title: ERAC, Equipment marking
rules:
  - id: allergen_undeclared_on_pack
    condition: An allergen in the supplier spec is absent from the pack.
    severity: critical
    hazard_type: allergen
    actions: [hold, supplier_notice, qa_alert, listing_check]
  - id: allergen_missing_in_listing
    condition: An allergen on the pack is absent from the online listing.
    severity: high
    hazard_type: allergen
    actions: [listing_fix, qa_alert]
    listing: { field: allergens, op: add }
  - id: allergen_extra_in_listing
    condition: An allergen in the online listing is absent from both the pack and the spec.
    severity: low
    hazard_type: allergen
    actions: [listing_fix]
    listing: { field: allergens, op: remove }
  - id: warning_missing_on_pack
    condition: A warning in the supplier spec is absent from the pack.
    severity_from: /references/warning-hazards.md
    hazard_from: /references/warning-hazards.md
    actions: [hold, supplier_notice]
  - id: warning_missing_in_listing
    condition: A warning on the pack is absent from the online listing.
    severity: medium
    hazard_from: /references/warning-hazards.md
    actions: [listing_fix]
    listing: { field: warnings, op: add }
  - id: mark_missing_on_pack
    condition: A compliance mark in the supplier spec, such as the RCM, is absent from the pack.
    severity: high
    hazard_type: electrical_fire
    actions: [hold, supplier_notice]
  - id: ingredients_differ
    condition: The pack's ingredients differ from the spec, with a new ingredient or a similarity below ingredients_min_similarity.
    severity: medium
    hazard_type: quality_only
    actions: [supplier_notice]
  - id: origin_differs
    condition: The country of origin on the pack differs from the online listing.
    severity: low
    hazard_type: quality_only
    actions: [listing_fix, supplier_notice]
    listing: { field: origin, op: set_to }
min_legibility: 0.6
catalogue_match: { max_distance: 0.20, same_size_required: true }
ingredients_min_similarity: 0.85
candidate_severities: [high, critical]
targets_minutes:
  critical: { holds_verified: 60, listing_fixed: 120 }
  high: { holds_verified: 60, listing_fixed: 120 }
  medium: { holds_verified: null, listing_fixed: 1440 }
  low: { holds_verified: null, listing_fixed: 1440 }
---
# Rule

A label check compares three things: what the pack says, what the online listing says, and what the latest supplier
spec says. Each difference that matches a rule above is a finding with that rule's severity and actions[^design-s8]. The
values above are the rule; this text explains them.

- **Severity and hazard** come from the rule. `warning_missing_on_pack` takes both from
  [warning hazards](/references/warning-hazards.md), so a missing button battery warning weighs more than other missing
  warnings. `warning_missing_in_listing` takes only its hazard from there.
- **Actions:**
  - `hold`: hold the lot at every store holding it, by attested lineage.
  - `supplier_notice`: send the supplier a notice.
  - `qa_alert`: alert QA.
  - `listing_fix`: change the online listing with the rule's `listing` edit.
  - `listing_check`: ask the coordinator to check the listing against the spec.
- **Allergens** are compared by the names that must be declared[^fsanz-allergen-labelling], listed in
  [allergens](/references/allergens.md).
- **Compliance marks**: electrical equipment marking is moving to one mark, the Regulatory Compliance Mark
  (RCM)[^erac-marking]. A spec that names a mark and a pack that lacks it is a finding.
- **Reading and matching.** A read whose legibility is below `min_legibility` asks the store for a retake instead of
  producing findings. A label matches a catalogue product within `catalogue_match.max_distance`, and only with the same
  pack size when `same_size_required` is true.
- **Candidates.** A finding whose severity is in `candidate_severities` raises a label incident. Others appear as minor
  findings that a coordinator can raise by hand.
- **Time targets** (`targets_minutes`) run from approval: by when holds are verified by shelf photo, and by when the
  listing is fixed. A null target means none is set for that severity.

[^design-s8]: Team design decision: diff rules; policy values phase 1 starts with.
[^fsanz-allergen-labelling]: Since 25 February 2024 the Food Standards Code requires allergens to be declared by
    required names, in bold in the ingredient list and in a "Contains" summary statement.
[^erac-marking]: Marking is moving towards a single mark, the Regulatory Compliance Mark (RCM), as the Electrical
    Equipment Safety System (EESS) is brought in across participating jurisdictions; AS/NZS 4417.1 sets the conditions
    for using the mark.
