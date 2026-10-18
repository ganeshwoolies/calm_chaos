---
type: Playbook
title: Chemical contamination
description: How the desk handles products that may contain a harmful chemical, from cleaning residue in food to a banned substance in a household product.
tags: [playbook, chemical, recall]
status: draft
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s9
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on incident workflow, summarised in the repository's agent spec
  - id: fsanz-about-recalls
    resource: https://www.foodstandards.gov.au/food-recalls/about-food-recalls
    title: Food Standards Australia New Zealand, About food recalls
  - id: accc-mandatory-reporting
    resource: https://www.productsafety.gov.au/business/make-a-mandatory-report/when-you-must-report-an-incident
    title: ACCC Product Safety, When you must report an incident (based on ACCC content)
---
# Trigger

A recall of a product we range whose hazard type is `chemical`[^fsanz-about-recalls].

# Steps

1. **Severity and targets** come from [recall response](/policy/recall-response.md).
2. **Pull** the named batches or lots at every exposed store.
3. **Message** every exposed online order:
   - do not eat or use it;
   - keep it away from children;
   - how to recognise the batch;
   - the refund;
   - see a doctor if unwell.

   Name the chemical only as the notice names it.
4. **Considerations** worth raising:
   - a notice that covers a whole product line rather than named batches;
   - products from the same supplier that share an ingredient or a factory[^design-s9];
   - any report of a death, serious injury or serious illness that reaches the desk, for food as for a household
     product. The retailer must make a mandatory report to the ACCC within 2 days of becoming aware of
     it[^accc-mandatory-reporting].
5. **Supplier and QA** get the facts in the [vendor case format](/references/vendor-case-format.md).

[^design-s9]: Team design decision: considerations raise only real doubts.
[^fsanz-about-recalls]: Chemical or other contaminants is one of the problem classes FSANZ lists for food recalls.
[^accc-mandatory-reporting]: A supplier must report within 2 days of becoming aware that a consumer good it supplied
    caused, or may have caused, a death, serious injury or serious illness.
