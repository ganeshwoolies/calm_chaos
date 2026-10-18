---
type: BigQuery Table
title: online_orders
description: Online orders, each fulfilled by one store. Customers appear as opaque references only.
tags: [table, orders, lineage]
status: draft
resource: psd.online_orders
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| order_id | STRING | Order id |
| customer_ref | STRING | Opaque customer reference; no names or contact details exist |
| store_id | STRING | Store that fulfilled the order |
| ordered_at | TIMESTAMP | Order time |
| status | STRING | `collected` or `delivered` |
| channel_pref | STRING | How the customer prefers to be messaged |

# Joins

- `order_id` → [order_lines](/tables/order_lines.md)
- `store_id` → [stores](/tables/stores.md)
