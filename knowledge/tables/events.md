---
type: BigQuery Table
title: events
description: "Every tagged event, as the BigQuery subscription on psd-events-tagged lands it. Read it through v_events_dedup."
tags: [table, events, pubsub]
status: draft
resource: psd.events
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| event_id | STRING | Event id, `evt_` and a time-ordered hex string; the same on every redelivery |
| source | STRING | `recall` or `label` |
| feed | STRING | Feed the notice came from: `fsanz` or `test` (recall only) |
| guid | STRING | The feed item's guid (recall only) |
| title | STRING | The feed item's title (recall only) |
| url | STRING | Link to the notice (recall only) |
| store_id | STRING | Store that ran the check (label only) |
| submitted_at | TIMESTAMP | When the notice was published, or the check was made |
| text | STRING | Notice text the extraction read, at most 12,000 characters (recall only) |
| product_name | STRING | Brand and product name from the extract, or the title when the extract has none |
| product_id | STRING | Catalogue product (label only; a recall is matched later by the scope job) |
| category | STRING | Category from the hazard taxonomy; `other` when the extract names none from the list |
| hazard_type | STRING | Hazard type from the hazard taxonomy; `quality_only` when the extract names none from the list |
| severity | STRING | Severity the recall response maps the hazard type to, never the model's |
| summary | STRING | One sentence from the extract |
| tag_confidence | FLOAT64 | The model's own confidence, 0 to 1 |
| model | STRING | Model that extracted the notice |
| tagged_at | TIMESTAMP | When the transform tagged the event |
| recall_extract | STRING | The extract as JSON text (recall only) |
| label_payload | STRING | The label check as JSON text (label only) |
| tag_error | STRING | Why the model output could not be read; the notice shows as extraction failed |
| screen_flagged | BOOL | Model Armor's verdict on the notice text; NULL when screening failed |
| subscription_name | STRING | Subscription that wrote the row |
| message_id | STRING | Pub/Sub message id on psd-events-tagged |
| publish_time | TIMESTAMP | When the message was published to psd-events-tagged |
| attributes | STRING | Message attributes as JSON text |

# Notes

Pub/Sub delivers at least once, so an event can land twice. The view `v_events_dedup` keeps the earliest row of each
`event_id`, and every reader uses it.

# Joins

- `event_id` → [recall_notices](/tables/recall_notices.md), [recall_matches](/tables/recall_matches.md),
  [publish_log](/tables/publish_log.md)
