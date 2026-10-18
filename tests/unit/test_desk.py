from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from api import agents, desk, main


@pytest.fixture
def remote(monkeypatch) -> TestClient:
    """A browser on another host, with the desk passcode configured."""
    monkeypatch.setenv("PSD_DESK_PASSCODE", "lark-2026")
    return TestClient(main.app, client=("203.0.113.9", 50000))


def _calls(monkeypatch, status: int = 200, payload=None) -> list:
    calls = []

    def call(method, path, json=None, timeout=60):
        calls.append((method, path, json))
        return httpx.Response(status, json=payload if payload is not None else [])

    monkeypatch.setattr(desk.agents, "call", call)
    return calls


def test_the_page_is_public_and_the_root_leads_to_it(remote) -> None:
    page = remote.get("/desk")
    assert page.status_code == 200 and "Product Safety Desk" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert "not affiliated with or endorsed by any retailer" in page.text
    assert remote.get("/", follow_redirects=False).headers["location"] == "/desk"


def test_every_api_call_needs_the_passcode(remote, monkeypatch) -> None:
    _calls(monkeypatch)
    assert remote.get("/desk/api/incidents").status_code == 401
    wrong = remote.get("/desk/api/incidents", headers={"X-Desk-Passcode": "nope"})
    assert wrong.status_code == 401
    ok = remote.get("/desk/api/incidents", headers={"X-Desk-Passcode": "lark-2026"})
    assert ok.status_code == 200


def test_without_a_passcode_only_this_machine_is_served(monkeypatch) -> None:
    monkeypatch.delenv("PSD_DESK_PASSCODE", raising=False)
    _calls(monkeypatch)
    assert (
        TestClient(main.app, client=("203.0.113.9", 1))
        .get("/desk/api/incidents")
        .status_code
        == 403
    )
    assert (
        TestClient(main.app, client=("127.0.0.1", 1))
        .get("/desk/api/incidents")
        .status_code
        == 200
    )


AUTH = {"X-Desk-Passcode": "lark-2026"}


def test_decisions_and_verdicts_go_to_the_workflow(remote, monkeypatch) -> None:
    calls = _calls(monkeypatch, payload={"status": "verifying"})
    r = remote.post(
        "/desk/api/incidents/inc-1/decision",
        json={"decision": "approve", "actor": "coordinator"},
        headers=AUTH,
    )
    assert r.json() == {"status": "verifying"}
    remote.post(
        "/desk/api/tasks/t-1/verdict", json={"verdict": "verified_clear"}, headers=AUTH
    )
    (m1, p1, b1), (m2, p2, b2) = calls
    assert (m1, p1, b1["decision"]) == (
        "POST",
        "/desk/incidents/inc-1/decision",
        "approve",
    )
    assert (m2, p2, b2["verdict"]) == (
        "POST",
        "/desk/tasks/t-1/verdict",
        "verified_clear",
    )


def test_a_refusal_from_the_workflow_reaches_the_page(remote, monkeypatch) -> None:
    _calls(monkeypatch, status=409, payload={"detail": "inc-1 is closed"})
    r = remote.post(
        "/desk/api/incidents/inc-1/decision", json={"decision": "approve"}, headers=AUTH
    )
    assert r.status_code == 409 and "closed" in r.text


def test_notices_carry_the_fictional_flag_and_share_one_read(
    remote, monkeypatch
) -> None:
    reads = []
    rows = [
        {
            "guid": "g1",
            "feed": "test",
            "title": "FICTIONAL TEST: x",
            "match_status": "pending",
        },
        {
            "guid": "g2",
            "feed": "fsanz",
            "title": "Real notice",
            "match_status": "not_in_range",
        },
    ]
    monkeypatch.setattr(desk, "_notices", {"rows": [], "at": 0.0})
    monkeypatch.setattr(
        desk.bq, "rows", lambda sql, parameters=(): reads.append(sql) or rows
    )
    first = remote.get("/desk/api/notices", headers=AUTH).json()
    remote.get("/desk/api/notices", headers=AUTH)
    assert [n["fictional"] for n in first["notices"]] == [True, False]
    assert len(reads) == 1


