---
type: Playbook
title: Electrical fire or shock
description: How the desk handles electrical products that may overheat, catch fire or shock, from a recall or a missing compliance mark.
tags: [playbook, electrical-fire, electrical, recall, label]
status: draft
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s8
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on label check, incident workflow, summarised in the repository's agent spec
  - id: erac-marking
    resource: https://www.erac.gov.au/equipment/equipment-marking/
    title: ERAC, Equipment marking
  - id: erac-certification
    resource: https://www.erac.gov.au/equipment/certification-of-equipment/
    title: ERAC, Certification of equipment
  - id: accc-mandatory-reporting
    resource: https://www.productsafety.gov.au/business/make-a-mandatory-report/when-you-must-report-an-incident
    title: ACCC Product Safety, When you must report an incident (based on ACCC content)
  - id: accc-tell-recall
    resource: https://www.productsafety.gov.au/business/recall-an-unsafe-product/tell-the-accc-of-the-recall
    title: ACCC Product Safety, Tell the ACCC of the recall (based on ACCC content)
---
# Trigger

Either:
- a recall whose hazard type is `electrical_fire`; or
- a label check finding that a compliance mark the spec names, such as the RCM, is missing from the pack (see
  [label rules](/policy/label-rules.md)).

# Steps

1. **Severity, targets and actions** come from [recall response](/policy/recall-response.md) or
   [label rules](/policy/label-rules.md).
2. **Recall.** Pull the named lots. The customer message covers:
   - stop using the product and unplug it;
   - do not try to repair it;
   - how to recognise the lot or model;
   - the refund.
3. **Missing mark.** Electrical equipment marking is moving to one mark, the Regulatory Compliance Mark
   (RCM)[^erac-marking]. A pack without the mark the spec requires is held. The supplier notice asks for the certificate
   and the corrected packaging. The certification of Level 3 equipment can be checked with ERAC's public
   search[^erac-certification].
4. **Considerations** worth raising:
   - whether the units on the shelf themselves carry the mark, since a packaging-only fault reads differently from an
     uncertified product;
   - prior incidents for the same supplier;
   - any report of a death, serious injury or serious illness that reaches the desk. The retailer must make a mandatory
     report to the ACCC within 2 days of becoming aware of it[^accc-mandatory-reporting];
   - a hold that becomes a recall the retailer runs itself. The ACCC must be told within 2 days of taking recall
     action[^accc-tell-recall].
5. **Supplier and QA** get the facts in the [vendor case format](/references/vendor-case-format.md)[^design-s8].

[^design-s8]: Team design decision: mark_missing_on_pack holds the lot and sends a supplier notice.
[^erac-marking]: Marking is moving towards a single mark, the RCM, as the Electrical Equipment Safety System is brought
    in across participating jurisdictions.
[^erac-certification]: Level 3 equipment (prescribed equipment, or declared articles in NSW) must be certified before it
    is sold, and ERAC offers a public search to check that a product's certification is recognised.
[^accc-mandatory-reporting]: A supplier must report within 2 days of becoming aware that a consumer good it supplied
    caused, or may have caused, a death, serious injury or serious illness.
[^accc-tell-recall]: A recall notification is due within 2 days of taking recall action with a consumer product.
