---
type: Playbook
title: Choking hazard
description: How the desk handles products, mostly toys, with small or detachable parts a young child could choke on.
tags: [playbook, choking, toys, recall, label]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T12:19:08Z" }
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s8
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on label rules, dinosaur scenarios, summarised in the repository's agent spec
  - id: toys-standard
    resource: https://www.legislation.gov.au/F2023L01185/latest/text
    title: Consumer Goods (Toys for Children up to and including 36 Months of Age) Safety Standard 2023, Federal Register of Legislation
  - id: accc-mandatory-reporting
    resource: https://www.productsafety.gov.au/business/make-a-mandatory-report/when-you-must-report-an-incident
    title: ACCC Product Safety, When you must report an incident (based on ACCC content)
  - id: accc-tell-recall
    resource: https://www.productsafety.gov.au/business/recall-an-unsafe-product/tell-the-accc-of-the-recall
    title: ACCC Product Safety, Tell the ACCC of the recall (based on ACCC content)
---
# Trigger

Either:
- a recall whose hazard type is `choking`, for example a toy with a part that detaches; or
- a label finding that a small-parts age warning is missing from the pack (see
  [warning hazards](/references/warning-hazards.md)).

Toys for children up to and including 36 months fall under a mandatory standard. Neither the toy nor any part that can
come off may be small enough to choke on, and a battery that small must not be removable without a
tool[^toys-standard].

# Steps

1. **Severity, targets and actions** come from [recall response](/policy/recall-response.md) or
   [label rules](/policy/label-rules.md).
2. **Recall.** Pull the named lots. The customer message opens with the action: take the product away from children
   now. It then covers how to recognise the lot, and the refund.
3. **Missing warning.** The lot is held at every store that holds it. The supplier notice asks for:
   - corrected packaging;
   - every lot shipped without the warning;
   - a date.
4. **Considerations** worth raising:
   - a recall and a label defect on consecutive lots of the same product[^design-s8];
   - a toy labelled for older children but designed or marketed as a plaything for children up to 36 months, which the
     standard still covers[^toys-standard];
   - any report of a death, serious injury or serious illness that reaches the desk. The retailer must make a mandatory
     report to the ACCC within 2 days of becoming aware of it[^accc-mandatory-reporting];
   - a hold that becomes a recall the retailer runs itself. The ACCC must be told within 2 days of taking recall
     action[^accc-tell-recall].
5. **Supplier and QA** get the facts in the [vendor case format](/references/vendor-case-format.md).

[^design-s8]: Team design decision: the small-parts warning rule, and the choking recall and missing-warning label
    scenarios on consecutive lots of one toy.
[^toys-standard]: The standard covers a toy manufactured, designed, labelled or marketed as a plaything for a child up
    to and including 36 months. Small parts are checked with the small parts cylinder of the toy standards it adopts,
    and a battery that fits wholly within the cylinder must not be removable without the aid of a tool.
[^accc-mandatory-reporting]: A supplier must report within 2 days of becoming aware that a consumer good it supplied
    caused, or may have caused, a death, serious injury or serious illness.
[^accc-tell-recall]: A recall notification is due within 2 days of taking recall action with a consumer product.
