"""The incident workflow end to end, in process: Pub/Sub push, approval pause, resume, execution, verification.

Calls Gemini for the drafting step (needs Application Default Credentials). Assertions are on structure and state,
never on the model's wording.
"""

import base64
import json

import httpx
import pytest
import pytest_asyncio
from google.cloud import bigquery

from app import bq, evidence, executor, nodes
from app.fast_api_app import DESK_USER_ID
from app.fast_api_app import app as fastapi_app
from app.store import incident_id_for, store
from tests.knowledge_copy import copy_bundle, edit_concept


def _subscription() -> str:
    return f"projects/{bq.client().project}/subscriptions/psd-candidates-agent"


def _push(candidate_id: str, kind: str, message_id: str) -> dict:
    data = base64.b64encode(
        json.dumps({"candidate_id": candidate_id, "kind": kind}).encode()
    ).decode()
    return {
        "message": {"data": data, "messageId": message_id, "attributes": {}},
        "subscription": _subscription(),
    }


def _resume(incident: dict, interrupt_id: str, response: dict) -> dict:
    return {
        "appName": "app",
        "userId": incident["user_id"],
        "sessionId": incident["session_id"],
        "newMessage": {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "id": interrupt_id,
                        "name": "adk_request_input",
                        "response": {"result": json.dumps(response)},
                    }
                }
            ],
        },
    }


@pytest_asyncio.fixture
async def client():
    store.reset()
    transport = httpx.ASGITransport(app=fastapi_app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1", timeout=300
    ) as c:
        yield c
    store.reset()


async def _trigger(
    client: httpx.AsyncClient, candidate_id: str, kind: str, message_id: str
) -> dict:
    resp = await client.post(
        "/trigger/candidates", json=_push(candidate_id, kind, message_id)
    )
    assert resp.status_code == 200, resp.text
    incident = store.find_incident_for_candidate(candidate_id)
    assert incident is not None and incident["status"] == "awaiting_approval", incident
    # One session per incident, named by the incident id and owned by the desk.
    assert incident["session_id"] == incident["incident_id"]
    assert incident["user_id"] == DESK_USER_ID
    return incident


