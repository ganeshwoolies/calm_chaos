import pytest

from app import actions, executor
from app import store as store_module
from app.schemas import Decision, ShelfVerdict
from app.store import FirestoreStore, LocalStore, incident_id_for
from tests.fake_firestore import FakeFirestore


@pytest.fixture
def db() -> FakeFirestore:
    return FakeFirestore()


def _awaiting(store, ev, draft, pol) -> str:
    incident_id = incident_id_for(ev.candidate_id)
    store.begin_drafting(
        {
            "incident_id": incident_id,
            "candidate_id": ev.candidate_id,
            "kind": ev.kind,
            "product_id": ev.product.product_id,
            "supplier_id": ev.product.supplier_id,
            "interrupt_id": f"approve:{incident_id}",
            "hazard_type": ev.hazard_type,
            "product_name": f"{ev.product.brand} {ev.product.name}",
            "supplier_name": ev.product.supplier_name,
        }
    )
    store.update_incident(
        incident_id,
        status="awaiting_approval",
        draft=draft.model_dump(mode="json"),
        proposed=actions.propose(ev, pol).model_dump(mode="json"),
    )
    return incident_id


def test_a_new_store_reloads_what_an_earlier_one_wrote(
    db, yoghurt, recall_draft, pol
) -> None:
    first = FirestoreStore(db)
    incident_id = _awaiting(first, yoghurt, recall_draft, pol)
    first.suppress("recall:x:P1", "2099-01-01T00:00:00+00:00")
    again = FirestoreStore(db)
    assert again.get_incident(incident_id) == first.get_incident(incident_id)
    assert again.is_suppressed("recall:x:P1")
    assert db.data["psd_suppressed"]["recall:x:P1"] == {
        "until": "2099-01-01T00:00:00+00:00"
    }


def test_an_approval_is_one_batch_and_survives_a_restart(
    db, yoghurt, recall_draft, pol
) -> None:
    first = FirestoreStore(db)
    incident_id = _awaiting(first, yoghurt, recall_draft, pol)
    commits = db.commits
    result = executor.approve_incident(first, incident_id, Decision(decision="approve"))
    assert db.commits == commits + 1
    again = FirestoreStore(db)
    assert again.get_incident(incident_id)["status"] == result["status"] == "verifying"
    assert (
        len(again.open_tasks(incident_id)) == len(first.open_tasks(incident_id)) == 14
    )
    assert {m["status"] for m in again.outbox.values()} == {"sent"}
    assert sum(1 for m in again.outbox.values() if m["audience"] == "customer") == 37
    assert any(a["action"] == "approve_incident" for a in db.data["psd_audit"].values())


def test_a_verdict_and_a_dismissal_survive_a_restart(
    db, yoghurt, dinosaur, recall_draft, pol
) -> None:
    first = FirestoreStore(db)
    incident_id = _awaiting(first, yoghurt, recall_draft, pol)
    executor.approve_incident(first, incident_id, Decision(decision="approve"))
    task = first.open_tasks(incident_id)[0]
    executor.record_verification(
        first, task["task_id"], ShelfVerdict(verdict="verified_clear")
    )
    other = _awaiting(first, dinosaur, recall_draft, pol)
    executor.dismiss_incident(
        first, other, Decision(decision="dismiss", reason="Not ours")
    )
    again = FirestoreStore(db)
    assert again.tasks[task["task_id"]]["status"] == "verified_clear"
    assert again.get_incident(other)["status"] == "dismissed"
    assert again.is_suppressed(dinosaur.candidate_id)


def test_without_the_setting_the_store_stays_in_memory(monkeypatch) -> None:
    monkeypatch.delenv("PSD_STORE", raising=False)
    assert type(store_module.make_store()) is LocalStore


def test_every_version_written_is_appended_for_bigquery(
    db, yoghurt, recall_draft, pol
) -> None:
    appended: list = []
    mirrored = FirestoreStore(db, mirror=appended.extend)
    incident_id = _awaiting(mirrored, yoghurt, recall_draft, pol)
    # Outside a batch each write is appended at once: begin_drafting, then the update.
    assert [(c, k) for c, k, _ in appended] == [
        ("incidents", incident_id),
        ("incidents", incident_id),
    ]
    assert appended[-1][2]["status"] == "awaiting_approval"
    appended.clear()
    executor.approve_incident(mirrored, incident_id, Decision(decision="approve"))
    by_collection: dict = {}
    for collection, _, record in appended:
        by_collection.setdefault(collection, []).append(record)
    assert len(by_collection["tasks"]) == 14 and len(by_collection["outbox"]) == 39
    assert by_collection["incidents"][-1]["status"] == "verifying"
    assert {r["action"] for r in by_collection["audit"]} >= {
        "approve_incident",
        "issue_task",
        "send_message",
    }
