---
type: BigQuery Table
title: order_lines
description: The products in an online order, and the batch each was picked from.
tags: [table, orders, lineage]
status: draft
resource: psd.order_lines
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| order_id | STRING | Order |
| product_id | STRING | Product |
| batch_id | STRING | Batch the line was picked from |
| qty | INT64 | Units |

# Joins

- `order_id` → [online_orders](/tables/online_orders.md)
- `batch_id` → [batches](/tables/batches.md)
