---
type: Playbook
title: Microbial contamination
description: How the desk handles food that may carry harmful bacteria, viruses or toxins, such as Listeria or Salmonella.
tags: [playbook, microbial, food, recall]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T12:19:08Z" }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s9
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on incident workflow, execution, summarised in the repository's agent spec
  - id: fsanz-about-recalls
    resource: https://www.foodstandards.gov.au/food-recalls/about-food-recalls
    title: Food Standards Australia New Zealand, About food recalls
  - id: fsanz-recall-templates
    resource: https://www.foodstandards.gov.au/food-recalls/recalltemplates
    title: Food Standards Australia New Zealand, Recall templates
---
# Trigger

A regulator or supplier recall of a product we range, whose hazard type is `microbial`[^fsanz-about-recalls]. The
notice usually names the organism (for example Listeria monocytogenes) and batch codes or a best-before range.

# Steps

1. **Severity, targets and checkout block** are set by [recall response](/policy/recall-response.md); this playbook
   never changes them.
2. **Pull** the named batches at every exposed store. Pulled units are kept apart from saleable stock until the supplier
   says how they are returned or destroyed.
3. **Message** every exposed online order, following the regulator's notice for what consumers should
   do[^fsanz-recall-templates]:
   - the product and how to recognise the batch or best-before date;
   - do not eat it;
   - the refund;
   - see a doctor if unwell.

   Name the people most at risk only when the notice does. Never add a health claim the notice does not make.
4. **Evidence** quotes the notice's hazard and consumer advice as written, and every figure with its receipt.
5. **Considerations** worth raising:
   - a notice that names a best-before range instead of batch codes;
   - states in the notice that differ from where we sold the product;
   - prior incidents for the same supplier or product.
6. **Supplier and QA** get the facts in the [vendor case format](/references/vendor-case-format.md), with no
   speculation about how the contamination happened[^design-s9].

[^design-s9]: Team design decision: the workflow drafts the words; code computes and executes the actions.
[^fsanz-about-recalls]: Microbial is one of the problem classes FSANZ lists for food recalls.
[^fsanz-recall-templates]: A food recall notice explains the issue, the food safety hazard and what consumers should
    do, and gives contact details for follow-up.
