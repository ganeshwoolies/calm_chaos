import base64

import pytest
from fastapi.testclient import TestClient

from api import main


@pytest.fixture
def local() -> TestClient:
    return TestClient(main.app, client=("127.0.0.1", 50000))


def test_internal_routes_refuse_callers_other_than_loopback(monkeypatch) -> None:
    monkeypatch.setattr(main.recalls, "poll", lambda: {"new": 0})
    remote = TestClient(main.app, client=("10.0.0.7", 50000))
    assert remote.post("/internal/poll-recalls").status_code == 403


def test_poll_and_scope_run_their_jobs(local, monkeypatch) -> None:
    monkeypatch.setattr(main.recalls, "poll", lambda: {"new": 2})
    monkeypatch.setattr(main.scope, "run", lambda: {"landed": 1})
    assert local.post("/internal/poll-recalls").json() == {"new": 2}
    assert local.post("/internal/scope").json() == {"landed": 1}


def _push(data: bytes) -> dict:
    return {
        "message": {
            "data": base64.b64encode(data).decode("ascii"),
            "attributes": {"event_id": "evt_1", "source": "recall"},
            "messageId": "m1",
        },
        "subscription": "projects/p/subscriptions/psd-events-tag",
    }


def test_the_relay_push_forwards_the_decoded_row(local, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        main.relay,
        "relay",
        lambda data, attrs, mid: calls.append((data, attrs, mid)) or True,
    )
    assert (
        local.post("/internal/relay", json=_push(b'{"event_id": "evt_1"}')).status_code
        == 204
    )
    assert calls == [
        (b'{"event_id": "evt_1"}', {"event_id": "evt_1", "source": "recall"}, "m1")
    ]


def test_a_relay_push_that_cannot_publish_asks_for_redelivery(
    local, monkeypatch
) -> None:
    monkeypatch.setattr(main.relay, "relay", lambda data, attrs, mid: False)
    assert local.post("/internal/relay", json=_push(b"{}")).status_code == 503
