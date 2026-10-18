---
name: label-incident
description: Write the text of a label incident for a retail safety coordinator to approve, from label-check findings where the pack, the online listing and the supplier spec disagree.
---

# Writing a label incident

You write words only. The actions (holds on a lot, listing fixes, the supplier notice) are already decided by policy
and passed to you as the proposed actions. Describe them; never add, drop or change one. If something looks wrong,
say so in `considerations`.

## title
One line: brand and product, the lot when known, what the label gets wrong, and the scale ("hold at 11 stores" or
"listing fix only").

## narrative
Three to five sentences: which store checked the label and when, what the pack shows against the listing and the
spec, why it matters to a customer (an undeclared allergen, a missing safety warning), what happens on approval.

## evidence
One line per finding: the rule, the field, the value, and the store that found it. Cite the lineage receipt id when
holds are proposed.

## considerations
Only real doubts: an unreadable lot, a finding seen at only one store, a listing fix that removes something.

## customer_message
Leave it empty: label incidents do not message customers in phase 1.

## supplier_notice
Follow `assets/supplier-notice.md` below.

## vendor_case_body
Follow the sections of `assets/vendor-case.md` below, in order.

## qa_alert
Facts only: product id, lot, the finding, the stores and units held. No speculation about cause.

## Policy and knowledge
`references/label-rules.md` below is the label policy behind the proposed actions; it explains them and never changes
them. Verified knowledge, such as the hazard's playbook, guides the wording only.
