from app import executor, policy
from app.actions import propose
from app.schemas import Decision, ShelfVerdict
from app.store import incident_id_for, store


def _awaiting(evidence, draft) -> str:
    incident_id = incident_id_for(evidence.candidate_id)
    store.create_incident(
        {
            "incident_id": incident_id,
            "candidate_id": evidence.candidate_id,
            "kind": evidence.kind,
            "product_id": evidence.product.product_id,
            "product_name": evidence.product.name,
            "supplier_id": evidence.product.supplier_id,
            "supplier_name": evidence.product.supplier_name,
            "hazard_type": evidence.hazard_type,
            "severity": "critical",
            "status": "awaiting_approval",
            "proposed": propose(evidence, policy.current()).model_dump(mode="json"),
            "draft": draft.model_dump(mode="json"),
        }
    )
    return incident_id


def _messages(incident_id: str, audience: str) -> list:
    return [
        m
        for m in store.outbox.values()
        if m["incident_id"] == incident_id and m["audience"] == audience
    ]


def test_approve_executes_every_action(yoghurt, recall_draft) -> None:
    incident_id = _awaiting(yoghurt, recall_draft)
    result = executor.approve_incident(
        store, incident_id, Decision(decision="approve", actor="coordinator-1")
    )
    assert result["status"] == "verifying" and result["open_tasks"] == 14
    customers = _messages(incident_id, "customer")
    assert len(customers) == 37 and all(m["status"] == "sent" for m in customers)
    assert all(
        m["recipient_ref"] in m["body"] for m in customers
    )  # personalised by code, not the model
    assert (
        len(_messages(incident_id, "supplier")) == 1
        and len(_messages(incident_id, "qa")) == 1
    )
    assert len(store.pos_block_requests) == 1 and len(store.vendor_cases) == 1
    # The approval first, then what the executor did on it, one row per object.
    actions = [row["action"] for row in store.audit]
    assert actions[0] == "approve_incident"
    assert actions.count("issue_task") == 14 and actions.count("send_message") == 39
    assert "edit_incident" not in actions
    assert all(m["created_at"] <= m["sent_at"] for m in store.outbox.values())
    incident = store.get_incident(incident_id)
    assert incident["approved_at"] <= incident["executed_at"]
    assert incident["edits"] == []


def test_second_approval_writes_nothing(yoghurt, recall_draft) -> None:
    incident_id = _awaiting(yoghurt, recall_draft)
    executor.approve_incident(store, incident_id, Decision(decision="approve"))
    counts = (len(store.tasks), len(store.outbox), len(store.audit))
    again = executor.approve_incident(store, incident_id, Decision(decision="approve"))
    assert again["already_executed"] is True
    assert (len(store.tasks), len(store.outbox), len(store.audit)) == counts


def test_coordinator_edits_are_applied(yoghurt, recall_draft) -> None:
    incident_id = _awaiting(yoghurt, recall_draft)
    decision = Decision(
        decision="approve", remove_stores=["S004"], text={"narrative": "Edited."}
    )
    executor.approve_incident(store, incident_id, decision)
    assert len(store.open_tasks(incident_id)) == 13
    assert store.get_incident(incident_id)["approved"]["text"]["narrative"] == "Edited."
    assert store.get_incident(incident_id)["edits"] == [
        "removed stores from the proposal",
        "edited the narrative",
    ]


def test_holds_can_become_pulls(dinosaur, recall_draft) -> None:
    draft = recall_draft.model_copy(update={"customer_message": None})
    incident_id = _awaiting(dinosaur, draft)
    held = [
        a["store_id"]
        for a in store.get_incident(incident_id)["proposed"]["store_actions"]
    ]
    result = executor.approve_incident(
        store,
        incident_id,
        Decision(decision="approve", pull_stores=[held[0], "S999"]),
    )
    kinds = {t["store_id"]: t["kind"] for t in store.open_tasks(incident_id)}
    assert kinds[held[0]] == "pull"
    assert all(kinds[s] == "hold" for s in held[1:])
    assert result["notes"] == ["pull ignored for stores not in the proposal: ['S999']"]
    assert "changed holds to pulls" in store.get_incident(incident_id)["edits"]


def test_checkout_block_on_critical_recall_needs_a_reason(
    yoghurt, recall_draft
) -> None:
    incident_id = _awaiting(yoghurt, recall_draft)
    result = executor.approve_incident(
        store, incident_id, Decision(decision="approve", checkout_block=False)
    )
    assert len(store.pos_block_requests) == 1
    assert result["notes"] == [
        "checkout block kept: dropping it on a critical recall needs a reason"
    ]

    store.reset()
    incident_id = _awaiting(yoghurt, recall_draft)
    executor.approve_incident(
        store,
        incident_id,
        Decision(
            decision="approve", checkout_block=False, reason="Supplier confirmed scope"
        ),
    )
    assert store.pos_block_requests == {}


def test_an_edited_approval_is_audited_with_what_changed(yoghurt, recall_draft) -> None:
    incident_id = _awaiting(yoghurt, recall_draft)
    executor.approve_incident(
        store,
        incident_id,
        Decision(
            decision="approve",
            remove_stores=["S004", "S999"],
            checkout_block=False,
            reason="Supplier confirmed scope",
        ),
    )
    assert [row["action"] for row in store.audit][:2] == [
        "approve_incident",
        "edit_incident",
    ]
    (edit,) = [row for row in store.audit if row["action"] == "edit_incident"]
    assert edit["after"] == {
        "edits": ["removed stores from the proposal", "dropped the checkout block"],
        "notes": ["remove ignored for stores not in the proposal: ['S999']"],
        "reason": "Supplier confirmed scope",
    }


