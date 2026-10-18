-- Per incident, and over all incidents in the row whose incident_id is NULL: stores tasked and stores verified clear,
-- and tasks issued, where a task issued again after a shelf was not clear counts again.
SELECT
  incident_id,
  COUNT(DISTINCT CONCAT(incident_id, ':', store_id)) AS stores_tasked,
  COUNT(DISTINCT IF(status = 'verified_clear', CONCAT(incident_id, ':', store_id), NULL)) AS stores_verified,
  COUNT(*) AS tasks_issued,
  COUNTIF(status = 'verified_clear') AS tasks_verified_clear,
  COUNTIF(status = 'open') AS tasks_open
FROM v_desk_tasks
GROUP BY ROLLUP (incident_id)
ORDER BY incident_id IS NULL DESC, incident_id
