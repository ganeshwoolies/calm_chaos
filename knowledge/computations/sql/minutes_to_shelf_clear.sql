-- Each approved incident with store tasks: minutes from approval to the last shelf verified, once no task is open,
-- against the policy target.
WITH per_incident AS (
  SELECT
    t.incident_id,
    COUNTIF(t.status = 'open') AS open_tasks,
    TIMESTAMP_DIFF(MAX(t.verified_at), ANY_VALUE(i.approved_at), SECOND) / 60 AS minutes,
    ANY_VALUE(i.shelf_target_minutes) AS target_minutes
  FROM v_desk_tasks AS t
  JOIN v_desk_incidents AS i USING (incident_id)
  WHERE i.approved_at IS NOT NULL
  GROUP BY t.incident_id
)
SELECT
  COUNTIF(open_tasks = 0) AS incidents_clear,
  COUNTIF(open_tasks > 0) AS incidents_verifying,
  ROUND(APPROX_QUANTILES(IF(open_tasks = 0, minutes, NULL), 100)[SAFE_OFFSET(50)], 1) AS median_minutes,
  ROUND(MAX(IF(open_tasks = 0, minutes, NULL)), 1) AS max_minutes,
  COUNTIF(open_tasks = 0 AND minutes <= target_minutes) AS within_target
FROM per_incident
