---
type: Playbook
title: Undeclared or mislabelled allergen
description: How the desk handles a food whose pack or listing fails to declare an allergen it contains, from a recall or a label check.
tags: [playbook, allergen, food, recall, label]
status: draft
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s8
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on label check, incident workflow, summarised in the repository's agent spec
  - id: fsanz-allergen-labelling
    resource: https://www.foodstandards.gov.au/business/labelling/allergen-labelling
    title: Food Standards Australia New Zealand, Allergen labelling for food businesses
---
# Trigger

Either a recall whose hazard type is `allergen`, or a label check finding from [label rules](/policy/label-rules.md):
- an allergen in the spec but not on the pack;
- an allergen on the pack but not in the online listing;
- an allergen in the listing that neither the pack nor the spec has[^design-s8].

# Steps

1. **Severity, targets and actions** come from [recall response](/policy/recall-response.md) or
   [label rules](/policy/label-rules.md).
2. **Name the allergen** by its required name from [allergens](/references/allergens.md), exactly as it must be
   declared[^fsanz-allergen-labelling].
3. **Recall.** Pull the named batches. The customer message says plainly that people with an allergy or intolerance to
   that allergen must not eat the product. It also covers how to recognise the batch, the refund, and seeing a doctor
   after a reaction.
4. **Pack missing a declared allergen (label check).** The lot is held. The supplier notice asks for:
   - corrected artwork;
   - every lot printed with the faulty label;
   - a date for the fix.

   QA is alerted, because a pack that omits an allergen may need a recall.
5. **Listing only (label check).** The pack is right and the listing is wrong. The listing fix adds or removes the
   allergen, and the QA alert says which. No customer message is sent in phase 1.
6. **Considerations** worth raising:
   - a finding seen at only one store;
   - a listing fix that removes an allergen;
   - a "may contain" statement, which is never a finding.

[^design-s8]: Team design decision: allergen rules and their actions.
[^fsanz-allergen-labelling]: Allergens are declared by required names, in bold in the ingredient list and in a
    "Contains" summary statement.
