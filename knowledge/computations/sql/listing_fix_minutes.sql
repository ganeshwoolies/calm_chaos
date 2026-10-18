-- Each listing fix, from the first label check that found its defect to the fix applied.
WITH timed AS (
  SELECT TIMESTAMP_DIFF(ANY_VALUE(l.applied_at), MIN(c.checked_at), SECOND) / 60 AS minutes
  FROM v_desk_listing_changes AS l
  JOIN v_desk_incidents AS i USING (incident_id)
  JOIN label_checks AS c ON c.candidate_id = i.candidate_id
  GROUP BY l.change_id
)
SELECT
  COUNT(*) AS fixes,
  ROUND(APPROX_QUANTILES(minutes, 100)[SAFE_OFFSET(50)], 1) AS median_minutes,
  ROUND(MAX(minutes), 1) AS max_minutes
FROM timed
