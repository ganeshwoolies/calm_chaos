CREATE TABLE IF NOT EXISTS product_embeddings (
  product_id STRING NOT NULL,
  content STRING,
  content_hash STRING,
  embedding ARRAY<FLOAT64>,
  embedded_at TIMESTAMP
);
