-- Each incident's latest version, with the times and approved figures the scoreboard reads.
CREATE OR REPLACE VIEW v_desk_incidents AS
SELECT
  record_id AS incident_id,
  JSON_VALUE(record, '$.candidate_id') AS candidate_id,
  JSON_VALUE(record, '$.kind') AS kind,
  JSON_VALUE(record, '$.status') AS status,
  JSON_VALUE(record, '$.product_id') AS product_id,
  JSON_VALUE(record, '$.proposed.severity') AS severity,
  SAFE_CAST(JSON_VALUE(record, '$.created_at') AS TIMESTAMP) AS created_at,
  SAFE_CAST(JSON_VALUE(record, '$.awaiting_approval_at') AS TIMESTAMP) AS awaiting_approval_at,
  SAFE_CAST(JSON_VALUE(record, '$.approved_at') AS TIMESTAMP) AS approved_at,
  SAFE_CAST(JSON_VALUE(record, '$.executed_at') AS TIMESTAMP) AS executed_at,
  SAFE_CAST(JSON_VALUE(record, '$.closed_at') AS TIMESTAMP) AS closed_at,
  SAFE_CAST(JSON_VALUE(record, '$.dismissed_at') AS TIMESTAMP) AS dismissed_at,
  ARRAY_LENGTH(JSON_QUERY_ARRAY(record, '$.approved.actions.message_orders')) AS orders_to_message,
  SAFE_CAST(JSON_VALUE(record, '$.approved.actions.targets.message_minutes') AS INT64) AS message_target_minutes,
  SAFE_CAST(JSON_VALUE(record, '$.approved.actions.targets.shelf_minutes') AS INT64) AS shelf_target_minutes,
  written_at
FROM `__DATASET__.desk_records`
WHERE collection = 'incidents'
QUALIFY ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY written_at DESC) = 1;
