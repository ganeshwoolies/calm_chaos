-- Pub/Sub delivers at least once, so the same event can land twice: every reader uses this view, never the table.
CREATE OR REPLACE VIEW v_events_dedup AS
SELECT *
FROM `__DATASET__.events`
QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY publish_time) = 1;
