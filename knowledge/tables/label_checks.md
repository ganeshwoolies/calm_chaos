---
type: BigQuery Table
title: label_checks
description: "One row per label photo a store sends: what Gemini read, the product it matched, and the findings the label rules gave."
tags: [table, label, store]
status: draft
resource: psd.label_checks
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| check_id | STRING | Check id, `lc-` and 12 hex characters |
| store_id | STRING | Store that sent the photo |
| checked_at | TIMESTAMP | When the photo arrived |
| photo_uri | STRING | The photo in the photos bucket, deleted after 7 days |
| status | STRING | `checked`, `findings`, `retake` or `needs_product` |
| product_id | STRING | Catalogue product the pack is |
| match_method | STRING | `barcode`, `embedding` or `associate` |
| match_distance | FLOAT64 | Cosine distance of an embedding match |
| match_options | ARRAY<STRING> | Products offered to the associate when none matched |
| lot | STRING | Lot or batch code read from the pack |
| legibility | FLOAT64 | Gemini's own estimate of how much of the label it could read, 0 to 1 |
| label_read | JSON | The read; NULL for a retake, which keeps only the photo |
| findings | JSON | Findings, each with the severity, hazard and actions its rule in [label rules](/policy/label-rules.md) gives |
| max_severity | STRING | Severity of the worst finding |
| candidate_id | STRING | Label candidate the findings raised: `label:`, the product id, `:` and 6 hex characters of the defect signature |
| model | STRING | Model that read the photo |
| updated_at | TIMESTAMP | When the row last changed |

# Statuses

- **checked:** the pack matches the listing and the latest spec.
- **findings:** at least one rule found a difference.
- **retake:** legibility below the label rules' `min_legibility`.
- **needs_product:** no product matched; the associate picks from `match_options`.

# Notes

The defect signature is the product, the lot and the rules and values found, so the same defect at another store raises
the same candidate and joins the open incident.

# Joins

- `product_id` → [products](/tables/products.md)
- `store_id` → [stores](/tables/stores.md)
- `candidate_id` → [incident_candidates](/tables/incident_candidates.md)
