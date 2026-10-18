---
type: Reference
title: Hazard taxonomy
description: The closed lists of product categories, hazard types and severities that every rule, prompt and query uses.
tags: [policy, taxonomy, recall, label]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T12:19:08Z" }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s4
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on tagged row schema, summarised in the repository's agent spec
  - id: fsanz-about-recalls
    resource: https://www.foodstandards.gov.au/food-recalls/about-food-recalls
    title: Food Standards Australia New Zealand, About food recalls
categories: [food, household, electrical, toys, cosmetics, other]
severity_order: [low, medium, high, critical]
hazard_types:
  - { id: microbial, playbook: /playbooks/microbial.md }
  - { id: allergen, playbook: /playbooks/allergen.md }
  - { id: foreign_matter, playbook: /playbooks/foreign-matter.md }
  - { id: spoilage, playbook: /playbooks/spoilage.md }
  - { id: electrical_fire, playbook: /playbooks/electrical-fire.md }
  - { id: choking, playbook: /playbooks/choking.md }
  - { id: chemical, playbook: /playbooks/chemical.md }
  - { id: injury, playbook: /playbooks/injury.md }
  - { id: quality_only }
---
# Lists

Every event, incident and rule names its category, hazard type and severity from the lists above, and nothing
else[^design-s4]. A value outside them is an error, never a new value.

- **`categories`**: what kind of product it is.
- **`hazard_types`**: what can hurt a customer, each with the playbook the drafter reads. They are the desk's own.
  Microbial, allergen, foreign matter and chemical correspond to problem classes FSANZ lists for food
  recalls[^fsanz-about-recalls]; spoilage, food that may spoil before its date, has no FSANZ class. A hazard type
  without a playbook covers defects with no safety risk.
- **`severity_order`**: least to most severe. A severity is always set by policy, never by a model:
  - by hazard type in [recall response](/policy/recall-response.md);
  - by rule in [label rules](/policy/label-rules.md).

[^design-s4]: Team design decision: the tagged row schema and its closed lists.
[^fsanz-about-recalls]: Food recalls are classified by the problem with the food: microbial, labelling, foreign matter,
    chemical or other contaminants, undeclared allergen, packaging fault, biotoxin and other.
