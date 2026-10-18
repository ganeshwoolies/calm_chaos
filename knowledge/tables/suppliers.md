---
type: BigQuery Table
title: suppliers
description: Suppliers of CalmChaosRetail products, one per brand.
tags: [table, supply]
status: draft
resource: psd.suppliers
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| supplier_id | STRING | Supplier id, `SUP-` and three digits |
| name | STRING | Supplier name |
| contact_ref | STRING | Opaque contact reference |
| category | STRING | Category the supplier's products belong to |

# Joins

- `supplier_id` → [products](/tables/products.md)
