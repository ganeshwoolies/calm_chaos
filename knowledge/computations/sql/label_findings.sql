-- Label checks first, then the label candidates they raised, then their findings by rule and severity.
WITH found AS (
  SELECT JSON_VALUE(f, '$.rule') AS rule, JSON_VALUE(f, '$.severity') AS severity
  FROM label_checks AS c, UNNEST(JSON_QUERY_ARRAY(c.findings)) AS f
)
SELECT 'checks' AS measure, CAST(NULL AS STRING) AS rule, CAST(NULL AS STRING) AS severity, COUNT(*) AS n
FROM label_checks
UNION ALL
SELECT 'candidates_raised', NULL, NULL, COUNT(DISTINCT candidate_id)
FROM label_checks
WHERE candidate_id IS NOT NULL
UNION ALL
SELECT 'findings', rule, severity, COUNT(*)
FROM found
GROUP BY rule, severity
ORDER BY CASE measure WHEN 'checks' THEN 0 WHEN 'candidates_raised' THEN 1 ELSE 2 END, n DESC, rule
