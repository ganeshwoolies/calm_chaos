-- Each notice that raised a candidate, timed from the poller first seeing it and from the regulator publishing it; the
-- second includes the wait for the next poll.
WITH timed AS (
  SELECT
    TIMESTAMP_DIFF(c.created_at, n.first_seen, SECOND) / 60 AS from_first_seen,
    TIMESTAMP_DIFF(c.created_at, n.published_at, SECOND) / 60 AS from_published
  FROM recall_notices AS n
  JOIN incident_candidates AS c ON c.candidate_id = n.candidate_id
)
SELECT
  COUNT(*) AS notices,
  ROUND(APPROX_QUANTILES(from_first_seen, 100)[SAFE_OFFSET(50)], 1) AS median_minutes,
  ROUND(MAX(from_first_seen), 1) AS max_minutes,
  ROUND(APPROX_QUANTILES(from_published, 100)[SAFE_OFFSET(50)], 1) AS median_minutes_from_published,
  ROUND(MAX(from_published), 1) AS max_minutes_from_published
FROM timed
