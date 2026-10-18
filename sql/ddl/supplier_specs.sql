CREATE TABLE IF NOT EXISTS supplier_specs (
  product_id STRING NOT NULL,
  version STRING,
  allergens ARRAY<STRING>,
  warnings ARRAY<STRING>,
  marks ARRAY<STRING>,
  ingredients_text STRING,
  origin STRING,
  changed_at TIMESTAMP,
  supplier_id STRING
)
CLUSTER BY product_id;
