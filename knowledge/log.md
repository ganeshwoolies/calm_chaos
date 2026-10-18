# Log

## 2026-10-18

**Creation** learned/, for notes promoted from observations a coordinator verified. Each arrives as a pull request
that touches only learned/; coordinator practice is one playbook note, learned/playbook/coordinator-practice.md.

**Update** Published versus landed counts only events published to psd-events. An incident candidate goes to
psd-agents on psd-incident-candidates and never lands in events, so a label candidate, which has no notice event
behind it, no longer shows as missing.

**Creation** The scoreboard, as drafts: ten Metric concepts in metrics/, each with the Attested Computation and SQL
file behind its tile, and the desk_records table concept with its four views.

**Creation** The shelf check policy, as a draft: a shelf photo verifies a hold or pull task clear when no unit is
visible with confidence at least clear_min_confidence in a usable photo, not clear when a unit is visible, and asks
for a retake otherwise.

## 2026-10-17

**Creation** The bundle as drafts:
- the policy: hazard taxonomy, recall response, label rules, match rule, incident handling;
- eight hazard playbooks;
- the references for warning hazards, allergens and the vendor case format.

The values come from the Phase 1 design, sections 8, 10 and 12. Each concept becomes stable once a person has reviewed it
and added their verification.

**Creation** The recall lineage attested computation, with its SQL, its SQL equality attester and the run-on-BigQuery
reference, and a BigQuery Table concept for each table it reads or writes.

**Creation** The recall notice formats reference, and a BigQuery Table concept for each table the recall trigger writes:
events, recall_notices, recall_matches, incident_candidates, publish_log, publish_failures and product_embeddings.

**Update** products: catalogue embeddings moved to their own table, product_embeddings.

**Update** Source titles credit each licensor as it asks: "Food Standards Australia New Zealand" for FSANZ pages, and
"based on ACCC content" for ACCC pages, which the playbooks paraphrase.

**Update** The fictional retailer is Larkhaven, and the planted yoghurt brand is Morrowdale.

**Update** Recall notice formats: FSANZ content is credited on the terms of its copyright page, and fictional test
notices carry FICTIONAL TEST in their title and guid. The match rule's "none" outcome reads "not in the fictional
Larkhaven demo catalogue".

**Update** Sources that cited the team's private design notes now cite the repository's agent spec. Spoilage is stated
as the desk's own hazard type, with no FSANZ citation, and the hazard taxonomy names which hazard types correspond to
FSANZ recall classes. The FSANZ credit carries the Creative Commons Attribution licence link.

**Update** Match rule: how barcodes and the ambiguity gap decide a match, what Gemini confirms, that only feeds
configured for matching are matched, and that a notice whose embedding fails is tried again. Recall response and recall
lineage: the batches traced when a notice names no batch code. Incident handling: the suppression window holds back only
the dismissed candidate.

**Update** Sources. Recall response cites FSANZ's About food recalls for its coordinating role and the recall levels,
and gives the protocol's contents and the post-recall report deadlines. Label rules and the electrical fire playbook
follow ERAC on the RCM and on checking Level 3 certification. The choking playbook and warning hazards cite the toys
safety standard itself. The chemical playbook raises mandatory reporting for food as well as household products.
Allergens: gluten in the summary statement, and the date until which food labelled under the earlier rules could be
sold. Recall notice formats cite FSANZ's copyright terms.

**Creation** The label_checks table concept: one row per label photo a store sends, with the read, the match and the
findings the label rules gave.

**Update** The fictional retailer is CalmChaosRetail. The match rule's "none" outcome reads "not in catalogue" on
the desk, and the generated test labels and shelf images are stamped FICTIONAL TEST with the retailer's name.
