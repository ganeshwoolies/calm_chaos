"""Deterministic execution of a coordinator's decision. Called from the workflow, never from a model.

Every write is keyed on a deterministic id, so a resumed node that runs twice writes nothing twice.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from app import policy
from app.schemas import Decision, IncidentText, ProposedActions, ShelfVerdict
from app.store import LocalStore, now


def _slug(*parts: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", "-".join(parts)).strip("-")


def task_id(incident_id: str, store_id: str, batch_id: str) -> str:
    return _slug("task", incident_id, store_id, batch_id)


def _in_minutes(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


def _drop_needs_reason(proposed: ProposedActions, decision: Decision) -> bool:
    """Whether the decision drops a checkout block that policy lets a coordinator drop only with a reason."""
    pol = policy.current()
    return (
        decision.checkout_block is False
        and proposed.checkout_block
        and pol.recall.checkout_block_drop_needs_reason
        and pol.checkout_block(proposed.severity)
        and not (decision.reason or "").strip()
    )


_TEXTS = (
    ("title", "title"),
    ("narrative", "narrative"),
    ("vendor_case_body", "vendor case"),
    ("qa_alert", "QA alert"),
)


def check_decision(
    proposed: ProposedActions, draft: IncidentText, decision: Decision
) -> list[str]:
    """Why an approval cannot be carried out as asked, for the coordinator to fix before the run resumes.

    Stores outside the proposal are not problems: merge_decision ignores them with a note.
    """
    if decision.decision != "approve":
        return []
    problems = []
    if _drop_needs_reason(proposed, decision):
        problems.append(
            f"dropping the checkout block on a {proposed.severity} recall needs a reason"
        )
    edits = decision.text
    for field, label in _TEXTS:
        value = getattr(edits, field)
        if value is not None and not value.strip():
            problems.append(f"the {label} cannot be empty")
    if proposed.message_orders and draft.customer_message is not None:
        for field, label in (
            ("customer_message_subject", "customer message subject"),
            ("customer_message_body", "customer message"),
        ):
            value = getattr(edits, field)
            if value is not None and not value.strip():
                problems.append(
                    f"the {label} cannot be empty while orders are messaged"
                )
    if (
        proposed.supplier_notice
        and edits.supplier_notice is not None
        and not edits.supplier_notice.strip()
    ):
        problems.append("the supplier notice cannot be empty")
    return problems


def merge_decision(
    proposed: ProposedActions, draft: IncidentText, decision: Decision
) -> dict[str, Any]:
    """The approved version: the proposal and the draft with the coordinator's edits applied."""
    actions = proposed.model_copy(deep=True)
    notes: list[str] = []
    optional = {a.store_id: a for a in proposed.optional_store_actions}
    unknown_adds = sorted(set(decision.add_stores) - set(optional))
    if unknown_adds:
        notes.append(
            f"add ignored for stores not among the optional stores: {unknown_adds}"
        )
    added = [s for s in dict.fromkeys(decision.add_stores) if s in optional]
    actions.store_actions += [optional[s].model_copy() for s in added]
    actions.optional_store_actions = [
        a for a in actions.optional_store_actions if a.store_id not in added
    ]
    proposed_stores = {a.store_id for a in actions.store_actions}
    for edit, stores in (
        ("remove", decision.remove_stores),
        ("pull", decision.pull_stores),
    ):
        unknown = sorted(set(stores) - proposed_stores)
        if unknown:
            notes.append(f"{edit} ignored for stores not in the proposal: {unknown}")
    actions.store_actions = [
        a
        for a in actions.store_actions
        if a.store_id not in set(decision.remove_stores)
    ]
    for a in actions.store_actions:
        if a.store_id in set(decision.pull_stores):
            a.action = "pull"
    if (
        decision.checkout_block is not None
        and decision.checkout_block != actions.checkout_block
    ):
        if _drop_needs_reason(proposed, decision):
            notes.append(
                f"checkout block kept: dropping it on a {proposed.severity} recall needs a reason"
            )
        else:
            actions.checkout_block = decision.checkout_block
    text = draft.model_copy(deep=True)
    edits = decision.text
    for field in (*(f for f, _ in _TEXTS), "supplier_notice"):
        if getattr(edits, field) is not None:
            setattr(text, field, getattr(edits, field))
    if text.customer_message is not None:
        if edits.customer_message_subject is not None:
            text.customer_message.subject = edits.customer_message_subject
        if edits.customer_message_body is not None:
            text.customer_message.body = edits.customer_message_body
    return {
        "actions": actions.model_dump(mode="json"),
        "text": text.model_dump(mode="json"),
        "notes": notes,
    }


# Set by code on every incident card and outbound message, never by the model, so no screenshot reads as a real recall
# or a real message.
DEMO_NOTICE = (
    "A fictional retailer and fictional products. Nothing is sent and no stock moves."
)


