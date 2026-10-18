-- Each approved incident, from its candidate being raised to the coordinator's approval.
WITH timed AS (
  SELECT TIMESTAMP_DIFF(i.approved_at, c.created_at, SECOND) / 60 AS minutes
  FROM v_desk_incidents AS i
  JOIN incident_candidates AS c USING (candidate_id)
  WHERE i.approved_at IS NOT NULL
)
SELECT
  COUNT(*) AS incidents,
  ROUND(APPROX_QUANTILES(minutes, 100)[SAFE_OFFSET(50)], 1) AS median_minutes,
  ROUND(MAX(minutes), 1) AS max_minutes
FROM timed
