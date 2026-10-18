-- The last two days in total, then hour by hour: distinct events published to psd-events, how many landed in events,
-- the gap (dead-lettered or dropped) and the duplicate rows the dedup view leaves out. Only psd-events leads to the
-- events table: a candidate published to psd-incident-candidates goes to psd-agents and never lands there.
WITH published AS (
  SELECT event_id, MIN(published_at) AS published_at
  FROM publish_log
  WHERE ok AND topic = 'psd-events' AND published_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
  GROUP BY event_id
),
landed AS (
  SELECT event_id, COUNT(*) AS rows_landed
  FROM events
  WHERE publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 49 HOUR)
  GROUP BY event_id
)
SELECT
  TIMESTAMP_TRUNC(p.published_at, HOUR) AS hour,
  COUNT(*) AS published,
  COUNTIF(l.event_id IS NOT NULL) AS landed,
  COUNTIF(l.event_id IS NULL) AS missing,
  SUM(IF(l.event_id IS NULL, 0, l.rows_landed - 1)) AS duplicates
FROM published AS p
LEFT JOIN landed AS l USING (event_id)
GROUP BY GROUPING SETS ((), (hour))
ORDER BY hour IS NOT NULL, hour DESC