def _demo(body: str) -> str:
    return f"{body}\n\n{DEMO_NOTICE}"


def _personalise(body: str, order_id: str) -> str:
    return _demo(f"{body}\n\nThis message is about your online order {order_id}.")


def approve_incident(
    store: LocalStore, incident_id: str, decision: Decision
) -> dict[str, Any]:
    with store.batch():
        return _approve(store, incident_id, decision)


def _approve(store: LocalStore, incident_id: str, decision: Decision) -> dict[str, Any]:
    incident = store.get_incident(incident_id)
    if incident["status"] != "awaiting_approval":
        return {
            "status": incident["status"],
            "already_executed": True,
            "open_tasks": len(store.open_tasks(incident_id)),
        }

    proposed = ProposedActions.model_validate(incident["proposed"])
    draft = IncidentText.model_validate(incident["draft"])
    approved = merge_decision(proposed, draft, decision)
    actions = ProposedActions.model_validate(approved["actions"])
    text = IncidentText.model_validate(approved["text"])
    edits = _edit_kinds(proposed, draft, actions, text)
    store.update_incident(
        incident_id,
        status="approved",
        approved=approved,
        approved_at=now(),
        approved_by=decision.actor,
        edits=edits,
    )
    store.append_audit(
        decision.actor,
        "approve_incident",
        "incident",
        incident_id,
        before={"proposed": incident["proposed"], "draft": incident["draft"]},
        after=approved,
    )
    if edits or approved["notes"]:
        store.append_audit(
            decision.actor,
            "edit_incident",
            "incident",
            incident_id,
            after={
                "edits": edits,
                "notes": approved["notes"],
                "reason": decision.reason,
            },
        )

    for a in actions.store_actions:
        _issue_task(
            store,
            {
                "task_id": task_id(incident_id, a.store_id, a.batch_id),
                "incident_id": incident_id,
                "store_id": a.store_id,
                "kind": a.action,
                "batch_id": a.batch_id,
                "code": a.code,
                "aisle": a.aisle,
                "qty_on_hand": a.qty_on_hand,
                "status": "open",
                "issued_at": now(),
                "due_at": _in_minutes(actions.targets.shelf_minutes),
                "verification": None,
            },
        )
    if text.customer_message:
        for order_id in actions.message_orders:
            store.queue_message(
                {
                    "message_id": _slug("msg", incident_id, order_id),
                    "incident_id": incident_id,
                    "audience": "customer",
                    "recipient_ref": order_id,
                    "subject": text.customer_message.subject,
                    "body": _personalise(text.customer_message.body, order_id),
                }
            )
    if actions.checkout_block:
        store.create_pos_block_request(
            {
                "request_id": _slug("pos", incident_id),
                "incident_id": incident_id,
                "product_id": incident["product_id"],
                "codes": sorted({a.code for a in actions.store_actions}),
                "requested_at": now(),
                "status": "requested",
            }
        )
    for fix in actions.listing_fixes:
        change = {
            "change_id": _slug("lst", incident_id, fix.field),
            "incident_id": incident_id,
            "product_id": incident["product_id"],
            "change": fix.model_dump(mode="json"),
            "applied_at": now(),
            "applied_by": decision.actor,
        }
        store.apply_listing_change(change)
        store.append_audit(
            decision.actor,
            "apply_listing_change",
            "listing_change",
            change["change_id"],
            after={"product_id": change["product_id"], "change": change["change"]},
        )
    if actions.supplier_notice and text.supplier_notice:
        store.queue_message(
            {
                "message_id": _slug("msg", incident_id, "supplier"),
                "incident_id": incident_id,
                "audience": "supplier",
                "recipient_ref": incident["supplier_id"],
                "subject": text.title,
                "body": _demo(text.supplier_notice),
            }
        )
    store.queue_message(
        {
            "message_id": _slug("msg", incident_id, "qa"),
            "incident_id": incident_id,
            "audience": "qa",
            "recipient_ref": "qa",
            "subject": text.title,
            "body": _demo(text.qa_alert),
        }
    )
    if actions.vendor_case:
        store.create_vendor_case(
            {
                "case_id": _slug("case", incident_id),
                "incident_id": incident_id,
                "supplier_id": incident["supplier_id"],
                "body": text.vendor_case_body,
                "status": "open",
                "created_at": now(),
            }
        )
    _send_queued(store, incident_id)

    open_tasks = store.open_tasks(incident_id)
    store.update_incident(
        incident_id,
        status="verifying" if open_tasks else "executed",
        executed_at=now(),
    )
    return {
        "status": "verifying" if open_tasks else "executed",
        "open_tasks": len(open_tasks),
        "customer_messages": sum(
            1
            for m in store.outbox.values()
            if m["incident_id"] == incident_id and m["audience"] == "customer"
        ),
        "notes": approved["notes"],
    }


