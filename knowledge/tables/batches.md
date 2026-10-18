---
type: BigQuery Table
title: batches
description: Production batches (food) and lots (other goods), with the code printed on the pack.
tags: [table, supply, lineage]
status: draft
resource: psd.batches
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| batch_id | STRING | Batch id, unique across products |
| product_id | STRING | Product the batch is of |
| kind | STRING | `batch` for food, `lot` for other goods |
| code | STRING | Code printed on the pack or rating plate, e.g. B2026-091 |
| produced_on | DATE | Production date |
| best_before | DATE | Best-before date, food only |
| supplier_id | STRING | Supplier that produced it |

# Joins

- `product_id` → [products](/tables/products.md)
- `batch_id` → [deliveries](/tables/deliveries.md), [order_lines](/tables/order_lines.md)
