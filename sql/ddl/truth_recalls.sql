CREATE TABLE IF NOT EXISTS truth_recalls (
  scenario STRING NOT NULL,
  feed STRING,
  notice_format STRING,
  product_id STRING,
  options ARRAY<STRING>,
  codes ARRAY<STRING>,
  expected_match_status STRING,
  stores_on_hand ARRAY<STRING>,
  units_on_hand INT64,
  online_orders ARRAY<STRING>
);