def _issue_task(store: LocalStore, task: dict[str, Any]) -> None:
    store.upsert_task(task)
    store.append_audit(
        "desk",
        "issue_task",
        "task",
        task["task_id"],
        after={
            k: task[k]
            for k in ("store_id", "kind", "code", "due_at", "reissue_of")
            if task.get(k) is not None
        },
    )


def _send_queued(store: LocalStore, incident_id: str) -> None:
    """Simulated sender: nothing leaves the process."""
    for message in list(store.outbox.values()):
        if message["incident_id"] == incident_id and message["status"] == "queued":
            store.mark_sent(message["message_id"])
            store.append_audit(
                "desk",
                "send_message",
                "message",
                message["message_id"],
                after={
                    "audience": message["audience"],
                    "recipient_ref": message["recipient_ref"],
                },
            )


def dismiss_incident(
    store: LocalStore, incident_id: str, decision: Decision
) -> dict[str, Any]:
    with store.batch():
        return _dismiss(store, incident_id, decision)


def _dismiss(store: LocalStore, incident_id: str, decision: Decision) -> dict[str, Any]:
    incident = store.get_incident(incident_id)
    if incident["status"] != "awaiting_approval":
        return {"status": incident["status"], "already_executed": True}
    until = (
        datetime.now(UTC)
        + timedelta(hours=policy.current().handling.dismiss_suppress_hours)
    ).isoformat()
    store.suppress(incident["candidate_id"], until)
    incident = store.update_incident(
        incident_id,
        status="dismissed",
        dismissed_by=decision.actor,
        dismiss_reason=decision.reason,
        dismissed_at=now(),
    )
    store.append_audit(
        decision.actor,
        "dismiss_incident",
        "incident",
        incident_id,
        after={"reason": decision.reason},
    )
    subject = f"{incident['kind']} incident on {_product(incident)} for {incident['hazard_type']}"
    reason = decision.reason or "no reason recorded"
    facts = [
        _fact(
            {"product_id": incident["product_id"]},
            "product_incident_history",
            f"A {subject} was dismissed on {incident['dismissed_at'][:10]}: {reason}.",
        ),
        _fact(
            {"supplier_id": incident["supplier_id"]},
            "supplier_quality_history",
            f"Supplier {_supplier(incident)}: a {subject} was dismissed on "
            f"{incident['dismissed_at'][:10]}: {reason}.",
        ),
    ]
    return {"status": "dismissed", "suppressed_until": until, "memory_facts": facts}


def record_verification(
    store: LocalStore, current_task_id: str, verdict: ShelfVerdict
) -> dict[str, Any]:
    with store.batch():
        return _verify(store, current_task_id, verdict)


def _verify(
    store: LocalStore, current_task_id: str, verdict: ShelfVerdict
) -> dict[str, Any]:
    task = store.tasks[current_task_id]
    if task["status"] != "open":
        return {"status": task["status"], "already_recorded": True}
    task = store.update_task(
        current_task_id,
        status=verdict.verdict,
        verification=verdict.model_dump(mode="json"),
        verified_at=now(),
    )
    reissued = None
    if verdict.verdict in ("not_clear", "retake"):
        attempt = (
            sum(
                1
                for t in store.tasks.values()
                if t.get("reissue_of") == current_task_id
            )
            + 1
        )
        reissued = {
            **task,
            "task_id": f"{current_task_id}-r{attempt}",
            "status": "open",
            "verification": None,
            "verified_at": None,
            "issued_at": now(),
            "reissue_of": current_task_id,
        }
        _issue_task(store, reissued)
    store.append_audit(
        "store",
        "record_verification",
        "task",
        current_task_id,
        after=verdict.model_dump(mode="json"),
    )
    return {
        "status": verdict.verdict,
        "reissued_task_id": reissued["task_id"] if reissued else None,
    }


def _edit_kinds(
    proposed: ProposedActions,
    draft: IncidentText,
    actions: ProposedActions,
    text: IncidentText,
) -> list[str]:
    """What the coordinator changed before approving, in words reusable across incidents."""
    edits = []
    proposed_ids = {a.store_id for a in proposed.store_actions}
    approved_ids = {a.store_id for a in actions.store_actions}
    if proposed_ids - approved_ids:
        edits.append("removed stores from the proposal")
    if approved_ids - proposed_ids:
        edits.append("added optional stores to the proposal")
    held = {a.store_id for a in proposed.store_actions if a.action == "hold"}
    if any(a.action == "pull" and a.store_id in held for a in actions.store_actions):
        edits.append("changed holds to pulls")
    if actions.checkout_block != proposed.checkout_block:
        edits.append(
            "dropped the checkout block"
            if proposed.checkout_block
            else "added a checkout block"
        )
    for field, label in (
        ("title", "title"),
        ("narrative", "narrative"),
        ("supplier_notice", "supplier notice"),
        ("vendor_case_body", "vendor case"),
        ("qa_alert", "QA alert"),
    ):
        if getattr(text, field) != getattr(draft, field):
            edits.append(f"edited the {label}")
    if text.customer_message != draft.customer_message:
        edits.append("edited the customer message")
    return edits