def test_a_listing_fix_is_audited(muesli, recall_draft) -> None:
    draft = recall_draft.model_copy(update={"customer_message": None})
    incident_id = _awaiting(muesli, draft)
    executor.approve_incident(store, incident_id, Decision(decision="approve"))
    (change,) = [row for row in store.audit if row["action"] == "apply_listing_change"]
    assert change["object_id"] in store.listing_changes
    assert change["after"]["change"]["field"] == "allergens"


def test_check_decision_names_what_to_fix(yoghurt, recall_draft, pol) -> None:
    proposed = propose(yoghurt, pol)
    with_reason = Decision(
        decision="approve", checkout_block=False, reason="Supplier confirmed scope"
    )
    assert executor.check_decision(proposed, recall_draft, with_reason) == []
    broken = Decision(
        decision="approve",
        checkout_block=False,
        text={"customer_message_body": " ", "title": ""},
    )
    assert executor.check_decision(proposed, recall_draft, broken) == [
        "dropping the checkout block on a critical recall needs a reason",
        "the title cannot be empty",
        "the customer message cannot be empty while orders are messaged",
    ]
    dismissal = Decision(decision="dismiss", reason="Not our product")
    assert executor.check_decision(proposed, recall_draft, dismissal) == []


def test_dismissal_suppresses_the_candidate(yoghurt, recall_draft) -> None:
    incident_id = _awaiting(yoghurt, recall_draft)
    result = executor.dismiss_incident(
        store, incident_id, Decision(decision="dismiss", reason="Not our product")
    )
    assert result["status"] == "dismissed"
    assert store.is_suppressed(yoghurt.candidate_id)
    assert store.tasks == {} and store.outbox == {}
    assert store.get_incident(incident_id)["dismissed_at"]
    assert {f["topic"] for f in result["memory_facts"]} == {
        "product_incident_history",
        "supplier_quality_history",
    }
    assert all("Not our product" in f["fact"] for f in result["memory_facts"])


def test_not_clear_reissues_the_task(dinosaur, recall_draft) -> None:
    draft = recall_draft.model_copy(update={"customer_message": None})
    incident_id = _awaiting(dinosaur, draft)
    executor.approve_incident(store, incident_id, Decision(decision="approve"))
    first = store.open_tasks(incident_id)[0]["task_id"]
    result = executor.record_verification(
        store, first, ShelfVerdict(verdict="not_clear")
    )
    assert result["reissued_task_id"] == f"{first}-r1"
    assert len(store.open_tasks(incident_id)) == 11
    (reissue,) = [
        row
        for row in store.audit
        if row["action"] == "issue_task" and row["object_id"] == f"{first}-r1"
    ]
    assert reissue["after"]["reissue_of"] == first
    for task in store.open_tasks(incident_id):
        executor.record_verification(
            store, task["task_id"], ShelfVerdict(verdict="verified_clear")
        )
    assert store.open_tasks(incident_id) == []
    closed = executor.close_incident(store, incident_id)
    assert closed["status"] == "closed"
    facts = closed["memory_facts"]
    by_topic = {}
    for f in facts:
        by_topic.setdefault(f["topic"], []).append(f)
    assert len(by_topic["supplier_quality_history"]) == 1
    assert len(by_topic["product_incident_history"]) == 1
    stores = by_topic["store_execution_pattern"]
    assert len(stores) == 11 and all("store_id" in f["scope"] for f in stores)
    assert sum("after 1 repeat photo check." in f["fact"] for f in stores) == 1
    assert "coordinator_playbook" not in by_topic


def test_a_repeated_coordinator_edit_becomes_a_playbook_fact(
    dinosaur, recall_draft
) -> None:
    draft = recall_draft.model_copy(update={"customer_message": None})
    for n in (1, 2):
        incident_id = _awaiting(dinosaur, draft)
        executor.approve_incident(
            store,
            incident_id,
            Decision(decision="approve", text={"qa_alert": f"Rewritten {n}."}),
        )
        for task in store.open_tasks(incident_id):
            executor.record_verification(
                store, task["task_id"], ShelfVerdict(verdict="verified_clear")
            )
        facts = executor.close_incident(store, incident_id)["memory_facts"]
        playbook = [f for f in facts if f["topic"] == "coordinator_playbook"]
        if n == 1:
            assert playbook == []
            # A second incident of the same kind, with the same edit.
            store.incidents[incident_id + "-earlier"] = store.incidents.pop(incident_id)
            store.tasks.clear()
        else:
            assert len(playbook) == 1 and "edited the QA alert" in playbook[0]["fact"]


def test_coordinator_adds_optional_stores_to_a_low_recall(
    yoghurt, recall_draft
) -> None:
    yoghurt.hazard_type = "quality_only"
    incident_id = _awaiting(yoghurt, recall_draft)
    optional = store.get_incident(incident_id)["proposed"]["optional_store_actions"]
    picked = [optional[0]["store_id"], optional[1]["store_id"]]
    decision = Decision(decision="approve", add_stores=[*picked, "S999"])
    executor.approve_incident(store, incident_id, decision)
    tasks = store.open_tasks(incident_id)
    assert sorted(t["store_id"] for t in tasks) == sorted(picked)
    assert all(t["due_at"] is None for t in tasks)
    incident = store.get_incident(incident_id)
    assert "added optional stores to the proposal" in incident["edits"]
    assert any("S999" in n for n in incident["approved"]["notes"])
