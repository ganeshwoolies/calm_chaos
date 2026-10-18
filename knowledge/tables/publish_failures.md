---
type: BigQuery Table
title: publish_failures
description: "Every message psd-api gave up publishing after two attempts, with its body, so nothing is dropped silently."
tags: [table, pubsub, scoreboard]
status: draft
resource: psd.publish_failures
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| event_id | STRING | Event the message carries |
| source | STRING | `recall` or `label` |
| topic | STRING | Topic it was for |
| failed_at | TIMESTAMP | When the second attempt failed |
| error | STRING | The last error |
| body | STRING | The message body, to publish again |

# Joins

- `event_id` → [publish_log](/tables/publish_log.md)
