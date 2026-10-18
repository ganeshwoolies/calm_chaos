import pytest
from fastapi.testclient import TestClient

from app import actions, executor
from app import fast_api_app as agents_app
from app.store import incident_id_for, store


@pytest.fixture
def local() -> TestClient:
    return TestClient(agents_app.app, client=("127.0.0.1", 50000))


@pytest.fixture
def paused(yoghurt, recall_draft, pol) -> str:
    """An incident drafted and paused for approval, as the workflow leaves it."""
    incident_id = incident_id_for(yoghurt.candidate_id)
    store.begin_drafting(
        {
            "incident_id": incident_id,
            "candidate_id": yoghurt.candidate_id,
            "kind": "recall",
            "product_id": yoghurt.product.product_id,
            "supplier_id": yoghurt.product.supplier_id,
            "interrupt_id": f"approve:{incident_id}",
        }
    )
    store.update_incident(
        incident_id,
        status="awaiting_approval",
        draft=recall_draft.model_dump(mode="json"),
        proposed=actions.propose(yoghurt, pol).model_dump(mode="json"),
    )
    return incident_id


def test_the_desk_lists_an_incident_with_its_card(local, paused) -> None:
    (view,) = local.get("/desk/incidents").json()
    assert view["incident_id"] == paused and view["status"] == "awaiting_approval"
    assert view["severity"] == "critical" and view["title"].startswith("Morrowdale")
    assert view["card"].startswith(executor.DEMO_NOTICE)
    assert view["tasks"] == [] and view["messages"] == {}


def test_the_card_is_also_served_in_parts(local, paused) -> None:
    (view,) = local.get("/desk/incidents").json()
    detail = view["detail"]
    assert detail["basis"] == "proposed"
    assert detail["narrative"] == (
        "The regulator recalled batch B2026-091. 14 stores hold 212 units."
    )
    assert detail["actions"][0].startswith("pull at 14 stores (212 units on hand)")
    assert "checkout block: yes" in detail["actions"]
    assert all(f"- {line}" in view["card"] for line in detail["actions"])
    assert detail["considerations"] == []
    assert detail["evidence"][0].startswith("14 stores hold the batch")
    assert detail["receipts"] == ["rcpt-fixture-yoghurt-0001"]
    assert detail["customer_message"] == {
        "subject": "Recall: Morrowdale Vanilla Yoghurt 1kg",
        "body": "Do not eat it.",
    }


def test_an_approved_incident_is_shown_as_approved(local, paused) -> None:
    incident = store.get_incident(paused)
    store.update_incident(
        paused,
        status="closed",
        approved={
            "text": {**incident["draft"], "narrative": "Approved as edited."},
            "actions": {**incident["proposed"], "checkout_block": False},
            "notes": [],
        },
    )
    (view,) = local.get("/desk/incidents").json()
    assert view["detail"]["basis"] == "approved"
    assert view["detail"]["narrative"] == "Approved as edited."
    assert "checkout block: no" in view["detail"]["actions"]
    assert "checkout block: no" in view["card"] and view["editable"] is None


def test_a_paused_incident_offers_its_proposal_and_texts_to_edit(local, paused) -> None:
    (view,) = local.get("/desk/incidents").json()
    editable = view["editable"]
    assert len(editable["store_actions"]) == 14 and editable["orders_to_message"] == 37
    assert set(editable["store_actions"][0]) == {
        "store_id",
        "batch_id",
        "code",
        "action",
        "qty_on_hand",
        "aisle",
    }
    assert editable["checkout_block"] is True
    assert editable["checkout_block_drop_needs_reason"] is True
    assert editable["text"]["customer_message_body"] == "Do not eat it."
    assert view["approval"] is None


def test_an_edit_policy_refuses_is_sent_back_before_the_run_resumes(
    local, paused, monkeypatch
) -> None:
    async def resume(*args, **kwargs):
        pytest.fail("the paused run was resumed")

    monkeypatch.setattr(agents_app, "_resume", resume)
    r = local.post(
        f"/desk/incidents/{paused}/decision",
        json={
            "decision": "approve",
            "checkout_block": False,
            "text": {"qa_alert": " "},
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "Dropping the checkout block on a critical recall needs a reason; "
        "the QA alert cannot be empty."
    )
    assert store.get_incident(paused)["status"] == "awaiting_approval"


def test_only_this_machine_may_call_without_an_audience() -> None:
    remote = TestClient(agents_app.app, client=("203.0.113.9", 50000))
    assert remote.get("/desk/incidents").status_code == 403


def test_a_decision_needs_an_incident_awaiting_approval(local, paused) -> None:
    missing = local.post(
        "/desk/incidents/inc-none/decision", json={"decision": "approve"}
    )
    assert missing.status_code == 404
    store.update_incident(paused, status="closed")
    closed = local.post(
        f"/desk/incidents/{paused}/decision", json={"decision": "approve"}
    )
    assert closed.status_code == 409 and "closed" in closed.text


def test_a_dismissal_needs_a_reason(local, paused) -> None:
    for body in ({"decision": "dismiss"}, {"decision": "dismiss", "reason": "  "}):
        assert (
            local.post(f"/desk/incidents/{paused}/decision", json=body).status_code
            == 422
        )
    assert store.get_incident(paused)["status"] == "awaiting_approval"


def test_a_memory_retry_reports_what_it_generated(local, monkeypatch) -> None:
    asked = []

    def retry(store, limit):
        asked.append(limit)
        return [
            {"status": "generated", "error": None},
            {"status": "failed", "error": "RuntimeError: unavailable"},
        ]

    monkeypatch.setattr(agents_app.learn, "retry", retry)
    r = local.post("/desk/memory/retry?limit=2")
    assert r.status_code == 200 and asked == [2]
    assert r.json()["retried"] == 2 and r.json()["generated"] == 1
    assert r.json()["errors"] == ["RuntimeError: unavailable"]
    assert local.post("/desk/memory/retry?limit=0").status_code == 422


def test_a_verdict_needs_an_open_task(local) -> None:
    assert (
        local.post(
            "/desk/tasks/t-none/verdict", json={"verdict": "verified_clear"}
        ).status_code
        == 404
    )
