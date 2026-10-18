-- Each approved incident that messages online orders: minutes from approval to its last customer message sent, against
-- the policy target, and messages sent over orders to message, which must be 1.
WITH per_incident AS (
  SELECT
    i.incident_id,
    ANY_VALUE(i.orders_to_message) AS orders_to_message,
    ANY_VALUE(i.message_target_minutes) AS target_minutes,
    COUNTIF(o.sent_at IS NOT NULL) AS sent,
    TIMESTAMP_DIFF(MAX(o.sent_at), ANY_VALUE(i.approved_at), SECOND) / 60 AS minutes
  FROM v_desk_incidents AS i
  LEFT JOIN v_desk_outbox AS o ON o.incident_id = i.incident_id AND o.audience = 'customer'
  WHERE i.approved_at IS NOT NULL AND i.orders_to_message > 0
  GROUP BY i.incident_id
)
SELECT
  COUNT(*) AS incidents,
  SUM(sent) AS messages_sent,
  SUM(orders_to_message) AS orders_to_message,
  ROUND(SAFE_DIVIDE(SUM(sent), SUM(orders_to_message)), 3) AS sent_ratio,
  ROUND(MAX(minutes), 1) AS max_minutes,
  COUNTIF(minutes <= target_minutes) AS within_target
FROM per_incident
