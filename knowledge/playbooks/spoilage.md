---
type: Playbook
title: Spoilage
description: How the desk handles food recalled because it may spoil early, for example from a packaging or seal fault.
tags: [playbook, spoilage, food, recall]
status: draft
stale_after: 2027-04-30T00:00:00Z
sources:
  - id: design-s9
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on incident workflow, summarised in the repository's agent spec
---
# Trigger

A recall of a product we range whose hazard type is `spoilage`: food that may spoil before its date, for example
because a seal failed. Spoilage is the desk's own hazard type, not one of FSANZ's recall classes.

# Steps

1. **Severity and targets** come from [recall response](/policy/recall-response.md). They are less urgent than for
   contamination, but the shelves are still cleared and verified.
2. **Pull** the named batches at every exposed store.
3. **Message** every exposed online order: do not eat it even if it looks and smells normal, how to recognise the
   batch, and the refund.
4. **Considerations** worth raising: a notice that blames packaging, because other products from the same packing line
   may follow[^design-s9].
5. **Supplier and QA** get the facts in the [vendor case format](/references/vendor-case-format.md).

[^design-s9]: Team design decision: considerations raise only real doubts.
