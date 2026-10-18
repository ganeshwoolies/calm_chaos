---
name: recall-incident
description: Write the text of a recall incident for a retail safety coordinator to approve, from a regulator notice, the catalogue match and the attested lineage to stores and online orders.
---

# Writing a recall incident

You write words only. The actions (which stores pull which batch, the checkout block, which online orders are
messaged) are already decided by policy and passed to you as the proposed actions. Describe them; never add, drop or
change one. If something looks wrong, say so in `considerations`.

## title
One line: brand, product and pack size, the batch or best-before the notice names, the hazard in plain words, and the
scale ("14 stores, 37 online orders"). Use the figures from the proposed actions.

## narrative
Three to five sentences for a coordinator who has thirty seconds: who recalled what and why, how sure the catalogue
match is, where the stock is, what happens on approval.

## evidence
Short lines a coordinator can check: the notice title and date, the batch codes it names, the match method, and each
figure with its receipt id ("14 stores hold the batch (receipt rcpt-...)").

## considerations
Only real doubts: a notice that names no batch, states that do not match where we sold it, a stock count of zero at a
store that still gets a task, prior incidents for the same supplier.

## customer_message
Only when the proposed actions message online orders. Follow `assets/customer-message.md` below.

## vendor_case_body
Follow the sections of `assets/vendor-case.md` below, in order.

## supplier_notice, qa_alert
Facts only: product id, batch codes, hazard, the regulator notice, the stores and units affected. No speculation about
cause.

## Policy and knowledge
`references/severity.md` below is the recall policy behind the proposed actions; it explains them and never changes
them. Verified knowledge, such as the hazard's playbook, guides the wording only.
