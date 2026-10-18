---
type: BigQuery Table
title: incident_candidates
description: "Every candidate raised for the incident workflow, and whether it has been published."
tags: [table, recall, label, candidates]
status: draft
resource: psd.incident_candidates
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| candidate_id | STRING | `recall:`, 8 hex characters of the notice guid's SHA-1, `:` and the product id |
| kind | STRING | `recall` or `label` |
| product_id | STRING | Catalogue product |
| guid | STRING | Notice the candidate came from (recall only) |
| batch_ids | ARRAY<STRING> | Batches the lineage found |
| event_ids | ARRAY<STRING> | Events behind the candidate |
| stores | ARRAY<STRING> | Exposed stores |
| online_orders | INT64 | Online orders containing the batches |
| receipt_ids | ARRAY<STRING> | Receipts of the attested lineage behind the figures |
| created_at | TIMESTAMP | When the candidate was raised |
| published | BOOL | Whether it has been published to psd-incident-candidates |
| published_at | TIMESTAMP | When it was published |

# Notes

A candidate is written before it is published, and the scope job publishes every row not yet published, so none is lost
between the two. The workflow admits a candidate id once, so publishing one twice opens one incident.

# Joins

- `product_id` → [products](/tables/products.md)
- `guid` → [recall_notices](/tables/recall_notices.md)
- `receipt_ids` → [attestations](/tables/attestations.md)
