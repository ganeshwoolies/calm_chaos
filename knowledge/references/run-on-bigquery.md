---
type: Reference
title: Run on BigQuery
description: How the desk's executor runs a BigQuery attested computation and what its receipt holds.
tags: [reference, attested, bigquery]
status: draft
sources:
  - id: design-s12
    resource: .agents-cli-spec.md
    title: Product Safety Desk team design decision on attested computations, summarised in the repository's agent spec
---
# Run

`app/attest.py`, `run_attested(concept, params, used_by)`[^design-s12]:
1. Loads the concept from the pinned bundle, and refuses one that is not a stable, human-verified, unexpired Attested
   Computation.
2. Reads the file its `computation` names. The caller never supplies SQL.
3. Binds each declared parameter by name and type. An optional parameter left out is a typed NULL; a required one left
   out, or an undeclared one, is refused.
4. Runs the file as one query job with the desk's dataset as default dataset, so the SQL names no project. It sets a
   per-query cap on bytes billed, and labels the job with the concept and the caller.
5. Builds the receipt from the job: `job_id`, `executed_sql` (the job's own query text) and `result` (the rows).
6. Asks the concept's attester for a verdict, and appends the receipt with its verdict to the `attestations` table.
7. Raises on a failing verdict, or when the receipt cannot be recorded, so the caller shows the figures as unavailable,
   never as numbers.

# Receipt fields

| Field | Meaning |
|---|---|
| `receipt_id` | `rcpt-` and 12 hex characters |
| `concept` | The concept path, e.g. `/computations/recall-lineage.md` |
| `knowledge_version` | The bundle version the run used |
| `params` | The parameter values as bound |
| `job_id` | The BigQuery job |
| `executed_sql` | The text BigQuery ran |
| `result` | The rows, as JSON |
| `attested`, `reason` | The attester's verdict |
| `used_by` | The caller, e.g. `incident:inc-6afd5316ff`, or `scope:` and the notice guid |
| `created_at` | When the run finished |

[^design-s12]: Team design decision: the executor binds only the declared parameters as query parameters, runs the SQL
    file the concept names and returns a receipt.
