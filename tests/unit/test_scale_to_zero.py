"""What lets psd-api scale to zero: the poller's state survives an instance, and the internal routes take OIDC callers."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import main, recalls
from app import store as store_module
from tests.fake_firestore import FakeFirestore


@pytest.fixture
def db(monkeypatch) -> FakeFirestore:
    fake = FakeFirestore()
    monkeypatch.setenv("PSD_STORE", "firestore")
    monkeypatch.setattr(store_module, "firestore_client", lambda: fake)
    monkeypatch.setattr(recalls, "_state_loaded", [])
    monkeypatch.setattr(recalls, "_health", {})
    monkeypatch.setattr(recalls._fetcher, "validators", {})
    return fake


def test_a_new_instance_resumes_the_feeds_backoff_and_validators(
    db, monkeypatch
) -> None:
    (feed,) = [f for f in recalls.feeds.feeds() if f.name == "fsanz"]
    recalls._health["fsanz"] = {
        "feed": "fsanz",
        "failures": 2,
        "next_poll_after": "2099-01-01T00:00:00+00:00",
    }
    recalls._fetcher.validators[feed.url] = {"etag": '"abc"'}
    recalls._save_state()

    monkeypatch.setattr(recalls, "_state_loaded", [])
    monkeypatch.setattr(recalls, "_health", {})
    monkeypatch.setattr(recalls._fetcher, "validators", {})
    recalls._load_state()
    assert recalls._health["fsanz"]["failures"] == 2
    assert recalls._fetcher.validators[feed.url] == {"etag": '"abc"'}


def test_without_the_setting_the_poller_keeps_its_state_in_memory(monkeypatch) -> None:
    monkeypatch.delenv("PSD_STORE", raising=False)
    monkeypatch.setattr(
        store_module, "firestore_client", lambda: pytest.fail("Firestore was called")
    )
    monkeypatch.setattr(recalls, "_state_loaded", [])
    recalls._load_state()
    recalls._save_state()


def test_internal_routes_take_a_verified_caller_from_anywhere(monkeypatch) -> None:
    async def refuse(request):
        raise HTTPException(status_code=401, detail="no valid token")

    async def accept(request):
        return None

    far = TestClient(main.app, client=("203.0.113.9", 50000))
    monkeypatch.setattr(main.scope, "run", lambda: {"ran": True})
    monkeypatch.setattr(main, "_internal_verifier", refuse)
    assert far.post("/internal/scope", json={}).status_code == 401
    monkeypatch.setattr(main, "_internal_verifier", accept)
    assert far.post("/internal/scope", json={}).json() == {"ran": True}
    monkeypatch.setattr(main, "_internal_verifier", None)
    assert far.post("/internal/scope", json={}).status_code == 403
