---
type: BigQuery Table
title: supplier_specs
description: Every version of each supplier's product specification; a label is checked against the latest.
tags: [table, supply, label]
status: draft
resource: psd.supplier_specs
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| product_id | STRING | Product the spec describes |
| version | STRING | Spec version, `v1` upwards |
| allergens | ARRAY<STRING> | Allergens the spec declares |
| warnings | ARRAY<STRING> | Warnings the pack must carry |
| marks | ARRAY<STRING> | Compliance marks the pack must carry |
| ingredients_text | STRING | Ingredient list |
| origin | STRING | Country of origin statement |
| changed_at | TIMESTAMP | When this version took effect |
| supplier_id | STRING | Supplier that issued the spec |

# Joins

- `product_id` → [products](/tables/products.md)
