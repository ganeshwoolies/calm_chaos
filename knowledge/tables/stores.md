---
type: BigQuery Table
title: stores
description: CalmChaosRetail stores and the distribution centre that serves each.
tags: [table, supply, stores]
status: draft
resource: psd.stores
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| store_id | STRING | Store id, `S` and three digits |
| name | STRING | Store name |
| state | STRING | State or territory |
| dc_id | STRING | Distribution centre serving the store |
| lat | FLOAT64 | Latitude |
| lng | FLOAT64 | Longitude |

# Joins

- `store_id` → [deliveries](/tables/deliveries.md), [store_stock](/tables/store_stock.md), [online_orders](/tables/online_orders.md)
