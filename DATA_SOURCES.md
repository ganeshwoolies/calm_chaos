# Data sources

An independent hackathon entry for the AI Builder Cup 2026, not affiliated with or endorsed by any retailer, FSANZ or
the ACCC. CalmChaosRetail and every brand in its catalogue are fictional.

## FSANZ food recalls

- **Source:** Food Standards Australia New Zealand, food recalls RSS feed,
  https://www.foodstandards.gov.au/food-recalls-rss.xml.
- **Terms:** FSANZ licenses its content under Creative Commons Attribution, on the terms of its copyright page,
  https://www.foodstandards.gov.au/legal-policies/copyright, which links the licence deed https://creativecommons.org/licenses/by/3.0/au/. The desk credits it as
  "© Food Standards Australia New Zealand" with both links.
- **How it is read:** every 15 minutes, with conditional GET and a User-Agent that names the Product Safety Desk
  prototype. A feed that errors or answers 429 is polled less often. `robots.txt` allows the feed.
- **What is kept:** each item's title, link, guid, publication time, and the notice fields of its description
  (business, summary, where it was distributed, recall reason, date markings, problem, food safety hazard, what to do),
  at most 12,000 characters.
- **What is never kept:** `dc:creator`, which names an FSANZ staff member; the recalling business's contact details;
  product images; recall PDFs.
- **Credit on every notice:** each notice is stored with its title, its link and the credit from `config/feeds.yaml`:
  "© Food Standards Australia New Zealand", the copyright page link, "Licensed under Creative Commons Attribution"
  with the licence link, and "Shortened; fields extracted by AI; not endorsed by FSANZ". All of it goes wherever the
  notice is shown.
- **Contacts:** any email address or phone number left in a notice's text is removed, whatever its layout. Notice
  pages are fetched only under https://www.foodstandards.gov.au/food-recalls/, at most three a poll; a refusal ends
  page fetches for the poll, and a feed that refuses three times in a row is stopped.
- **Real brands:** live notices name real brands, which the fictional catalogue does not sell. The scope job never
  matches a notice from a live feed, by rule rather than by the model's judgement, so live notices only ever appear as
  "not in catalogue".
- **Saved copy:** `tests/unit/feeds/fsanz_feed.xml` holds four items of the feed for offline parser tests, credited as
  above. Staff identifiers, business contact details and the links to product images and recall documents are replaced
  by `example.invalid` placeholders, and the business, brand, product and store names, with the link paths that carry
  them, by fictional ones.

## Knowledge bundle citations

The playbooks, policies and references in `knowledge/` paraphrase public guidance and cite each page in their
`sources`:
- FSANZ pages (food recalls, the Food Industry Recall Protocol, allergen labelling), credited to Food Standards
  Australia New Zealand on the terms of its copyright page.
- ACCC Product Safety pages (mandatory reporting, recall notification, mandatory standards for toys and button
  batteries), marked "based on ACCC content". Source: ACCC © Commonwealth of Australia. The desk uses no ACCC logo,
  Coat of Arms or third-party material, and implies no endorsement by the ACCC.

## ACCC Product Safety Australia

Not polled. productsafety.gov.au refuses automated clients, and the desk does not disguise itself to get past that.
Polling it would need the ACCC's agreement first; enquiries about reusing its content go to stratcomms@accc.gov.au.
The desk uses only the section headings of an ACCC recall notice, for fictional test notices.

## Fictional test notices

`data/gen_notices.py` writes one notice per recall scenario in `data/truth.yaml`, in the FSANZ or the ACCC layout. Each
carries the banner "Fictional test notice: not issued by FSANZ or the ACCC", "FICTIONAL TEST" in its title and guid, a
`TEST-` reference number and a fictional brand. The poller adds the title label itself for every notice from the test
feed (`fictional: true` in `config/feeds.yaml`), never from the notice's text or a model's output. They are hosted only
in the project's private feeds bucket, which blocks public access.

## The synthetic retailer

CalmChaosRetail, its stores, catalogue, suppliers, batches, deliveries, stock and online orders are fictional and generated
by code from `data/truth.yaml` and a fixed seed (`data/gen_catalogue.py`, `data/gen_supply.py`). No real customer,
retailer or supplier data is used; online customers are opaque references with no names or contact details.

## Label photos

`data/gen_labels.py` draws the pack labels the label check reads, from the same generated catalogue and specs, with
system fonts and Pillow. Every label says "FICTIONAL TEST LABEL · CalmChaosRetail · not a real product", and the brands
are the catalogue's fictional ones. Photos sent from the store page are stored in the project's photos bucket and
deleted after 7 days; they are of fictional labels only.

## Shelf photos

`data/gen_shelves.py` draws the shelves the shelf check reads, with the same generated catalogue's fictional products,
system fonts and Pillow. Every image says "FICTIONAL TEST IMAGE · CalmChaosRetail · not a real shelf or a real product".
Shelf photos sent from the store page are stored in the project's photos bucket and deleted after 7 days.

## Before real use

These measures fit a hackathon prototype on public data. Before any use with a real retailer, a lawyer should review
data use, privacy (the Australian Privacy Principles) and consumer messaging.
