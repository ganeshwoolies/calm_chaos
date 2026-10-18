-- Each store task's latest version. A task issued again after a shelf was not clear is its own row, with reissue_of.
CREATE OR REPLACE VIEW v_desk_tasks AS
SELECT
  record_id AS task_id,
  JSON_VALUE(record, '$.incident_id') AS incident_id,
  JSON_VALUE(record, '$.store_id') AS store_id,
  JSON_VALUE(record, '$.kind') AS kind,
  JSON_VALUE(record, '$.code') AS code,
  JSON_VALUE(record, '$.status') AS status,
  JSON_VALUE(record, '$.reissue_of') AS reissue_of,
  SAFE_CAST(JSON_VALUE(record, '$.issued_at') AS TIMESTAMP) AS issued_at,
  SAFE_CAST(JSON_VALUE(record, '$.due_at') AS TIMESTAMP) AS due_at,
  SAFE_CAST(JSON_VALUE(record, '$.verified_at') AS TIMESTAMP) AS verified_at,
  written_at
FROM `__DATASET__.desk_records`
WHERE collection = 'tasks'
QUALIFY ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY written_at DESC) = 1;
