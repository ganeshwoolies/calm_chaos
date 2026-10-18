-- Embeds every catalogue product whose content is new or has changed since it was embedded, for VECTOR_SEARCH in
-- match_recalls.sql. A failed embedding is not stored, so the next run retries it. The content, endpoint and
-- dimensions must stay the same as the notice side in match_recalls.sql, or the distances mean nothing.
MERGE product_embeddings AS t
USING (
  SELECT product_id, content, content_hash, embedding
  FROM (
    SELECT
      c.product_id,
      c.content,
      c.content_hash,
      AI.EMBED(
        c.content, endpoint => 'gemini-embedding-2', model_params => JSON '{"outputDimensionality": 768}'
      ).result AS embedding
    FROM (
      SELECT product_id, content, TO_HEX(SHA256(content)) AS content_hash
      FROM (SELECT product_id, CONCAT(brand, ' ', name, ' ', size, ' ', subcategory) AS content FROM products)
    ) AS c
    LEFT JOIN product_embeddings AS e USING (product_id)
    WHERE e.content_hash IS DISTINCT FROM c.content_hash
  )
  WHERE ARRAY_LENGTH(embedding) = 768
) AS s
ON t.product_id = s.product_id
WHEN MATCHED THEN
  UPDATE SET content = s.content, content_hash = s.content_hash, embedding = s.embedding,
    embedded_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (product_id, content, content_hash, embedding, embedded_at)
  VALUES (s.product_id, s.content, s.content_hash, s.embedding, CURRENT_TIMESTAMP())
