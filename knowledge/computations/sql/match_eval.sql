-- Detection against the truth tables: test-feed notices against truth_recalls by scenario (the guid's third part), and
-- label checks against truth_labels by product and lot. Precision is correct over predicted, recall correct over
-- expected.
WITH notices AS (
  SELECT SPLIT(guid, ':')[SAFE_OFFSET(2)] AS scenario, match_status, matched_product_id
  FROM recall_notices
  WHERE STARTS_WITH(guid, 'FICTIONAL-TEST:')
),
recalls AS (
  SELECT
    COUNT(*) AS judged,
    COUNTIF(n.matched_product_id IS NOT NULL) AS predicted,
    COUNTIF(t.product_id IS NOT NULL) AS expected,
    COUNTIF(n.matched_product_id = t.product_id) AS correct,
    COUNTIF(n.match_status = t.expected_match_status) AS status_agrees
  FROM notices AS n
  JOIN truth_recalls AS t USING (scenario)
),
checks AS (
  SELECT
    t.expected_rules,
    ARRAY(SELECT JSON_VALUE(f, '$.rule') FROM UNNEST(JSON_QUERY_ARRAY(c.findings)) AS f) AS rules
  FROM label_checks AS c
  JOIN truth_labels AS t ON t.product_id = c.product_id AND t.lot = c.lot
  WHERE c.status IN ('checked', 'findings')
),
labels AS (
  SELECT
    COUNT(*) AS judged,
    SUM(ARRAY_LENGTH(rules)) AS predicted,
    SUM(ARRAY_LENGTH(expected_rules)) AS expected,
    SUM((SELECT COUNT(*) FROM UNNEST(rules) AS r WHERE r IN UNNEST(expected_rules))) AS correct
  FROM checks
)
SELECT
  'recall_match' AS detection, judged, predicted, expected, correct,
  ROUND(SAFE_DIVIDE(correct, predicted), 3) AS precision,
  ROUND(SAFE_DIVIDE(correct, expected), 3) AS recall,
  status_agrees
FROM recalls
UNION ALL
SELECT
  'label_findings', judged, predicted, expected, correct,
  ROUND(SAFE_DIVIDE(correct, predicted), 3),
  ROUND(SAFE_DIVIDE(correct, expected), 3),
  CAST(NULL AS INT64)
FROM labels
ORDER BY CASE detection WHEN 'recall_match' THEN 0 ELSE 1 END
