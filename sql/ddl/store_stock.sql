CREATE TABLE IF NOT EXISTS store_stock (
  store_id STRING NOT NULL,
  product_id STRING,
  batch_id STRING,
  on_hand INT64,
  aisle STRING,
  as_of TIMESTAMP
)
CLUSTER BY batch_id, store_id;
