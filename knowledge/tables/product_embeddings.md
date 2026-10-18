---
type: BigQuery Table
title: product_embeddings
description: "One embedding per catalogue product, which recall matching searches with VECTOR_SEARCH."
tags: [table, catalogue, matching]
status: draft
resource: psd.product_embeddings
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| product_id | STRING | Catalogue product |
| content | STRING | Text embedded: brand, name, size and subcategory |
| content_hash | STRING | SHA-256 of the content; a product is embedded again only when it changes |
| embedding | ARRAY<FLOAT64> | 768-dimension gemini-embedding-2 embedding |
| embedded_at | TIMESTAMP | When it was embedded |

# Joins

- `product_id` → [products](/tables/products.md)
