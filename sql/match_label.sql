-- The catalogue products a label read may be, for api/labels.py: the product whose barcode the pack prints, and the
-- @top_k nearest products by embedding, which decide only when no barcode matches. The read side embeds like
-- embed_catalogue.sql; change both or neither.
SELECT p.product_id, p.brand, p.name, p.size, 'barcode' AS method, CAST(NULL AS FLOAT64) AS distance
FROM products AS p
WHERE p.barcode = @barcode
UNION ALL
SELECT p.product_id, p.brand, p.name, p.size, 'embedding', v.distance
FROM VECTOR_SEARCH(
  TABLE product_embeddings, 'embedding',
  (
    SELECT e.result AS embedding
    FROM (
      SELECT AI.EMBED(@content, endpoint => 'gemini-embedding-2', model_params => JSON '{"outputDimensionality": 768}') AS e
    )
    WHERE ARRAY_LENGTH(e.result) = 768
  ),
  'embedding', top_k => @top_k, distance_type => 'COSINE'
) AS v
JOIN products AS p ON p.product_id = v.base.product_id
ORDER BY method, distance
