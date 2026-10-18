-- Each outbound message's latest version: queued, then sent by the simulated sender.
CREATE OR REPLACE VIEW v_desk_outbox AS
SELECT
  record_id AS message_id,
  JSON_VALUE(record, '$.incident_id') AS incident_id,
  JSON_VALUE(record, '$.audience') AS audience,
  JSON_VALUE(record, '$.recipient_ref') AS recipient_ref,
  JSON_VALUE(record, '$.status') AS status,
  SAFE_CAST(JSON_VALUE(record, '$.created_at') AS TIMESTAMP) AS created_at,
  SAFE_CAST(JSON_VALUE(record, '$.sent_at') AS TIMESTAMP) AS sent_at,
  written_at
FROM `__DATASET__.desk_records`
WHERE collection = 'outbox'
QUALIFY ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY written_at DESC) = 1;
