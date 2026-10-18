import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from google.auth import exceptions, jwt

from api import desk, identity, main, store

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _fresh_cache():
    identity._verified.clear()
    yield
    identity._verified.clear()


def _claims(monkeypatch, claims: dict | None, calls: list | None = None) -> None:
    def verify(token, request, audience):
        if calls is not None:
            calls.append((token, audience))
        if claims is None:
            raise ValueError("bad token")
        return claims

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "calm-chaos")
    monkeypatch.setattr(identity.id_token, "verify_firebase_token", verify)


def test_only_a_coordinator_token_names_an_actor(monkeypatch) -> None:
    calls: list = []
    _claims(
        monkeypatch,
        {"email": "amy@calmchaos.test", "coordinator": True, "exp": 4e9},
        calls,
    )
    assert identity.coordinator("t1") == "amy@calmchaos.test"
    assert identity.coordinator("t1") == "amy@calmchaos.test"
    assert calls == [
        ("t1", "calm-chaos")
    ]  # verified once, then cached until it expires

    _claims(monkeypatch, {"email": "raj@calmchaos.test", "exp": 4e9})
    assert identity.coordinator("t2") is None
    _claims(monkeypatch, None)
    assert identity.coordinator("t3") is None


def test_a_signed_in_coordinator_acts_under_their_email(monkeypatch) -> None:
    monkeypatch.setattr(
        identity,
        "coordinator",
        lambda token: "amy@calmchaos.test" if token == "good" else None,
    )
    sent = []

    def call(method, path, json=None, timeout=60):
        sent.append(json)
        return httpx.Response(200, json={})

    monkeypatch.setattr(desk.agents, "call", call)
    client = TestClient(main.app, client=("203.0.113.9", 50000))
    good = {"Authorization": "Bearer good"}
    assert client.get("/desk/api/me", headers=good).json() == {
        "actor": "amy@calmchaos.test"
    }
    client.post(
        "/desk/api/incidents/inc-1/decision",
        json={"decision": "approve", "actor": "coordinator"},
        headers=good,
    )
    assert sent[-1]["actor"] == "amy@calmchaos.test"
    bad = client.get("/desk/api/incidents", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401 and "coordinator role" in bad.json()["detail"]


def test_a_token_that_could_not_be_checked_is_not_refused(monkeypatch) -> None:
    def verify(token, request, audience):
        raise exceptions.TransportError("Could not fetch certificates")

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "calm-chaos")
    monkeypatch.setattr(identity.id_token, "verify_firebase_token", verify)
    with pytest.raises(exceptions.TransportError):
        identity.coordinator("t1")
    assert identity._verified == {}
    client = TestClient(main.app, client=("203.0.113.9", 50000))
    out = client.get("/desk/api/incidents", headers={"Authorization": "Bearer t1"})
    # A 401 would sign the coordinator out of the page; a 503 is shown and retried.
    assert out.status_code == 503


def test_a_store_link_is_exchanged_for_a_store_token(monkeypatch) -> None:
    monkeypatch.setenv("PSD_STORE_TOKEN_SALT", "salt")
    monkeypatch.setattr(
        store.labels,
        "stores",
        lambda: [{"store_id": "S012", "name": "x", "state": "NSW"}],
    )
    monkeypatch.setattr(identity, "store_token", lambda store_id: f"custom-{store_id}")
    client = TestClient(main.app, client=("203.0.113.9", 50000))
    headers = {
        "X-Store-Id": "S012",
        "X-Store-Token": store.storelinks.token("S012", "salt"),
    }
    assert client.post("/store/api/firebase-token", headers=headers).json() == {
        "token": "custom-S012"
    }
    wrong = {"X-Store-Id": "S012", "X-Store-Token": "forged"}
    assert client.post("/store/api/firebase-token", headers=wrong).status_code == 401


def test_a_store_token_is_a_firebase_custom_token_for_that_store(monkeypatch) -> None:
    credentials = SimpleNamespace(
        valid=True,
        service_account_email="sa-psd-api@calm-chaos.iam.gserviceaccount.com",
    )
    monkeypatch.setattr(
        identity.google.auth, "default", lambda: (credentials, "calm-chaos")
    )

    class Signer:
        key_id = None

        def __init__(self, request, creds, email):
            assert email == credentials.service_account_email

        def sign(self, message):
            return b"signature"

    monkeypatch.setattr(identity.iam, "Signer", Signer)
    payload = jwt.decode(identity.store_token("S012"), verify=False)
    assert payload["uid"] == "store-S012" and payload["claims"] == {"store_id": "S012"}
    assert payload["aud"] == identity.FIREBASE_TOKEN_AUDIENCE
    assert payload["iss"] == payload["sub"] == credentials.service_account_email
    assert payload["exp"] - payload["iat"] == identity.CUSTOM_TOKEN_SECONDS


def test_hosting_sends_the_apis_to_psd_api_and_the_rules_close_everything_else() -> (
    None
):
    config = json.loads((REPO / "firebase.json").read_text(encoding="utf-8"))
    run = {r["source"] for r in config["hosting"]["rewrites"] if "run" in r}
    assert run == {"/desk/api/**", "/store/api/**", "/metrics"}
    assert (REPO / config["hosting"]["public"] / "desk.html").is_file()
    rules = (REPO / config["firestore"]["rules"]).read_text(encoding="utf-8")
    assert (
        "match /psd_incidents/{incident}" in rules
        and "request.auth.token.store_id == resource.data.store_id" in rules
    )
    assert "allow read, write: if false;" in rules
