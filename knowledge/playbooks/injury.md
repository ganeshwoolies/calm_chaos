---
type: Playbook
title: Injury hazard
description: How the desk handles products that can cut, crush, burn or otherwise injure, including a missing button battery warning.
tags: [playbook, injury, recall, label]
status: draft
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s8
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on label rules, dinosaur battery scenario, summarised in the repository's agent spec
  - id: accc-button-guide
    resource: https://www.productsafety.gov.au/consumers/be-safe-around-the-home/safely-use-batteries-and-technology/button-batteries-guide
    title: ACCC Product Safety, Button batteries guide (based on ACCC content)
  - id: accc-button-standards
    resource: https://www.productsafety.gov.au/business/search-mandatory-standards/button-and-coin-batteries-mandatory-standards
    title: ACCC Product Safety, Button and coin batteries mandatory standards (based on ACCC content)
  - id: accc-mandatory-reporting
    resource: https://www.productsafety.gov.au/business/make-a-mandatory-report/when-you-must-report-an-incident
    title: ACCC Product Safety, When you must report an incident (based on ACCC content)
  - id: accc-tell-recall
    resource: https://www.productsafety.gov.au/business/recall-an-unsafe-product/tell-the-accc-of-the-recall
    title: ACCC Product Safety, Tell the ACCC of the recall (based on ACCC content)
---
# Trigger

Either:
- a recall whose hazard type is `injury`; or
- a label finding that a warning in the supplier spec is missing from the pack (see
  [warning hazards](/references/warning-hazards.md)).

A missing button battery warning is the case that matters most. A swallowed button battery can lodge in a child's
throat and burn it, and young children are at greatest risk[^accc-button-guide]. Products containing button or coin
batteries must carry the warnings set by mandatory standards, and a retailer is a supplier under them[^accc-button-standards].

# Steps

1. **Severity, targets and actions** come from [recall response](/policy/recall-response.md) or
   [label rules](/policy/label-rules.md). A missing button battery warning on the pack is critical; other missing
   warnings are not.
2. **Recall.** Pull the named lots. The customer message covers:
   - stop using the product;
   - keep it away from children when the notice says so;
   - how to recognise the lot;
   - the refund.

   For a button battery hazard, it also gives the regulator's urgent advice: call the Poisons Information Centre on
   13 11 26 at once if a child may have swallowed or inserted a battery, and Triple Zero (000) if the child is bleeding
   or having difficulty breathing[^accc-button-guide].
3. **Missing warning.** The lot is held at every store that holds it, by attested lineage. The supplier notice names the
   missing warning and the spec version that requires it. It asks for corrected packaging, every lot shipped without
   the warning, and a date[^design-s8].
4. **Considerations** worth raising:
   - an unreadable lot, when the hold covers the reporting store only;
   - a battery compartment that may not be secured, which is a product fault rather than a label fault and may need a
     recall;
   - prior incidents for the same supplier;
   - any report of a death, serious injury or serious illness that reaches the desk. The retailer must make a mandatory
     report to the ACCC within 2 days of becoming aware of it[^accc-mandatory-reporting];
   - a hold that becomes a recall the retailer runs itself. The ACCC must be told within 2 days of taking recall
     action[^accc-tell-recall].
5. **Supplier and QA** get the facts in the [vendor case format](/references/vendor-case-format.md).

[^design-s8]: Team design decision: warning_missing_on_pack holds the lot and sends a supplier notice; the dinosaur
    fixture lacks the button battery warning its spec requires.
[^accc-button-guide]: The ACCC's consumer guide: button batteries can lodge in the throat and cause severe burns;
    young children are at greatest risk; what to do if one is swallowed or inserted.
[^accc-button-standards]: Two safety and two information standards cover button and coin batteries and products
    containing them, including the warnings that must be provided. They bind every business that supplies the goods,
    retailers included.
[^accc-mandatory-reporting]: A supplier must report within 2 days of becoming aware that a consumer good it supplied
    caused, or may have caused, a death, serious injury or serious illness.
[^accc-tell-recall]: A recall notification is due within 2 days of taking recall action with a consumer product.
