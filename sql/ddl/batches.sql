CREATE TABLE IF NOT EXISTS batches (
  batch_id STRING NOT NULL,
  product_id STRING,
  kind STRING,
  code STRING,
  produced_on DATE,
  best_before DATE,
  supplier_id STRING
)
CLUSTER BY product_id;
