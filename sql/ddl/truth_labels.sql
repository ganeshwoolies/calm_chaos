CREATE TABLE IF NOT EXISTS truth_labels (
  fixture STRING NOT NULL,
  product_id STRING,
  lot STRING,
  reporting_store STRING,
  expected_rules ARRAY<STRING>,
  expected_severity STRING,
  hold_stores ARRAY<STRING>,
  units_on_hand INT64
);
