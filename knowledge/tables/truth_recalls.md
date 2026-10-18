---
type: BigQuery Table
title: truth_recalls
description: Ground truth for each recall scenario, written by the generators and read only by evaluation.
tags: [table, truth, evaluation]
status: draft
resource: psd.truth_recalls
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| scenario | STRING | Scenario id from data/truth.yaml |
| feed | STRING | Feed the notice is published on |
| notice_format | STRING | `fsanz` or `accc` |
| product_id | STRING | Product the notice should match; empty when none should |
| options | ARRAY<STRING> | Products an ambiguous notice should offer |
| codes | ARRAY<STRING> | Batch or lot codes the notice names |
| expected_match_status | STRING | Match status the scoping job should reach |
| stores_on_hand | ARRAY<STRING> | Stores holding the batch |
| units_on_hand | INT64 | Units those stores hold |
| online_orders | ARRAY<STRING> | Orders that contain the batch |

# Joins

- `product_id` → [products](/tables/products.md)
