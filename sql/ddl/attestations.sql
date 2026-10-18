CREATE TABLE IF NOT EXISTS attestations (
  receipt_id STRING NOT NULL,
  concept STRING,
  knowledge_version STRING,
  params JSON,
  job_id STRING,
  executed_sql STRING,
  result JSON,
  attested BOOL,
  reason STRING,
  used_by STRING,
  created_at TIMESTAMP
)
PARTITION BY DATE(created_at);
