CREATE TABLE IF NOT EXISTS online_orders (
  order_id STRING NOT NULL,
  customer_ref STRING,
  store_id STRING,
  ordered_at TIMESTAMP,
  status STRING,
  channel_pref STRING
)
PARTITION BY DATE(ordered_at)
CLUSTER BY order_id;
