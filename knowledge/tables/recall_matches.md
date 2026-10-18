---
type: BigQuery Table
title: recall_matches
description: "Every catalogue product the scope job considered for a notice, with how it was found and Gemini's verdict."
tags: [table, recall, matching]
status: draft
resource: psd.recall_matches
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| event_id | STRING | The notice's event |
| product_id | STRING | Catalogue product considered |
| rank | INT64 | Order by distance, nearest first |
| method | STRING | `barcode` or `embedding` |
| distance | FLOAT64 | Cosine distance between the notice and the product; NULL for a barcode |
| same_product | BOOL | Gemini's verdict that the product is one the notice recalls; NULL when not asked or the call failed |
| created_at | TIMESTAMP | When the scope job wrote the row |

# Joins

- `event_id` → [events](/tables/events.md), [recall_notices](/tables/recall_notices.md)
- `product_id` → [products](/tables/products.md)
