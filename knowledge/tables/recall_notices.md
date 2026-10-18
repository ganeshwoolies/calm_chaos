---
type: BigQuery Table
title: recall_notices
description: "One row per regulator notice the desk has seen: what the poller read, and the match status the scope job reached."
tags: [table, recall, matching]
status: draft
resource: psd.recall_notices
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| guid | STRING | The feed item's guid: the key that stops a notice being read twice |
| feed | STRING | `fsanz` or `test` |
| title | STRING | The feed item's title |
| url | STRING | Link to the notice |
| attribution | STRING | Source to credit wherever the notice is shown, from config/feeds.yaml |
| published_at | TIMESTAMP | When the regulator published it |
| first_seen | TIMESTAMP | When the poller first read it |
| event_id | STRING | The event it was published as |
| text | STRING | Notice text the extraction read, at most 12,000 characters |
| screen_flagged | BOOL | Model Armor's verdict; NULL when screening failed |
| screen_reason | STRING | Filters that matched, or why screening failed |
| recall_extract | JSON | The notice's extract, once it has landed |
| match_status | STRING | `pending`, `matched`, `matched_no_exposure`, `not_in_range`, `ambiguous` or `extraction_failed` |
| matched_product_id | STRING | Catalogue product the notice matched |
| match_method | STRING | `barcode` or `embedding` |
| match_distance | FLOAT64 | Cosine distance of an embedding match |
| match_options | ARRAY<STRING> | Products an ambiguous notice could be |
| matched_by | STRING | `scope` for the scope job |
| receipt_id | STRING | Receipt of the attested lineage the match ran |
| candidate_id | STRING | Candidate raised for an exposed match |
| updated_at | TIMESTAMP | When the row last changed |

# Statuses

- **pending:** read and published; the extract has not landed, the scope job has not reached it, or its embedding or
  lineage failed and it is tried again.
- **matched:** one product confirmed, exposure found, and a candidate raised.
- **matched_no_exposure:** we range the product, but the named batches reached no store or online order.
- **not_in_range:** no catalogue product confirmed. Every live notice ends here without being matched: it names a
  real brand, and the catalogue is fictional.
- **ambiguous:** two or more products found by barcode, or confirmed products within the
  [match rule](/policy/match-rule.md)'s ambiguity gap of the nearest.
- **extraction_failed:** the model output could not be read, or names a date the lineage cannot read.

# Joins

- `event_id` → [events](/tables/events.md)
- `matched_product_id` → [products](/tables/products.md)
- `receipt_id` → [attestations](/tables/attestations.md)
- `candidate_id` → [incident_candidates](/tables/incident_candidates.md)
