CREATE TABLE IF NOT EXISTS deliveries (
  delivery_id STRING NOT NULL,
  batch_id STRING,
  dc_id STRING,
  store_id STRING,
  delivered_at TIMESTAMP,
  qty INT64
)
CLUSTER BY batch_id, store_id;
