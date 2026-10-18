CREATE TABLE IF NOT EXISTS recall_matches (
  event_id STRING NOT NULL,
  product_id STRING,
  rank INT64,
  method STRING,
  distance FLOAT64,
  same_product BOOL,
  created_at TIMESTAMP
)
CLUSTER BY event_id;
