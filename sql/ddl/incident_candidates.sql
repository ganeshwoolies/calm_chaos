CREATE TABLE IF NOT EXISTS incident_candidates (
  candidate_id STRING NOT NULL,
  kind STRING,
  product_id STRING,
  guid STRING,
  batch_ids ARRAY<STRING>,
  event_ids ARRAY<STRING>,
  stores ARRAY<STRING>,
  online_orders INT64,
  receipt_ids ARRAY<STRING>,
  created_at TIMESTAMP,
  published BOOL,
  published_at TIMESTAMP
);
