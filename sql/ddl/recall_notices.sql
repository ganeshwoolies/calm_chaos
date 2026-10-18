CREATE TABLE IF NOT EXISTS recall_notices (
  guid STRING NOT NULL,
  feed STRING,
  title STRING,
  url STRING,
  attribution STRING,
  published_at TIMESTAMP,
  first_seen TIMESTAMP,
  event_id STRING,
  text STRING,
  screen_flagged BOOL,
  screen_reason STRING,
  recall_extract JSON,
  match_status STRING,
  matched_product_id STRING,
  match_method STRING,
  match_distance FLOAT64,
  match_options ARRAY<STRING>,
  matched_by STRING,
  receipt_id STRING,
  candidate_id STRING,
  updated_at TIMESTAMP
)
CLUSTER BY match_status;
