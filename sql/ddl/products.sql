CREATE TABLE IF NOT EXISTS products (
  product_id STRING NOT NULL,
  name STRING,
  brand STRING,
  size STRING,
  category STRING,
  subcategory STRING,
  barcode STRING,
  supplier_id STRING,
  unit_price NUMERIC,
  listing_text STRING,
  listing_allergens ARRAY<STRING>,
  listing_warnings ARRAY<STRING>,
  listing_marks ARRAY<STRING>,
  listing_origin STRING
)
CLUSTER BY category;
