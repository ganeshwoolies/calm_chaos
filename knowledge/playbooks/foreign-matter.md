---
type: Playbook
title: Foreign matter
description: How the desk handles food that may contain pieces of glass, metal, plastic or other material that should not be there.
tags: [playbook, foreign-matter, food, recall]
status: draft
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s9
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on incident workflow, summarised in the repository's agent spec
  - id: fsanz-about-recalls
    resource: https://www.foodstandards.gov.au/food-recalls/about-food-recalls
    title: Food Standards Australia New Zealand, About food recalls
---
# Trigger

A recall of a product we range whose hazard type is `foreign_matter`[^fsanz-about-recalls]. The notice names the
material when it is known.

# Steps

1. **Severity, targets and checkout block** come from [recall response](/policy/recall-response.md).
2. **Pull** the named batches at every exposed store.
3. **Message** every exposed online order:
   - name the material the notice names;
   - do not eat it;
   - how to recognise the batch;
   - the refund;
   - see a doctor after an injury.

   Never describe how the material got in.
4. **Considerations** worth raising: a notice that names no material, and repeat foreign-matter incidents for the same
   supplier[^design-s9].
5. **Supplier and QA** get the facts in the [vendor case format](/references/vendor-case-format.md).

[^design-s9]: Team design decision: considerations raise only real doubts.
[^fsanz-about-recalls]: Foreign matter is one of the problem classes FSANZ lists for food recalls.
