---
type: BigQuery Table
title: products
description: "The CalmChaosRetail catalogue: every product with its online listing."
tags: [table, catalogue, listing]
status: draft
resource: psd.products
---
# Schema

| Column | Type | Meaning |
|---|---|---|
| product_id | STRING | Product id, `P` and five digits |
| name | STRING | Product name without brand or size, e.g. Vanilla Yoghurt |
| brand | STRING | Brand, always fictional |
| size | STRING | Pack size as printed, e.g. 1kg |
| category | STRING | Category from the hazard taxonomy |
| subcategory | STRING | Shelf grouping, e.g. dairy |
| barcode | STRING | EAN-13 barcode |
| supplier_id | STRING | Supplier of the product |
| unit_price | NUMERIC | Shelf price in AUD |
| listing_text | STRING | Online listing description |
| listing_allergens | ARRAY<STRING> | Allergens the online listing declares |
| listing_warnings | ARRAY<STRING> | Warnings the online listing shows |
| listing_marks | ARRAY<STRING> | Compliance marks the online listing shows |
| listing_origin | STRING | Country of origin statement on the listing |

# Joins

- `supplier_id` → [suppliers](/tables/suppliers.md)
- `product_id` → [batches](/tables/batches.md), [supplier_specs](/tables/supplier_specs.md),
  [product_embeddings](/tables/product_embeddings.md)
