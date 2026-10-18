-- The catalogue products each extracted notice in @notices may name, for decide() in api/scope.py:
-- - products whose barcode the notice prints (method barcode; no model involved);
-- - otherwise, or for every notice when @barcode_first is false, the @top_k nearest products by embedding. Gemini
--   confirms or rejects each one within @max_distance as the product the notice recalls; same_product is NULL when
--   the call failed or was not made.
-- A notice whose own embedding failed returns a single embedding_failed row, so it is retried rather than read as
-- naming nothing. The notice side embeds like embed_catalogue.sql; change both or neither.
CREATE TEMP TABLE matching_notice AS
WITH barcode AS (
  SELECT n.event_id, ARRAY_AGG(DISTINCT p.product_id) AS products
  FROM UNNEST(@notices) AS n, UNNEST(n.barcodes) AS code
  JOIN products AS p ON p.barcode = code
  GROUP BY n.event_id
)
SELECT
  n.event_id,
  n.brand,
  n.product_name,
  n.sizes,
  b.products AS barcode_products,
  IF(
    b.products IS NULL OR NOT @barcode_first,
    AI.EMBED(
      CONCAT(n.brand, ' ', n.product_name, ' ', n.sizes), endpoint => 'gemini-embedding-2',
      model_params => JSON '{"outputDimensionality": 768}'
    ),
    NULL
  ) AS embedded
FROM UNNEST(@notices) AS n
LEFT JOIN barcode AS b USING (event_id);

WITH neighbour AS (
  SELECT
    v.query.event_id,
    v.base.product_id,
    v.distance,
    ROW_NUMBER() OVER (PARTITION BY v.query.event_id ORDER BY v.distance) AS rank
  FROM VECTOR_SEARCH(
    TABLE product_embeddings, 'embedding',
    (SELECT event_id, embedded.result AS embedding FROM matching_notice WHERE ARRAY_LENGTH(embedded.result) = 768),
    'embedding', top_k => @top_k, distance_type => 'COSINE'
  ) AS v
)
SELECT n.event_id, product_id, 1 AS rank, 'barcode' AS method, CAST(NULL AS FLOAT64) AS distance, TRUE AS same_product
FROM matching_notice AS n, UNNEST(n.barcode_products) AS product_id
UNION ALL
SELECT
  nb.event_id,
  nb.product_id,
  nb.rank,
  'embedding',
  nb.distance,
  IF(
    nb.distance <= @max_distance,
    -- A notice often names the recalling business where the brand belongs ("Acme Dairy Co" for the brand "Acme"), so
    -- the fields go separately and a business named after the brand counts as that brand.
    AI.IF(
      (
        'A retailer sells: brand "', p.brand, '", product "', p.name, '", pack size "', p.size,
        '". A recall notice names: brand or recalling business "', n.brand, '", product "', n.product_name,
        '", pack sizes "', IF(n.sizes = '', 'not stated', n.sizes),
        '". The retailer product is a product this notice recalls: the same brand, where a business named after',
        ' the brand (the brand followed by words such as Co, Foods or Pty Ltd) counts as that brand; the same',
        ' product and variant; and either one of the pack sizes the notice states, or any pack size when the',
        ' notice states none.'
      ),
      endpoint => 'gemini-3.8-flash'
    ),
    NULL
  )
FROM neighbour AS nb
JOIN matching_notice AS n USING (event_id)
JOIN products AS p USING (product_id)
UNION ALL
SELECT event_id, CAST(NULL AS STRING), NULL, 'embedding_failed', NULL, NULL
FROM matching_notice
WHERE (barcode_products IS NULL OR NOT @barcode_first) AND IFNULL(ARRAY_LENGTH(embedded.result), 0) != 768