def test_a_fictional_notice_is_published_then_polled(remote, monkeypatch) -> None:
    published = []
    monkeypatch.setattr(
        desk.gen_notices, "publish", lambda notices, bucket: published.extend(notices)
    )
    monkeypatch.setattr(desk.feeds, "feeds_bucket", lambda: "bucket")
    monkeypatch.setattr(desk.recalls, "poll", lambda: {"new": 1, "published": 1})
    r = remote.post(
        "/desk/api/test-notice", json={"scenario": "yoghurt_listeria"}, headers=AUTH
    )
    assert r.status_code == 200 and r.json()["poll"]["new"] == 1
    (n,) = published
    assert n.title.startswith("FICTIONAL TEST") and r.json()["guid"] == n.guid
    bad = remote.post("/desk/api/test-notice", json={"scenario": "nope"}, headers=AUTH)
    assert bad.status_code == 400


def test_calls_to_cloud_run_carry_an_id_token_for_its_url(monkeypatch) -> None:
    fetched, sent = [], []
    monkeypatch.setattr(agents, "URL", "https://psd-agents.example.run.app")
    monkeypatch.setattr(agents, "_token", {"value": None, "at": 0.0})
    monkeypatch.setattr(
        agents.id_token,
        "fetch_id_token",
        lambda request, audience: fetched.append(audience) or "tok",
    )
    monkeypatch.setattr(
        agents.httpx,
        "request",
        lambda method, url, json, headers, timeout: (
            sent.append((url, headers)) or SimpleNamespace(status_code=200)
        ),
    )
    agents.call("GET", "/desk/incidents")
    agents.call("GET", "/desk/incidents")
    assert fetched == ["https://psd-agents.example.run.app"]
    assert sent[0] == (
        "https://psd-agents.example.run.app/desk/incidents",
        {"Authorization": "Bearer tok"},
    )


def test_a_local_workflow_gets_no_token(monkeypatch) -> None:
    monkeypatch.setattr(agents, "URL", "http://127.0.0.1:8000")
    assert agents._headers() == {}


def test_a_memory_retry_goes_to_the_workflow_with_its_limit(
    remote, monkeypatch
) -> None:
    calls = _calls(monkeypatch, payload={"retried": 1, "generated": 1})
    r = remote.post("/desk/api/memory/retry?limit=1", headers=AUTH)
    assert r.status_code == 200 and r.json()["generated"] == 1
    remote.post("/desk/api/memory/retry", headers=AUTH)
    assert [c[:2] for c in calls] == [
        ("POST", "/desk/memory/retry?limit=1"),
        ("POST", "/desk/memory/retry"),
    ]


def test_a_run_trace_is_read_from_the_workflow(remote, monkeypatch) -> None:
    calls = _calls(monkeypatch, payload={"incident_id": "inc-1", "steps": []})
    r = remote.get("/desk/api/incidents/inc-1/trace", headers=AUTH)
    assert r.status_code == 200 and r.json()["steps"] == []
    assert calls[-1][:2] == ("GET", "/desk/incidents/inc-1/trace")


def test_a_refused_decision_comes_back_in_the_workflows_words(
    remote, monkeypatch
) -> None:
    said = "Dropping the checkout block on a critical recall needs a reason."
    _calls(monkeypatch, status=400, payload={"detail": said})
    r = remote.post(
        "/desk/api/incidents/inc-1/decision",
        json={"decision": "approve", "checkout_block": False},
        headers=AUTH,
    )
    assert r.status_code == 400 and r.json()["detail"] == said


def test_the_learned_routes_pass_through_to_psd_agents(remote, monkeypatch) -> None:
    calls = _calls(
        monkeypatch, payload={"observations": [], "promotion": {"available": False}}
    )
    headers = {"X-Desk-Passcode": "lark-2026"}
    assert (
        remote.get("/desk/api/memories", headers=headers).json()["observations"] == []
    )
    remote.delete("/desk/api/memories/m1", params={"actor": "amy"}, headers=headers)
    remote.post(
        "/desk/api/memories/m1/promote",
        json={"actor": "amy", "stale_after": "2027-04-30T00:00:00Z"},
        headers=headers,
    )
    assert [(m, p) for m, p, _ in calls] == [
        ("GET", "/desk/memories"),
        ("DELETE", "/desk/memories/m1?actor=amy"),
        ("POST", "/desk/memories/m1/promote"),
    ]
    assert calls[-1][2] == {
        "actor": "amy",
        "stale_after": "2027-04-30T00:00:00Z",
        "text": None,
    }


def test_the_learned_tab_reads_notes_and_staleness_from_the_pinned_bundle(
    remote,
) -> None:
    out = remote.get(
        "/desk/api/knowledge", headers={"X-Desk-Passcode": "lark-2026"}
    ).json()
    assert out["version"] and out["learned"] == []
    assert isinstance(out["stale"], list) and isinstance(out["due"], list)
