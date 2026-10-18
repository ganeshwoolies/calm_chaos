---
type: BigQuery Table
title: truth_labels
description: Ground truth for each label fixture, written by the generators and read only by evaluation.
tags: [table, truth, evaluation, label]
status: draft
resource: psd.truth_labels
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| fixture | STRING | Fixture id from data/truth.yaml |
| product_id | STRING | Product on the pack |
| lot | STRING | Lot or batch printed on the pack |
| reporting_store | STRING | Store that photographs the label |
| expected_rules | ARRAY<STRING> | Label rules the check should find |
| expected_severity | STRING | Severity of the worst finding |
| hold_stores | ARRAY<STRING> | Stores a hold should cover |
| units_on_hand | INT64 | Units those stores hold |

# Joins

- `product_id` → [products](/tables/products.md)
