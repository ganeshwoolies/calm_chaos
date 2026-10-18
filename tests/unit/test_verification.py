"""Shelf verification: every open task is asked at once, so stores answer in any order, and the incident then closes."""

import pytest
from fastapi.testclient import TestClient

from app.store import incident_id_for, store
from tests import offline_desk

YOGHURT = "recall:yoghurt_listeria"
INCIDENT = incident_id_for(YOGHURT)


@pytest.fixture
def approved(monkeypatch, recall_draft) -> TestClient:
    desk = offline_desk.desk(monkeypatch, recall_draft)
    assert offline_desk.push(desk, YOGHURT).json()["status"] == "awaiting_approval"
    r = desk.post(f"/desk/incidents/{INCIDENT}/decision", json={"decision": "approve"})
    assert r.json()["status"] == "verifying"
    return desk


def _verdict(desk: TestClient, task_id: str, verdict: str = "verified_clear", **more):
    return desk.post(
        f"/desk/tasks/{task_id}/verdict", json={"verdict": verdict, **more}
    )


def test_stores_verify_in_any_order_and_the_incident_closes(approved) -> None:
    tasks = [t["task_id"] for t in store.open_tasks(INCIDENT)]
    assert len(tasks) == 14
    for task_id in reversed(tasks):
        r = _verdict(approved, task_id)
        assert r.status_code == 200, r.text
    assert store.get_incident(INCIDENT)["status"] == "closed"
    assert all(store.tasks[t]["status"] == "verified_clear" for t in tasks)


def test_a_shelf_not_clear_is_asked_again_under_a_new_task(approved) -> None:
    last = store.open_tasks(INCIDENT)[-1]["task_id"]
    r = _verdict(
        approved,
        last,
        "not_clear",
        note="Two tubs are still at the back of the shelf.",
        photo_uri="gs://photos/shelves/last.jpg",
    )
    assert r.status_code == 200
    assert store.tasks[last]["verification"]["photo_uri"] == (
        "gs://photos/shelves/last.jpg"
    )
    reissued = f"{last}-r1"
    assert store.tasks[reissued]["status"] == "open"
    assert _verdict(approved, reissued).status_code == 200
    assert store.tasks[reissued]["status"] == "verified_clear"
    assert _verdict(approved, last).status_code == 409
