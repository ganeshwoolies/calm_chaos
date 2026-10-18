CREATE TABLE IF NOT EXISTS publish_log (
  event_id STRING NOT NULL,
  source STRING,
  topic STRING,
  message_id STRING,
  published_at TIMESTAMP,
  publisher STRING,
  attempt INT64,
  ok BOOL,
  error STRING
)
PARTITION BY DATE(published_at);
