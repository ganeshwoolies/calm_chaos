---
okf_version: "0.2"
---
# CalmChaosRetail product safety knowledge

The authority for every rule the desk applies and every playbook its drafters read. Code and prompts use a concept only
when it is stable, verified by a person and not stale.

## Policy

* [Hazard taxonomy](policy/hazard-taxonomy.md) - The closed lists of categories, hazard types and severities.
* [Recall response](policy/recall-response.md) - Severity by hazard, time targets, checkout block and exposure for recalls.
* [Label rules](policy/label-rules.md) - How label check differences become findings, severities and actions.
* [Recall notice to catalogue match rule](policy/match-rule.md) - How a notice is matched to a catalogue product.
* [Incident handling](policy/incident-handling.md) - Rules that apply to every incident, such as dismissal suppression.
* [Shelf check](policy/shelf-check.md) - How a shelf photo decides whether a hold or pull task is verified clear.

## Playbooks

* [Microbial contamination](playbooks/microbial.md) - Food that may carry harmful bacteria, viruses or toxins.
* [Undeclared or mislabelled allergen](playbooks/allergen.md) - An allergen missing from a pack or listing.
* [Foreign matter](playbooks/foreign-matter.md) - Glass, metal, plastic or other material in food.
* [Spoilage](playbooks/spoilage.md) - Food that may spoil early, for example from a seal fault.
* [Electrical fire or shock](playbooks/electrical-fire.md) - Electrical products that may overheat, burn or shock.
* [Choking hazard](playbooks/choking.md) - Small or detachable parts a young child could choke on.
* [Chemical contamination](playbooks/chemical.md) - A harmful chemical in food or a household product.
* [Injury hazard](playbooks/injury.md) - Products that can cut, crush or burn, and missing button battery warnings.

## References

* [Warning hazards](references/warning-hazards.md) - The hazard and severity behind a missing pack warning.
* [Allergens that must be declared](references/allergens.md) - Required allergen names and their summary terms.
* [Vendor case format](references/vendor-case-format.md) - The sections of every vendor case.
* [Run on BigQuery](references/run-on-bigquery.md) - How an attested computation runs and what its receipt holds.
* [Recall notice formats](references/notice-formats.md) - The sections of FSANZ and ACCC recall notices, and which the poller reads.

## Learned

* [Learned](learned/index.md) - Notes promoted from observations a coordinator verified, by pull request only.

## Metrics

The scoreboard's tiles, in order. Each shows only what its attested computation returns.

* [Minutes to candidate](metrics/minutes-to-candidate.md) - How long a recall notice takes to become an incident candidate.
* [Minutes to approve](metrics/minutes-to-approve.md) - How long an incident waits for the coordinator's approval.
* [Customers messaged](metrics/customers-messaged.md) - Whether every exposed online order was messaged, and how soon.
* [Minutes to shelf clear](metrics/minutes-to-shelf-clear.md) - How long after approval every affected shelf is verified clear.
* [Stores verified](metrics/stores-verified.md) - Tasked stores that verified their shelf clear, per incident and overall.
* [Listing fix minutes](metrics/listing-fix-minutes.md) - How long a label defect stays in the listing after a store finds it.
* [Notice outcomes](metrics/notice-outcomes.md) - Recall notices seen, by feed and match status.
* [Label findings](metrics/label-findings.md) - Label checks, the candidates they raised, findings by rule and severity.
* [Published versus landed](metrics/published-vs-landed.md) - Events published against events landed in BigQuery, per hour.
* [Detection quality](metrics/match-eval.md) - Recall matching and label findings against the truth tables.

## Computations

* [Recall lineage](computations/recall-lineage.md) - Stores and online orders that received the batches a notice or a pack names.
* [Minutes to candidate](computations/minutes-to-candidate.md) - The attested computation behind the Minutes to candidate tile.
* [Minutes to approve](computations/minutes-to-approve.md) - The attested computation behind the Minutes to approve tile.
* [Customers messaged](computations/customers-messaged.md) - The attested computation behind the Customers messaged tile.
* [Minutes to shelf clear](computations/minutes-to-shelf-clear.md) - The attested computation behind the Minutes to shelf clear tile.
* [Stores verified](computations/stores-verified.md) - The attested computation behind the Stores verified tile.
* [Listing fix minutes](computations/listing-fix-minutes.md) - The attested computation behind the Listing fix minutes tile.
* [Notice outcomes](computations/notice-outcomes.md) - The attested computation behind the Notice outcomes tile.
* [Label findings](computations/label-findings.md) - The attested computation behind the Label findings tile.
* [Published versus landed](computations/published-vs-landed.md) - The attested computation behind the Published versus landed tile.
* [Detection quality](computations/match-eval.md) - The attested computation behind the Detection quality tile.

## Tables

* [products](tables/products.md) - The catalogue, with each product's online listing.
* [suppliers](tables/suppliers.md) - Suppliers, one per brand.
* [supplier_specs](tables/supplier_specs.md) - Every version of each product specification.
* [stores](tables/stores.md) - Stores and the distribution centre serving each.
* [batches](tables/batches.md) - Batches and lots, with the code printed on the pack.
* [deliveries](tables/deliveries.md) - Deliveries of batches to stores: the edge lineage follows.
* [store_stock](tables/store_stock.md) - Units of each batch a store still holds.
* [online_orders](tables/online_orders.md) - Online orders and the store fulfilling each.
* [order_lines](tables/order_lines.md) - The products and batches in each online order.
* [attestations](tables/attestations.md) - The receipt of every attested computation run.
* [events](tables/events.md) - Every tagged event the BigQuery subscription lands; read through v_events_dedup.
* [recall_notices](tables/recall_notices.md) - Every notice the desk has seen and the match status it reached.
* [recall_matches](tables/recall_matches.md) - Every catalogue product considered for a notice.
* [incident_candidates](tables/incident_candidates.md) - Candidates raised for the incident workflow, and whether published.
* [publish_log](tables/publish_log.md) - Every publish attempt psd-api made.
* [publish_failures](tables/publish_failures.md) - Messages psd-api gave up publishing, with their bodies.
* [product_embeddings](tables/product_embeddings.md) - Catalogue embeddings that recall matching searches.
* [label_checks](tables/label_checks.md) - Every label photo a store sent, what was read and the findings.
* [truth_recalls](tables/truth_recalls.md) - Ground truth for the recall scenarios, for evaluation only.
* [truth_labels](tables/truth_labels.md) - Ground truth for the label fixtures, for evaluation only.
* [desk_records](tables/desk_records.md) - Every version of every desk record, and the views of each record's latest.
