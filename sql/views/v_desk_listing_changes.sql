-- Each listing fix the executor applied after an approval.
CREATE OR REPLACE VIEW v_desk_listing_changes AS
SELECT
  record_id AS change_id,
  JSON_VALUE(record, '$.incident_id') AS incident_id,
  JSON_VALUE(record, '$.product_id') AS product_id,
  JSON_VALUE(record, '$.change.field') AS field,
  SAFE_CAST(JSON_VALUE(record, '$.applied_at') AS TIMESTAMP) AS applied_at,
  JSON_VALUE(record, '$.applied_by') AS applied_by,
  written_at
FROM `__DATASET__.desk_records`
WHERE collection = 'listing_changes'
QUALIFY ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY written_at DESC) = 1;
