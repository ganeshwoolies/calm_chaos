---
type: Attested Computation
title: Recall lineage
description: The stores and online orders that received the batches or lots a recall notice, or a label check, names.
tags: [recall, label, lineage, attested]
status: stable
verified:
  - { by: "human:Calm_Chaos_team", at: "2026-10-17T12:19:08Z" }
stale_after: 2027-04-30T00:00:00Z
runtime: bigquery
parameters:
  - { name: product_id, type: string, required: true }
  - { name: codes, type: array<string>, required: true }
  - { name: best_before_from, type: date, required: false }
  - { name: best_before_to, type: date, required: false }
  - { name: as_of, type: timestamp, required: true }
  - { name: order_lookback_days, type: integer, required: true }
computation: /computations/sql/recall_lineage.sql
executor: { resource: /references/run-on-bigquery.md, receipt: [job_id, executed_sql, result] }
attester: { resource: /attesters/sql_equality.py }
sources:
  - id: design-s7
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on lineage and attested computations, summarised in the repository's agent spec
---
# Computation

The SQL in [recall_lineage.sql](/computations/sql/recall_lineage.sql) picks the product's batches in three ways:
- batches whose code is in `codes`;
- when `codes` is empty, batches whose best-before falls between `best_before_from` and `best_before_to`;
- when `codes` is empty and `best_before_from` is not given, every batch of the product[^design-s7].

A recall passes the batch codes its notice names. When it names none, it passes one best-before range, from the
earliest to the latest date the notice names; a single date is a range of one day, and a date with no start leaves
`best_before_from` out, so every batch is traced. A label check passes the lots read from the packs.

It returns two kinds of row:
- **`store`.** Per batch and store delivered up to `as_of`: units delivered, last delivery time, units still on hand
  and aisle. The tables are [deliveries](/tables/deliveries.md) and [store_stock](/tables/store_stock.md).
- **`order`.** Every online order line carrying the batch, ordered within `order_lookback_days` before `as_of`. The
  tables are [order_lines](/tables/order_lines.md) and [online_orders](/tables/online_orders.md).

The figures on an incident card come from these rows and nothing else:
- **Stores:** the store rows that hold stock or are inside the exposure window of
  [recall response](/policy/recall-response.md).
- **Units:** the sum of units on hand.
- **Online orders:** the distinct order ids.

# Receipt

[Run on BigQuery](/references/run-on-bigquery.md) runs the file with the parameters bound by name and returns
`job_id`, `executed_sql` and `result`. The [SQL equality attester](/attesters/sql_equality.py) passes the receipt
only when the executed SQL equals this file. A failing receipt is recorded and its figures are never shown.

[^design-s7]: Team design decision: lineage (attested); attested computations: every number carries a
    receipt.
