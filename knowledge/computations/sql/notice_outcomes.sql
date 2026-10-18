-- Recall notices seen: the total first, then by feed and match status.
SELECT feed, match_status, COUNT(*) AS notices
FROM recall_notices
GROUP BY GROUPING SETS ((), (feed, match_status))
ORDER BY feed IS NOT NULL, feed, notices DESC, match_status
