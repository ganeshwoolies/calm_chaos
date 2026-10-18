"""The run trace the coordinator sees: an incident drafted, edited and approved offline, read back step by step."""

import json

import pytest
from fastapi.testclient import TestClient

from app.store import incident_id_for
from tests import offline_desk

YOGHURT = "recall:yoghurt_listeria"
INCIDENT = incident_id_for(YOGHURT)


@pytest.fixture
def desk(monkeypatch, recall_draft) -> TestClient:
    return offline_desk.desk(monkeypatch, recall_draft)


def _drafted_and_approved(desk: TestClient) -> None:
    pushed = offline_desk.push(desk, YOGHURT)
    assert pushed.json()["status"] == "awaiting_approval"
    approved = desk.post(
        f"/desk/incidents/{INCIDENT}/decision",
        json={
            "decision": "approve",
            "remove_stores": ["S004"],
            "text": {"narrative": "Edited by the coordinator."},
        },
    )
    assert approved.status_code == 200 and approved.json()["status"] == "verifying"
    assert approved.json()["approval"]["edits"] == [
        "removed stores from the proposal",
        "edited the narrative",
    ]
    # The card now reads as approved, not as proposed.
    card = approved.json()["card"]
    assert "Approved actions:" in card and "Edited by the coordinator." in card
    assert "S004" not in card


def test_the_trace_reads_as_the_run_happened(desk) -> None:
    _drafted_and_approved(desk)
    trace = desk.get(f"/desk/incidents/{INCIDENT}/trace").json()
    assert trace["session_id"] == INCIDENT
    steps = trace["steps"]
    nodes = [s["node"] for s in steps]
    for node in (
        "parse_candidate",
        "gather_evidence",
        "propose_actions",
        "recall_drafter",
        "validate_and_persist",
        "await_approval",
        "apply_decision",
        "execute_approved",
        "await_verification",
    ):
        assert node in nodes, node
    (draft,) = [s for s in steps if s["kind"] == "draft"]
    assert draft["summary"].startswith("draft: Morrowdale Vanilla Yoghurt 1kg")
    assert "(6100 tokens in, 420 out)" in draft["summary"]
    pauses = [s["summary"] for s in steps if s["kind"] == "pause"]
    assert pauses[0] == f"paused for approve:{INCIDENT}"
    # The 13 shelf checks are asked at once and read as one step.
    assert pauses[1].startswith(f"paused for 13 replies: verify:task-{INCIDENT}-")
    (decision,) = [s for s in steps if s["kind"] == "resume"]
    assert decision["summary"] == (
        f"approve:{INCIDENT} answered: approve by coordinator "
        "with edits to remove_stores, text.narrative"
    )
    # A resumed run replays every finished node; the trace shows each one once.
    assert nodes.count("parse_candidate") == 1


def test_the_trace_shows_state_by_its_keys_only(desk) -> None:
    _drafted_and_approved(desk)
    shown = json.dumps(desk.get(f"/desk/incidents/{INCIDENT}/trace").json())
    (evidence,) = [
        s
        for s in desk.get(f"/desk/incidents/{INCIDENT}/trace").json()["steps"]
        if s["node"] == "gather_evidence"
    ]
    assert "state evidence" in evidence["summary"]
    for private in ("store_rows", "Verified knowledge", "Do not eat it."):
        assert private not in shown, private


def test_an_incident_without_a_session_here_has_no_trace(desk) -> None:
    assert desk.get("/desk/incidents/inc-none/trace").status_code == 404
