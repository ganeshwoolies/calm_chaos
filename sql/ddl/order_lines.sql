CREATE TABLE IF NOT EXISTS order_lines (
  order_id STRING NOT NULL,
  product_id STRING,
  batch_id STRING,
  qty INT64
)
CLUSTER BY batch_id;
