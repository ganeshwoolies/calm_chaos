"""End to end on a running desk: a fictional recall notice becomes one incident paused for approval, with attested
figures.

    PSD_E2E=1 PSD_E2E_URL=https://<psd-api URL> PSD_E2E_PASSCODE=<desk passcode> uv run pytest tests/e2e

PSD_E2E_URL defaults to a local psd-api (http://127.0.0.1:8081, with psd-agents beside it). The run publishes the
yoghurt_listeria scenario to the test feed and drives the poll and the scope job itself, then waits for the draft. It
makes about 4 to 9 Gemini calls: one extraction, up to five match confirmations, and one to three drafts. It leaves the
incident awaiting approval, as a coordinator would find it.
"""

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PSD_E2E") != "1",
    reason="publishes a notice and calls Gemini: set PSD_E2E=1 to run",
)

URL = os.environ.get("PSD_E2E_URL", "http://127.0.0.1:8081").rstrip("/")
# The truth of yoghurt_listeria (data/truth.yaml): 14 stores hold 212 units, and 37 online orders contain the batch.
STORES, UNITS, ORDERS = 14, 212, 37
EXTRACT_SECONDS = 600
DRAFT_SECONDS = 600


@pytest.fixture
def desk() -> httpx.Client:
    headers = {"X-Desk-Passcode": os.environ.get("PSD_E2E_PASSCODE", "")}
    with httpx.Client(base_url=URL, headers=headers, timeout=660) as client:
        yield client


def _until(seconds: float, step: float, check):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if (found := check()) is not None:
            return found
        time.sleep(step)
    return None


def test_a_fictional_notice_becomes_an_incident_paused_with_attested_figures(
    desk,
) -> None:
    published = desk.post(
        "/desk/api/test-notice", json={"scenario": "yoghurt_listeria"}
    )
    assert published.status_code == 200, published.text
    guid = published.json()["guid"]

    def matched():
        rows = desk.get("/desk/api/notices").json()["notices"]
        notice = next((n for n in rows if n["guid"] == guid), None)
        if notice and notice["candidate_id"]:
            return notice
        desk.post("/desk/api/poll")
        desk.post("/desk/api/scope")
        return None

    notice = _until(EXTRACT_SECONDS, 20, matched)
    assert notice is not None, f"{guid} was not matched within {EXTRACT_SECONDS} s"
    assert (
        notice["match_status"] == "matched" and notice["matched_product_id"] == "P48812"
    )

    def paused():
        for incident in desk.get("/desk/api/incidents").json():
            if incident["candidate_id"] == notice["candidate_id"] and incident[
                "status"
            ] in (
                "awaiting_approval",
                "failed",
                "blocked",
            ):
                return incident
        return None

    incident = _until(DRAFT_SECONDS, 10, paused)
    assert incident is not None, (
        f"no incident for {notice['candidate_id']} within {DRAFT_SECONDS} s"
    )
    assert incident["status"] == "awaiting_approval", incident.get("failure")
    actions = incident["detail"]["actions"]
    assert actions[0].startswith(f"pull at {STORES} stores ({UNITS} units on hand)")
    assert f"message {ORDERS} online orders" in actions
    receipts = incident["detail"]["receipts"]
    assert receipts and not any(r.startswith("rcpt-fixture") for r in receipts)
