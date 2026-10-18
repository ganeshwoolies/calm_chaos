---
type: Reference
title: Recall notice formats
description: The sections of an FSANZ food recall and an ACCC product safety recall, and which of them the poller reads.
tags: [reference, recall, notices]
status: draft
sources:
  - id: fsanz-feed
    resource: https://www.foodstandards.gov.au/food-recalls-rss.xml
    title: Food Standards Australia New Zealand, food recalls RSS feed
  - id: fsanz-copyright
    resource: https://www.foodstandards.gov.au/legal-policies/copyright
    title: Food Standards Australia New Zealand, Copyright
  - id: accc-recalls
    resource: https://www.productsafety.gov.au/recalls
    title: ACCC Product Safety Australia, recalls (based on ACCC content)
---
# FSANZ food recalls

The feed is RSS 2.0, newest first[^fsanz-feed]. Each item has a title, a link, a guid such as
`7222 at https://www.foodstandards.gov.au` that never changes, a publication time, and a description that holds the
notice as HTML fields, each marked by its CSS class:

| Class | Heading | Read |
|---|---|---|
| field-recall-business | none: the recalling business | yes, as "Business" |
| field-bare | none: who is recalling what, and where it was sold | yes |
| field-location | Distributed in | yes |
| field-recall-type | Recall reason | yes |
| field-date-marking | Date marking(s) | yes |
| field-problem | Problem | yes |
| field-food-safety-hazard | Food safety hazard | yes |
| field-what-to-do | What to do | yes |
| field-further-information | the business's phone, email and website | no |
| field-food-recall-image, field-document | product images and the recall PDF | no |

Older notices hold the whole notice in the summary under `h2` headings, ending with contact details and related links;
the poller cuts the text at those headings. The item's `dc:creator` names an FSANZ staff member and is never read.

FSANZ licenses its content under Creative Commons Attribution on the terms of its copyright page, which links the
licence at https://creativecommons.org/licenses/by/3.0/au/; its logo and third-party material are
excluded[^fsanz-copyright]. The desk keeps each notice's title and link with its text, and credits it "© Food Standards
Australia New Zealand", noting that the text is shortened, its fields are extracted by AI and FSANZ does not endorse the
desk. It stores no logo, image or PDF from a notice.

# ACCC product safety recalls

A recall page has these sections, in order[^accc-recalls]: Recall published, PRA number, Product description, Brand,
Model, Reason the product is recalled, The hazards to consumers, What consumers should do, Identifying numbers (barcode,
SKU), Dates available for sale, and Where the product was sold.

The site refuses automated clients, so the desk does not poll it. Only fictional test notices use this layout.

# Fictional test notices

`data/gen_notices.py` writes one notice for each recall scenario, in the FSANZ or the ACCC layout. Each one carries the
banner "Fictional test notice: not issued by FSANZ or the ACCC", "FICTIONAL TEST" in its title and guid, a `TEST-`
reference number and a fictional brand. They
use the regulators' section headings and nothing else, and are kept only in the project's private feeds bucket.

[^fsanz-feed]: The feed's items, read with conditional GET; `robots.txt` allows it.
[^fsanz-copyright]: The credit names "Food Standards Australia New Zealand" and must not suggest that FSANZ endorses the
    user or the use.
[^accc-recalls]: The section headings of a recall page on productsafety.gov.au.
