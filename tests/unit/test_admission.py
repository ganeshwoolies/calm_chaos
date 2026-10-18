from datetime import UTC, datetime, timedelta

from app.store import DRAFTING_LEASE_SECONDS, incident_id_for, store

CANDIDATE = "recall:yoghurt_listeria"
INCIDENT = incident_id_for(CANDIDATE)


def _open() -> dict:
    return store.begin_drafting(
        {"incident_id": INCIDENT, "candidate_id": CANDIDATE, "session_id": INCIDENT}
    )


def test_unknown_candidate_is_new() -> None:
    assert store.admission(CANDIDATE) == "new"


def test_a_live_run_is_not_joined() -> None:
    _open()
    assert store.admission(CANDIDATE) == "in_progress"


def test_a_run_past_its_lease_is_drafted_again() -> None:
    incident = _open()
    incident["drafting_since"] = (
        datetime.now(UTC) - timedelta(seconds=DRAFTING_LEASE_SECONDS + 1)
    ).isoformat()
    assert store.admission(CANDIDATE) == "retry"


def test_a_failed_run_is_drafted_again_and_keeps_its_history() -> None:
    _open()
    store.mark_failed(INCIDENT, "validate_and_persist", ["unknown store S999"])
    assert store.admission(CANDIDATE) == "retry"
    incident = _open()
    assert incident["status"] == "drafting" and incident["attempt"] == 2
    assert incident["history"][-1]["status"] == "failed"
    assert "failure" not in incident


def test_mark_failed_leaves_a_paused_incident_alone() -> None:
    _open()
    store.update_incident(INCIDENT, status="awaiting_approval")
    store.mark_failed(INCIDENT, "workflow", "late error")
    assert store.get_incident(INCIDENT)["status"] == "awaiting_approval"
    assert store.admission(CANDIDATE) == "duplicate"


def test_a_dismissal_suppresses_until_it_expires() -> None:
    _open()
    store.update_incident(INCIDENT, status="dismissed", dismiss_reason="Not ours")
    store.suppress(CANDIDATE, (datetime.now(UTC) + timedelta(hours=1)).isoformat())
    assert store.admission(CANDIDATE) == "suppressed"
    store.suppress(CANDIDATE, (datetime.now(UTC) - timedelta(seconds=1)).isoformat())
    assert store.admission(CANDIDATE) == "reraise"
    incident = _open()
    assert "dismiss_reason" not in incident
    assert incident["history"][-1]["dismiss_reason"] == "Not ours"
