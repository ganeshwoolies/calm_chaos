CREATE TABLE IF NOT EXISTS publish_failures (
  event_id STRING NOT NULL,
  source STRING,
  topic STRING,
  failed_at TIMESTAMP,
  error STRING,
  body STRING
);
