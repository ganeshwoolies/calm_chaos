---
type: BigQuery Table
title: store_stock
description: Units of each batch a store still holds, and the aisle it sits in.
tags: [table, supply, lineage, stores]
status: draft
resource: psd.store_stock
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| store_id | STRING | Store |
| product_id | STRING | Product |
| batch_id | STRING | Batch held |
| on_hand | INT64 | Units on hand |
| aisle | STRING | Aisle, shown on the store task |
| as_of | TIMESTAMP | When the count was taken |

# Joins

- `store_id`, `batch_id` → [deliveries](/tables/deliveries.md)
