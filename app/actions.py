"""Proposed actions, computed from policy and evidence. Deterministic: no model output is read here."""

from datetime import datetime, timedelta

from app.policy import Policy
from app.schemas import (
    EvidencePack,
    Lineage,
    LineageRow,
    ListingFix,
    ProposedActions,
    StoreAction,
    Targets,
)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def propose(ev: EvidencePack, pol: Policy) -> ProposedActions:
    pol.check_evidence(ev)
    if ev.kind == "recall":
        return _propose_recall(ev, pol)
    return _propose_label(ev, pol)


def exposed_stores(lineage: Lineage | None, pol: Policy) -> list[LineageRow]:
    """Store rows that still hold the batch or received it within the exposure window."""
    if lineage is None:
        return []
    as_of = _parse(lineage.as_of)
    window = timedelta(days=pol.recall.exposure_days)
    return [
        row
        for row in lineage.store_rows
        if (row.on_hand or 0) > 0
        or (
            row.last_delivered is not None
            and as_of - _parse(row.last_delivered) <= window
        )
    ]


def _propose_recall(ev: EvidencePack, pol: Policy) -> ProposedActions:
    severity = pol.recall_severity(ev.hazard_type)
    target = pol.recall.targets_minutes[severity]
    lineage = ev.lineage
    store_actions = [
        StoreAction(
            store_id=row.store_id,
            batch_id=row.batch_id,
            code=row.code,
            action="pull",
            qty_on_hand=row.on_hand or 0,
            aisle=row.aisle,
        )
        for row in exposed_stores(lineage, pol)
    ]
    considerations = []
    extract = ev.notice.extract if ev.notice else None
    if extract and not extract.batch_codes and not extract.date_codes:
        considerations.append(
            "The notice names no batch, so the proposal covers every batch of the product."
        )
    best_before = [
        d
        for d in (extract.date_codes if extract else [])
        if d.get("kind") == "best_before"
    ]
    if (
        extract
        and not extract.batch_codes
        and len(best_before) > 1
        and all(d.get("from") for d in best_before)
    ):
        considerations.append(
            f"The notice names {len(best_before)} best-before dates, so the proposal covers every batch from the "
            "earliest to the latest, including any dated between them."
        )
    optional: list[StoreAction] = []
    if store_actions and not pol.recall_store_actions(severity):
        optional, store_actions = store_actions, []
        considerations.append(
            f"A {severity} recall proposes no store action. {len(optional)} exposed stores are listed as optional; "
            "add the ones to pull."
        )
    return ProposedActions(
        kind="recall",
        severity=severity,
        targets=Targets(
            message_minutes=target.customers_messaged,
            shelf_minutes=target.shelves_clear,
        ),
        store_actions=store_actions,
        optional_store_actions=optional,
        checkout_block=pol.checkout_block(severity),
        message_orders=lineage.order_ids if lineage else [],
        supplier_notice=True,
        vendor_case=True,
        considerations=considerations,
        receipts=ev.receipts,
    )


def _propose_label(ev: EvidencePack, pol: Policy) -> ProposedActions:
    findings = [f for check in ev.checks for f in check.findings]
    rules = [pol.label_rule(f.rule) for f in findings]
    severity = pol.max_severity([pol.finding_severity(f) for f in findings])
    target = pol.labels.targets_minutes[severity]
    wants_hold = any("hold" in r.actions for r in rules)
    considerations: list[str] = []
    store_actions: list[StoreAction] = []
    if wants_hold:
        rows = [
            r
            for r in (ev.lineage.store_rows if ev.lineage else [])
            if (r.on_hand or 0) > 0
        ]
        if rows:
            store_actions = [
                StoreAction(
                    store_id=r.store_id,
                    batch_id=r.batch_id,
                    code=r.code,
                    action="hold",
                    qty_on_hand=r.on_hand or 0,
                    aisle=r.aisle,
                )
                for r in rows
            ]
        else:
            store_actions = [
                StoreAction(
                    store_id=c.store_id,
                    batch_id="unknown",
                    code="unreadable",
                    action="hold",
                    qty_on_hand=0,
                )
                for c in ev.checks
            ]
            considerations.append(
                "The lot could not be read, so the hold covers the reporting store only. Widen it?"
            )
    fixes: dict[str, ListingFix] = {}
    for f, rule in zip(findings, rules, strict=True):
        if "listing_check" in rule.actions:
            considerations.append(
                f"Check the online listing's {f.field} against the supplier spec: the pack differs on {f.value}."
            )
        if rule.listing is None:
            continue
        fix = fixes.setdefault(rule.listing.field, ListingFix(field=rule.listing.field))
        if rule.listing.op == "set_to":
            fix.set_to = f.value
        elif f.value not in getattr(fix, rule.listing.op):
            getattr(fix, rule.listing.op).append(f.value)
    return ProposedActions(
        kind="label",
        severity=severity,
        targets=Targets(
            shelf_minutes=target.holds_verified if store_actions else None,
            listing_minutes=target.listing_fixed if fixes else None,
        ),
        store_actions=store_actions,
        listing_fixes=list(fixes.values()),
        supplier_notice=any("supplier_notice" in r.actions for r in rules)
        or bool(store_actions),
        vendor_case=bool(store_actions),
        considerations=considerations,
        receipts=ev.receipts,
    )
