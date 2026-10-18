---
type: Reference
title: Vendor case format
description: The sections every vendor case the desk opens with a supplier contains, in order.
tags: [reference, supplier, vendor-case]
status: draft
sources:
  - id: design-s10
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on vendor case, summarised in the repository's agent spec
---
# Sections

A vendor case is a factual record the supplier and the retailer's QA team work from[^design-s10]. It states facts and
asks for specific things. It never speculates about cause and never apportions blame.

1. **Summary.** One sentence: the product, the batch or lot, and what is wrong.
2. **Product.** Product id, brand, name and pack size; the supplier id.
3. **Affected stock.** The batch or lot codes, and the stores and units affected, quoting the attested figures with
   their receipt ids.
4. **What we found.** The regulator notice (title, date, link), or the label findings (rule, field, value, the store
   that found it).
5. **What we have done.** The actions approved by the coordinator: holds or pulls, checkout block, listing fixes,
   customer messages.
6. **What we need from you.**
   - the root cause once known;
   - the corrective action;
   - confirmation of every affected batch or lot and where it shipped;
   - for a label defect, corrected artwork;
   - a date by which you will reply.

[^design-s10]: Team design decision: the executor opens a vendor case with the drafted case text after approval.
