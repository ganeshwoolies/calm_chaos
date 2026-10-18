---
type: BigQuery Table
title: attestations
description: "One row per attested computation run, passing or not: the receipt behind every figure the desk shows."
tags: [table, attested, audit]
status: draft
resource: psd.attestations
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| receipt_id | STRING | Receipt id, `rcpt-` and 12 hex characters |
| concept | STRING | Concept path of the computation |
| knowledge_version | STRING | Bundle version the run used |
| params | JSON | Parameter values as bound |
| job_id | STRING | BigQuery job |
| executed_sql | STRING | Text BigQuery ran |
| result | JSON | Rows returned |
| attested | BOOL | Attester verdict |
| reason | STRING | Why the verdict failed |
| used_by | STRING | Caller, e.g. an incident |
| created_at | TIMESTAMP | When the run finished |

# Joins

- `concept` → [recall lineage](/computations/recall-lineage.md)