def _fact(scope: dict[str, str], topic: str, fact: str) -> dict[str, Any]:
    return {"scope": scope, "topic": topic, "fact": fact}


def _product(incident: dict[str, Any]) -> str:
    return f"{incident.get('product_name') or incident['product_id']} ({incident['product_id']})"


def _supplier(incident: dict[str, Any]) -> str:
    return f"{incident.get('supplier_name') or incident['supplier_id']} ({incident['supplier_id']})"


def _minutes_after(start: str, end: str | None) -> int | None:
    if end is None:
        return None
    delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    return round(delta.total_seconds() / 60)


def close_incident(store: LocalStore, incident_id: str) -> dict[str, Any]:
    incident = store.update_incident(incident_id, status="closed", closed_at=now())
    return {"status": "closed", "memory_facts": observation_facts(store, incident)}


def observation_facts(store: LocalStore, incident: dict[str, Any]) -> list[dict]:
    """Facts for Memory Bank, one scope and topic each (design section 11).

    Built only from executor records: never from notice text, pack text or model output.
    """
    actions = ProposedActions.model_validate(incident["approved"]["actions"])
    approved_at = incident["approved_at"]
    tasks = [
        t for t in store.tasks.values() if t["incident_id"] == incident["incident_id"]
    ]
    first_issue = [t for t in tasks if not t.get("reissue_of")]
    cleared = [t["verified_at"] for t in tasks if t["status"] == "verified_clear"]
    codes = sorted({a.code for a in actions.store_actions})
    on_codes = f" on {', '.join(codes)}" if codes else ""
    orders = len(actions.message_orders)
    facts = [
        _fact(
            {"supplier_id": incident["supplier_id"]},
            "supplier_quality_history",
            f"Supplier {_supplier(incident)}: {incident['kind']} incident for {incident['hazard_type']} on "
            f"{_product(incident)}{on_codes}, severity {incident['severity']}, approved {approved_at[:10]}; "
            f"{len(first_issue)} stores, {orders} online orders.",
        )
    ]
    if first_issue:
        verb = "pulled" if first_issue[0]["kind"] == "pull" else "held"
        shelf = _minutes_after(approved_at, max(cleared) if cleared else None)
        target = actions.targets.shelf_minutes
        facts.append(
            _fact(
                {"product_id": incident["product_id"]},
                "product_incident_history",
                f"{_product(incident)} had a {incident['kind']} incident for {incident['hazard_type']}{on_codes}; "
                f"{len(first_issue)} stores {verb} it and every shelf was verified clear {shelf} minutes after "
                f"approval"
                + (f" against a {target}-minute target." if target else "."),
            )
        )
    else:
        facts.append(
            _fact(
                {"product_id": incident["product_id"]},
                "product_incident_history",
                f"{_product(incident)} had a {incident['kind']} incident for {incident['hazard_type']} "
                f"approved {approved_at[:10]}, with listing fixes and no store tasks.",
            )
        )
    for task in first_issue:
        root = task["task_id"]
        chain = [
            t
            for t in tasks
            if t["task_id"] == root or t["task_id"].startswith(f"{root}-r")
        ]
        clear = [t["verified_at"] for t in chain if t["status"] == "verified_clear"]
        minutes = _minutes_after(approved_at, max(clear) if clear else None)
        reissues = len(chain) - 1
        facts.append(
            _fact(
                {"store_id": task["store_id"]},
                "store_execution_pattern",
                f"Store {task['store_id']} verified a {task['kind']} task {minutes} minutes after approval"
                + (f" in aisle {task['aisle']}" if task.get("aisle") else "")
                + (
                    f" after {reissues} repeat photo check{'s' if reissues > 1 else ''}."
                    if reissues
                    else " at the first photo check."
                ),
            )
        )
    # One coordinator's one-off edit is not desk practice: an edit becomes a fact once two approved incidents share it.
    for edit in incident.get("edits", []):
        same = sum(
            1
            for other in store.incidents.values()
            if other["kind"] == incident["kind"] and edit in other.get("edits", [])
        )
        if same >= 2:
            facts.append(
                _fact(
                    {"playbook": "psd"},
                    "coordinator_playbook",
                    f"Coordinators {edit} before approving {incident['kind']} incidents ({same} incidents so far).",
                )
            )
    return facts
