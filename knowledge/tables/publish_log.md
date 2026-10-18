---
type: BigQuery Table
title: publish_log
description: "Every attempt psd-api made to publish a message, with its outcome: the published side of published versus landed."
tags: [table, pubsub, scoreboard]
status: draft
resource: psd.publish_log
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| event_id | STRING | Event the message carries |
| source | STRING | `recall` or `label` |
| topic | STRING | Topic published to |
| message_id | STRING | Pub/Sub message id; NULL when the attempt failed |
| published_at | TIMESTAMP | When the attempt was made |
| publisher | STRING | `psd-api` |
| attempt | INT64 | 1 or 2 |
| ok | BOOL | Whether the attempt succeeded |
| error | STRING | Why it failed |

# Joins

- `event_id` → [events](/tables/events.md), [publish_failures](/tables/publish_failures.md)
