---
type: BigQuery Table
title: desk_records
description: "Every version of every desk record psd-agents writes: incidents, tasks, the outbox, cases, listing and checkout changes, suppression, memory links and the audit log."
tags: [table, desk, scoreboard]
status: draft
resource: psd.desk_records
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| collection | STRING | `incidents`, `tasks`, `outbox`, `vendor_cases`, `listing_changes`, `pos_block_requests`, `suppressed`, `memory_links` or `audit` |
| record_id | STRING | The record's id in its collection; a fresh id for each audit row |
| written_at | TIMESTAMP | When this version was written |
| record | JSON | The whole record as Firestore holds it |

Append-only: a record changed three times has three rows. Partitioned by the day of `written_at`, clustered by
collection and record id.

# Views

Each view gives every record's latest version, with typed columns.

| View | Columns |
|---|---|
| v_desk_incidents | incident_id, candidate_id, kind, status, product_id, severity, created_at, awaiting_approval_at, approved_at, executed_at, closed_at, dismissed_at, orders_to_message, message_target_minutes, shelf_target_minutes |
| v_desk_tasks | task_id, incident_id, store_id, kind, code, status, reissue_of, issued_at, due_at, verified_at |
| v_desk_outbox | message_id, incident_id, audience, recipient_ref, status, created_at, sent_at |
| v_desk_listing_changes | change_id, incident_id, product_id, field, applied_at, applied_by |

The figures in v_desk_incidents are the approved ones: the orders the approved actions message and their time targets.
