---
type: BigQuery Table
title: deliveries
description: "One row per delivery of a batch from a distribution centre to a store: the edge recall lineage follows."
tags: [table, supply, lineage]
status: draft
resource: psd.deliveries
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| delivery_id | STRING | Delivery id |
| batch_id | STRING | Batch delivered |
| dc_id | STRING | Distribution centre it came from |
| store_id | STRING | Store it went to |
| delivered_at | TIMESTAMP | Delivery time |
| qty | INT64 | Units delivered |

# Joins

- `batch_id` → [batches](/tables/batches.md)
- `store_id` → [stores](/tables/stores.md)
