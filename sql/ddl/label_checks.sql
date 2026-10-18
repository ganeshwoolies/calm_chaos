CREATE TABLE IF NOT EXISTS label_checks (
  check_id STRING NOT NULL,
  store_id STRING,
  checked_at TIMESTAMP,
  photo_uri STRING,
  status STRING,
  product_id STRING,
  match_method STRING,
  match_distance FLOAT64,
  match_options ARRAY<STRING>,
  lot STRING,
  legibility FLOAT64,
  label_read JSON,
  findings JSON,
  max_severity STRING,
  candidate_id STRING,
  model STRING,
  updated_at TIMESTAMP
)
PARTITION BY DATE(checked_at)
CLUSTER BY candidate_id;
