"""The recall trigger end to end on live services: a fictional notice on the test feed becomes one paused incident.

poll → Model Armor → psd-events → the AI Inference transform on psd-events-tag → the relay → psd-events-tagged → the
BigQuery subscription → the scope job → psd-incident-candidates → the workflow's push route. Needs the feeds bucket, the
topics and subscriptions, the Model Armor template and the loaded world; calls Gemini in the transform, in AI.IF and in
the drafter. Skipped when a resource is missing.
"""

import base64
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import pytest_asyncio
from google.api_core.exceptions import NotFound
from google.cloud import bigquery, pubsub_v1, storage

from api import feeds, recalls, relay, scope
from api.main import CANDIDATES_SUBSCRIPTION, _pull, _relay_pulled
from app import bq
from app.fast_api_app import app as fastapi_app
from app.store import store
from data import gen_notices
from tests.knowledge_copy import copy_bundle

LANDING_SECONDS = 420

_NOTICE_SQL = """SELECT n.match_status, n.receipt_id, n.candidate_id, n.screen_flagged, e.severity, e.hazard_type,
  e.tag_error, e.recall_extract
FROM recall_notices AS n
LEFT JOIN v_events_dedup AS e USING (event_id)
WHERE n.guid = @guid"""


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setenv("PSD_KNOWLEDGE_DIR", str(copy_bundle(tmp_path / "knowledge")))
    monkeypatch.setenv("PSD_EVIDENCE_SOURCE", "bigquery")
    client = bq.client()
    try:
        pubsub_v1.PublisherClient().get_topic(
            topic=f"projects/{client.project}/topics/psd-events"
        )
        storage.Client(project=client.project).get_bucket(feeds.feeds_bucket())
        client.get_table(bq.table_ref("recall_notices"))
    except NotFound as e:
        pytest.skip(f"a recall trigger resource is missing: {e}")


@pytest_asyncio.fixture
async def workflow():
    store.reset()
    transport = httpx.ASGITransport(app=fastapi_app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1", timeout=600
    ) as c:
        yield c
    store.reset()


def _wait(what: str, check: Callable[[], Any], seconds: float) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if value := check():
            return value
        time.sleep(5)
    raise AssertionError(f"timed out after {seconds:.0f} s waiting for {what}")


def _notice(guid: str) -> dict[str, Any] | None:
    rows = bq.rows(_NOTICE_SQL, [bigquery.ScalarQueryParameter("guid", "STRING", guid)])
    return rows[0] if rows else None


def _scoped(guid: str) -> dict[str, Any] | None:
    scope.run()
    row = _notice(guid)
    return row if row and row["match_status"] != "pending" else None


def _landed(guid: str) -> dict[str, Any] | None:
    row = _notice(guid)
    return row if row and row["severity"] else None


def _candidate_envelope(candidate_id: str) -> dict[str, Any]:
    """The candidate's message from psd-candidates-agent as a push envelope; any other message is nacked."""
    subscriber = pubsub_v1.SubscriberClient()
    path = subscriber.subscription_path(bq.client().project, CANDIDATES_SUBSCRIPTION)
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            response = subscriber.pull(subscription=path, max_messages=10, timeout=30)
            ours = [
                r
                for r in response.received_messages
                if json.loads(r.message.data).get("candidate_id") == candidate_id
            ]
            others = [r.ack_id for r in response.received_messages if r not in ours]
            if others:
                subscriber.modify_ack_deadline(
                    subscription=path, ack_ids=others, ack_deadline_seconds=0
                )
            if ours:
                subscriber.acknowledge(
                    subscription=path, ack_ids=[r.ack_id for r in ours]
                )
                m = ours[0].message
                return {
                    "message": {
                        "data": base64.b64encode(m.data).decode("ascii"),
                        "attributes": dict(m.attributes),
                        "messageId": m.message_id,
                    },
                    "subscription": path,
                }
    finally:
        subscriber.close()
    raise AssertionError(f"candidate {candidate_id} never reached {path}")


@pytest.mark.asyncio
async def test_a_fictional_notice_becomes_one_paused_incident(
    live, workflow, monkeypatch
) -> None:
    bucket = feeds.feeds_bucket()
    (notice,) = gen_notices.render_all(
        ["yoghurt_listeria"], datetime.now(UTC).replace(microsecond=0)
    )
    gen_notices.publish([notice], bucket)
    test_feed = next(f for f in feeds.feeds() if f.name == "test")
    monkeypatch.setattr(recalls.feeds, "feeds", lambda: [test_feed])

    stop = _pull(relay.SUBSCRIPTION, _relay_pulled, max_messages=10)
    try:
        polled = recalls.poll()
        assert polled["published"] >= 1 and polled["failed"] == 0, polled
        assert _notice(notice.guid)["match_status"] == "pending"
        landed = _wait(
            "the tagged row in v_events_dedup",
            lambda: _landed(notice.guid),
            LANDING_SECONDS,
        )
    finally:
        stop()
    assert landed["tag_error"] is None, landed
    assert (landed["hazard_type"], landed["severity"]) == ("microbial", "critical")
    assert landed["screen_flagged"] is False
    extract = json.loads(landed["recall_extract"])
    assert extract["batch_codes"] == notice.expected["batch_codes"]

    scoped = _wait("the scope job", lambda: _scoped(notice.guid), 180)
    assert scoped["match_status"] == "matched", scoped
    assert scoped["candidate_id"] == scope.candidate_id(notice.guid, "P48812")

    response = await workflow.post(
        "/trigger/candidates", json=_candidate_envelope(scoped["candidate_id"])
    )
    assert response.status_code == 200, response.text
    incident = store.find_incident_for_candidate(scoped["candidate_id"])
    assert incident and incident["status"] == "awaiting_approval", incident

    session = await workflow.get(
        f"/apps/app/users/{incident['user_id']}/sessions/{incident['session_id']}"
    )
    state = session.json()["state"]
    assert state["evidence"]["lineage"]["receipt_id"] == scoped["receipt_id"]
    assert state["evidence"]["notice"]["guid"] == notice.guid
    proposed = state["proposed"]
    assert len(proposed["store_actions"]) == 14
    assert sum(a["qty_on_hand"] for a in proposed["store_actions"]) == 212
    assert len(proposed["message_orders"]) == 37
    assert proposed["receipts"] == [scoped["receipt_id"]]