async def _session_events(client: httpx.AsyncClient, incident: dict) -> list:
    resp = await client.get(
        f"/apps/app/users/{incident['user_id']}/sessions/{incident['session_id']}"
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["events"]


async def _session_state(client: httpx.AsyncClient, incident: dict) -> dict:
    resp = await client.get(
        f"/apps/app/users/{incident['user_id']}/sessions/{incident['session_id']}"
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["state"]


@pytest.mark.asyncio
async def test_recall_pause_resume_execute_verify(client) -> None:
    incident = await _trigger(client, "recall:yoghurt_listeria", "recall", "m-1")
    interrupt_id = f"approve:{incident['incident_id']}"
    assert incident["interrupt_id"] == interrupt_id

    # The pause is an adk_request_input function call whose id is our interrupt_id: psd-api needs no event scan.
    calls = [
        part["functionCall"]
        for event in await _session_events(client, incident)
        for part in (event.get("content") or {}).get("parts") or []
        if part.get("functionCall", {}).get("name") == "adk_request_input"
    ]
    assert [c["id"] for c in calls] == [interrupt_id]

    # The draft records the knowledge it ran with, and the microbial playbook was shown to the drafter.
    state = await _session_state(client, incident)
    assert incident["knowledge_version"] == state["knowledge_version"]
    # The figures are attested: the lineage receipt is a passing row in the attestations table.
    receipt_id = state["evidence"]["lineage"]["receipt_id"]
    if evidence.source() == "bigquery":
        recorded = bq.rows(
            "SELECT attested FROM attestations WHERE receipt_id = @r",
            [bigquery.ScalarQueryParameter("r", "STRING", receipt_id)],
        )
        assert recorded == [{"attested": True}]
    assert "/playbooks/microbial.md" in state["knowledge_paths"]
    assert set(incident["draft"]["sources_used"]) <= set(state["knowledge_paths"])

    resp = await client.post(
        "/run",
        json=_resume(
            incident, interrupt_id, {"decision": "approve", "actor": "coordinator-1"}
        ),
    )
    assert resp.status_code == 200, resp.text
    incident_id = incident["incident_id"]
    assert store.get_incident(incident_id)["status"] == "verifying"
    assert len(store.open_tasks(incident_id)) == 14
    customer = [
        m
        for m in store.outbox.values()
        if m["incident_id"] == incident_id and m["audience"] == "customer"
    ]
    assert len(customer) == 37 and all(m["status"] == "sent" for m in customer)

    # First shelf photo still shows the product: the task is reissued, then every task verifies clear.
    first = True
    while store.open_tasks(incident_id):
        task_id = store.open_tasks(incident_id)[0]["task_id"]
        verdict = "not_clear" if first else "verified_clear"
        first = False
        resp = await client.post(
            "/run", json=_resume(incident, f"verify:{task_id}", {"verdict": verdict})
        )
        assert resp.status_code == 200, resp.text
    assert store.get_incident(incident_id)["status"] == "closed"
    assert any(t.get("reissue_of") for t in store.tasks.values())


@pytest.mark.asyncio
async def test_dismissal_and_redelivery(client) -> None:
    incident = await _trigger(client, "label:P31007:4c19e2", "label", "m-2")
    interrupt_id = incident["interrupt_id"]
    reply = {
        "decision": "dismiss",
        "actor": "coordinator-1",
        "reason": "Listing already corrected",
    }
    resp = await client.post("/run", json=_resume(incident, interrupt_id, reply))
    assert resp.status_code == 200, resp.text
    assert store.get_incident(incident["incident_id"])["status"] == "dismissed"

    # The same candidate pushed again is suppressed: no new incident, no new pause.
    resp = await client.post(
        "/trigger/candidates", json=_push("label:P31007:4c19e2", "label", "m-3")
    )
    assert resp.status_code == 200 and resp.json()["status"] == "suppressed"
    assert len(store.incidents) == 1
    assert store.get_incident(incident["incident_id"])["status"] == "dismissed"


@pytest.mark.asyncio
async def test_duplicate_delivery_is_acknowledged_without_a_run(client) -> None:
    incident = await _trigger(client, "label:P50211:7a0d3f", "label", "m-4")
    before = len(await _session_events(client, incident))
    resp = await client.post(
        "/trigger/candidates", json=_push("label:P50211:7a0d3f", "label", "m-4")
    )
    assert resp.status_code == 200 and resp.json()["status"] == "duplicate"
    assert len(store.incidents) == 1
    # The paused session is untouched: nothing was appended after the approval pause.
    assert len(await _session_events(client, incident)) == before


@pytest.mark.asyncio
async def test_failed_run_is_redrafted_on_redelivery(client, monkeypatch) -> None:
    candidate_id = "label:P31007:4c19e2"
    incident_id = incident_id_for(candidate_id)
    monkeypatch.setattr(nodes, "REDRAFT_ATTEMPTS", 0)
    monkeypatch.setattr(nodes, "inconsistencies", lambda *a: ["forced for the test"])
    resp = await client.post(
        "/trigger/candidates", json=_push(candidate_id, "label", "m-5")
    )
    assert resp.status_code == 500  # Pub/Sub redelivers
    failed = store.get_incident(incident_id)
    assert failed["status"] == "failed"
    assert failed["failure"]["node"] == "validate_and_persist"

    monkeypatch.undo()
    incident = await _trigger(client, candidate_id, "label", "m-5")
    assert incident["attempt"] == 2
    assert incident["history"][-1]["status"] == "failed"
    assert any(a["action"] == "redraft_incident" for a in store.audit)


@pytest.mark.asyncio
async def test_a_message_that_is_not_a_candidate_is_rejected(client) -> None:
    data = base64.b64encode(b'{"hello": "world"}').decode()
    resp = await client.post(
        "/trigger/candidates",
        json={
            "message": {"data": data, "messageId": "m-6"},
            "subscription": _subscription(),
        },
    )
    assert resp.status_code == 400
    assert store.incidents == {}


@pytest.mark.asyncio
async def test_unverified_playbook_is_left_out_of_the_prompt(
    client, tmp_path, monkeypatch
) -> None:
    root = copy_bundle(tmp_path / "knowledge")
    edit_concept(root, "/playbooks/microbial.md", status="draft")
    monkeypatch.setenv("PSD_KNOWLEDGE_DIR", str(root))
    incident = await _trigger(client, "recall:yoghurt_listeria", "recall", "m-6")
    state = await _session_state(client, incident)
    assert "/playbooks/microbial.md" not in state["knowledge_paths"]
    assert state["knowledge_block"].startswith("none")


@pytest.mark.asyncio
async def test_stale_policy_stops_the_run(client, tmp_path, monkeypatch) -> None:
    root = copy_bundle(tmp_path / "knowledge")
    edit_concept(root, "/policy/recall-response.md", stale_after="2026-01-01T00:00:00Z")
    monkeypatch.setenv("PSD_KNOWLEDGE_DIR", str(root))
    candidate_id = "recall:yoghurt_listeria"
    resp = await client.post(
        "/trigger/candidates", json=_push(candidate_id, "recall", "m-7")
    )
    assert (
        resp.status_code == 500
    )  # Pub/Sub redelivers; after the dead-letter limit it is parked
    failed = store.get_incident(incident_id_for(candidate_id))
    assert failed["status"] == "failed"
    # Whichever node reads the policy first stops the run: gather_evidence when lineage runs, else propose_actions.
    assert failed["failure"]["node"] in ("gather_evidence", "propose_actions")
    assert "recall-response.md cannot be used: stale since" in str(
        failed["failure"]["error"]
    )


@pytest.mark.asyncio
async def test_the_desk_routes_approve_and_verify_a_paused_incident(client) -> None:
    incident = await _trigger(client, "label:P50211:7a0d3f", "label", "m-desk")
    incident_id = incident["incident_id"]
    listed = (await client.get("/desk/incidents")).json()
    (view,) = [v for v in listed if v["incident_id"] == incident_id]
    assert view["status"] == "awaiting_approval"
    assert view["card"].startswith(executor.DEMO_NOTICE)

    resp = await client.post(
        f"/desk/incidents/{incident_id}/decision",
        json={"decision": "approve", "actor": "coordinator-1"},
    )
    assert resp.status_code == 200, resp.text
    approved = resp.json()
    assert approved["status"] == "verifying" and approved["tasks"]
    again = await client.post(
        f"/desk/incidents/{incident_id}/decision", json={"decision": "approve"}
    )
    assert again.status_code == 409

    for task in approved["tasks"]:
        resp = await client.post(
            f"/desk/tasks/{task['task_id']}/verdict", json={"verdict": "verified_clear"}
        )
        assert resp.status_code == 200, resp.text
    assert store.get_incident(incident_id)["status"] == "closed"
