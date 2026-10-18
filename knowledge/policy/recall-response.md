---
type: Policy
title: Recall response
description: How severe a recall is, how fast the desk acts after approval, and which stores and online orders are exposed.
tags: [policy, recall]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T12:19:08Z" }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s12
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on policy values phase 1 starts with, summarised in the repository's agent spec
  - id: fsanz-about-recalls
    resource: https://www.foodstandards.gov.au/food-recalls/about-food-recalls
    title: Food Standards Australia New Zealand, About food recalls
  - id: fsanz-firp
    resource: https://www.foodstandards.gov.au/food-recalls/firp
    title: Food Standards Australia New Zealand, Food Industry Recall Protocol
  - id: fsanz-how-to-recall
    resource: https://www.foodstandards.gov.au/food-recalls/how-to-recall-food
    title: Food Standards Australia New Zealand, How to recall food
severity_by_hazard:
  microbial: critical
  allergen: critical
  electrical_fire: critical
  choking: critical
  injury: high
  chemical: high
  foreign_matter: high
  spoilage: medium
  quality_only: low
targets_minutes:
  critical: { customers_messaged: 30, shelves_clear: 60 }
  high: { customers_messaged: 120, shelves_clear: 240 }
  medium: { customers_messaged: 1440, shelves_clear: 1440 }
  low: { customers_messaged: null, shelves_clear: null }
store_action_severities: [critical, high, medium]
checkout_block_severities: [critical]
checkout_block_drop_needs_reason: true
exposure_days: 30
order_lookback_days: 30
---
# Rule

The values above are the rule; this text explains them and repeats none of them, so a change is made in one
place[^design-s12].

- **Severity** follows the hazard type (`severity_by_hazard`), never the wording of the notice. The hazard types are the
  closed list in [hazard taxonomy](/policy/hazard-taxonomy.md).
- **Time targets** (`targets_minutes`) run from the coordinator's approval: by when every exposed online customer has
  been messaged, and by when every exposed shelf is verified clear. A null target means none is set for that severity.
- **Store actions.** A recall whose severity is in `store_action_severities` proposes a pull at every exposed store.
  Any other recall proposes none: the exposed stores are listed as optional, and the coordinator adds the ones to pull.
- **Checkout block.** A recall whose severity is in `checkout_block_severities` requests a checkout block for the
  affected batches. When `checkout_block_drop_needs_reason` is true, a coordinator may drop it only with a recorded
  reason.
- **Exposure.** A store is exposed when it still holds the batch, or received it within `exposure_days`. An online order
  is messaged when it contains the batch and was placed within `order_lookback_days`. When the notice names no batch
  code, every batch with a best-before date from the earliest to the latest it names counts; when it names neither,
  every batch of the product counts.
  These figures come only from the attested recall lineage.

The desk acts for the retailer inside a recall that the supplier runs and FSANZ coordinates[^fsanz-about-recalls], under
the Food Industry Recall Protocol[^fsanz-firp]. It takes stock off sale and tells its own customers. The supplier stays
responsible for notifying the regulators and reporting on the recall[^fsanz-how-to-recall].

[^design-s12]: Team design decision: policy values phase 1 starts with.
[^fsanz-about-recalls]: FSANZ coordinates food recalls in Australia. A consumer recall recovers the food from every
    point in the supply chain, consumers included; a trade recall recovers it from distribution centres and wholesalers.
[^fsanz-firp]: The Food Industry Recall Protocol sets out the roles and responsibilities of food businesses and
    government in a recall, its key steps, the legal requirements for food businesses and what a recall plan contains.
[^fsanz-how-to-recall]: The recalling business contacts the food enforcement agency of the state or territory where its
    head office is, and FSANZ; tells the businesses it supplied as soon as possible; and sends FSANZ an interim
    post-recall report two weeks after the recall starts and a final one after four weeks.
