-- Sanctioned computation of /computations/recall-lineage.md. Run only through run_attested, which binds the declared
-- parameters by name and checks that BigQuery executed exactly this text.
WITH hit AS (
  SELECT batch_id, code, best_before
  FROM batches
  WHERE product_id = @product_id
    AND (
      code IN UNNEST(@codes)
      -- An empty array parameter arrives as NULL, hence IFNULL: without it a notice naming no batch matches nothing.
      OR (IFNULL(ARRAY_LENGTH(@codes), 0) = 0 AND best_before BETWEEN @best_before_from AND @best_before_to)
      OR (IFNULL(ARRAY_LENGTH(@codes), 0) = 0 AND @best_before_from IS NULL)
    )
),
store_rows AS (
  SELECT
    'store' AS row_kind,
    h.batch_id,
    h.code,
    d.store_id,
    SUM(d.qty) AS delivered,
    MAX(d.delivered_at) AS last_delivered,
    ANY_VALUE(COALESCE(ss.on_hand, 0)) AS on_hand,
    ANY_VALUE(ss.aisle) AS aisle,
    CAST(NULL AS STRING) AS order_id
  FROM hit AS h
  JOIN deliveries AS d USING (batch_id)
  LEFT JOIN store_stock AS ss ON ss.store_id = d.store_id AND ss.batch_id = h.batch_id
  WHERE d.delivered_at <= @as_of
  GROUP BY h.batch_id, h.code, d.store_id
),
order_rows AS (
  SELECT
    'order' AS row_kind,
    h.batch_id,
    h.code,
    o.store_id,
    CAST(NULL AS INT64) AS delivered,
    CAST(NULL AS TIMESTAMP) AS last_delivered,
    CAST(NULL AS INT64) AS on_hand,
    CAST(NULL AS STRING) AS aisle,
    o.order_id
  FROM hit AS h
  JOIN order_lines AS ol USING (batch_id)
  JOIN online_orders AS o USING (order_id)
  WHERE o.ordered_at BETWEEN TIMESTAMP_SUB(@as_of, INTERVAL @order_lookback_days DAY) AND @as_of
)
SELECT * FROM store_rows
UNION ALL
SELECT * FROM order_rows
ORDER BY row_kind DESC, on_hand DESC, store_id, order_id
