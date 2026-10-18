"""The coordinator page and its API: recall notices from BigQuery; incidents, decisions and shelf verdicts from
psd-agents; and scenario controls that publish a fictional notice, poll the feeds or run the scope job now.

The page is public; every API call needs the desk passcode (PSD_DESK_PASSCODE, from Secret Manager on Cloud Run).
Without a passcode set (local development) only loopback callers are served.
"""

import hmac
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from google.auth.exceptions import TransportError
from pydantic import BaseModel

from api import agents, feeds, identity, labels, recalls, scope, storelinks
from app import bq, knowledge
from app.schemas import Decision, Promotion, ShelfVerdict
from data import gen_notices

PAGE = Path(__file__).parent / "static" / "desk.html"
NOTICES_SQL = """SELECT guid, feed, title, url, attribution, published_at, first_seen, match_status, matched_product_id,
  match_options, candidate_id, screen_flagged
FROM recall_notices
ORDER BY first_seen DESC
LIMIT 50"""
# Several viewers polling the page share one BigQuery read every NOTICES_SECONDS.
NOTICES_SECONDS = 10.0

_notices: dict[str, Any] = {"rows": [], "at": 0.0}
_notices_lock = threading.Lock()


def _passcode(request: Request) -> None:
    """A signed-in coordinator's Firebase token, or the desk passcode."""
    request.state.actor = None
    scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and bearer.strip():
        # A 401 signs the page out; a check that could not run is a 503, which the page shows and retries.
        try:
            actor = identity.coordinator(bearer.strip())
        except TransportError as e:
            raise HTTPException(
                status_code=503,
                detail="The desk could not check your sign-in; it tries again shortly.",
            ) from e
        if not actor:
            raise HTTPException(
                status_code=401,
                detail="Sign in with an account that has the coordinator role.",
            )
        request.state.actor = actor
        return
    expected = os.environ.get("PSD_DESK_PASSCODE")
    if expected:
        given = request.headers.get("x-desk-passcode", "")
        if not hmac.compare_digest(given.encode(), expected.encode()):
            raise HTTPException(
                status_code=401, detail="The passcode is missing or wrong."
            )
        return
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            status_code=403,
            detail="Set PSD_DESK_PASSCODE to serve the desk to other hosts.",
        )


router = APIRouter()
api = APIRouter(prefix="/desk/api", dependencies=[Depends(_passcode)])


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/desk")


@router.get("/desk", include_in_schema=False)
def page() -> FileResponse:
    # Revalidated on every open, so a deploy never leaves a browser on the old page.
    return FileResponse(
        PAGE, media_type="text/html", headers={"Cache-Control": "no-cache"}
    )


def _agents(method: str, path: str, body: Any = None, timeout: float = 60) -> Any:
    response = agents.call(method, path, json=body, timeout=timeout)
    if response.status_code >= 400:
        # psd-agents explains a refusal in FastAPI's {"detail": ...}; the page shows that sentence, not the JSON.
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise HTTPException(
            status_code=response.status_code,
            detail=(detail if isinstance(detail, str) else response.text)[:500],
        )
    return response.json()


@api.get("/notices")
def notices() -> dict[str, Any]:
    with _notices_lock:
        if time.monotonic() - _notices["at"] > NOTICES_SECONDS:
            _notices["rows"] = bq.rows(NOTICES_SQL)
            _notices["at"] = time.monotonic()
        rows = _notices["rows"]
    fictional = {f.name for f in feeds.feeds() if f.fictional}
    return {
        "notices": [{**r, "fictional": r["feed"] in fictional} for r in rows],
        "feeds": recalls.health(),
    }


@api.get("/incidents")
def incidents() -> list[dict[str, Any]]:
    """Every incident, each task with the link to its store's page."""
    out = _agents("GET", "/desk/incidents")
    for incident in out:
        for task in incident.get("tasks") or []:
            task["store_link"] = storelinks.link(task["store_id"])
    return out


@api.get("/stores")
def stores() -> list[dict[str, Any]]:
    return list(labels.stores())


@api.get("/store-link/{store_id}")
def store_link(store_id: str) -> dict[str, str]:
    """The signed link that opens one store's page; only the coordinator hands these out."""
    if store_id not in {s["store_id"] for s in labels.stores()}:
        raise HTTPException(status_code=404, detail=f"No store {store_id}")
    return {"store_id": store_id, "url": storelinks.link(store_id)}


def _actor(request: Request, given: str) -> str:
    """A signed-in coordinator acts under their verified email, whatever the page sent."""
    return request.state.actor or given


@api.get("/me")
def me(request: Request) -> dict[str, Any]:
    return {"actor": request.state.actor}


@api.post("/incidents/{incident_id}/decision")
def decide(incident_id: str, decision: Decision, request: Request) -> dict[str, Any]:
    decision.actor = _actor(request, decision.actor)
    return _agents(
        "POST",
        f"/desk/incidents/{incident_id}/decision",
        decision.model_dump(mode="json"),
        timeout=660,
    )


@api.get("/incidents/{incident_id}/trace")
def incident_trace(incident_id: str) -> dict[str, Any]:
    return _agents("GET", f"/desk/incidents/{incident_id}/trace")


@api.post("/tasks/{task_id}/verdict")
def verdict(task_id: str, shelf: ShelfVerdict) -> dict[str, Any]:
    return _agents(
        "POST",
        f"/desk/tasks/{task_id}/verdict",
        shelf.model_dump(mode="json"),
        timeout=660,
    )


@api.post("/memory/retry")
def memory_retry(limit: int | None = Query(default=None, ge=1)) -> dict[str, Any]:
    # Each incident's scopes generate together, each within a minute.
    path = "/desk/memory/retry" + (f"?limit={limit}" if limit is not None else "")
    return _agents("POST", path, timeout=300)


@api.get("/memories")
def memories() -> dict[str, Any]:
    return _agents("GET", "/desk/memories")


@api.delete("/memories/{memory_id}")
def memory_delete(
    memory_id: str, request: Request, actor: str = Query(min_length=1)
) -> dict[str, Any]:
    actor = _actor(request, actor)
    return _agents(
        "DELETE", f"/desk/memories/{memory_id}?{urlencode({'actor': actor})}"
    )


@api.post("/memories/{memory_id}/promote")
def memory_promote(
    memory_id: str, promotion: Promotion, request: Request
) -> dict[str, Any]:
    promotion.actor = _actor(request, promotion.actor)
    return _agents(
        "POST",
        f"/desk/memories/{memory_id}/promote",
        promotion.model_dump(mode="json"),
        timeout=120,
    )


@api.get("/knowledge")
def knowledge_summary() -> dict[str, Any]:
    """The pinned bundle's promoted notes and staleness report, for the Learned tab."""
    bundle = knowledge.load_bundle()
    now = datetime.now(UTC)
    learned = [
        {
            "path": path,
            "type": c.type,
            "title": c.title,
            "verified_by": [v.by for v in c.human_verifications],
            "stale_after": c.stale_after.isoformat() if c.stale_after else None,
            "usable": c.usable(now),
            "sources": [s.get("id") for s in c.meta.get("sources") or []],
        }
        for path, c in sorted(bundle.concepts.items())
        if path.startswith("/learned/")
    ]
    stale, due = knowledge.staleness(bundle, now)
    return {
        "version": knowledge.knowledge_version(bundle),
        "learned": learned,
        "stale": stale,
        "due": due,
    }


class FictionalNotice(BaseModel):
    scenario: str


@api.get("/scenarios")
def scenarios() -> list[str]:
    return [s["id"] for s in gen_notices.load_truth()["recall_scenarios"]]


@api.post("/test-notice")
def fictional_notice(body: FictionalNotice) -> dict[str, Any]:
    """Publishes one FICTIONAL TEST notice to the test feed, then polls, so it is on its way to extraction."""
    if body.scenario not in scenarios():
        raise HTTPException(status_code=400, detail=f"No scenario {body.scenario}")
    (notice,) = gen_notices.render_all(
        [body.scenario], datetime.now(UTC).replace(microsecond=0)
    )
    gen_notices.publish([notice], feeds.feeds_bucket())
    return {"guid": notice.guid, "title": notice.title, "poll": recalls.poll()}


@api.post("/poll")
def poll() -> dict[str, Any]:
    return recalls.poll()


@api.post("/scope")
def run_scope() -> dict[str, Any]:
    return scope.run()


_labels: dict[str, Any] = {"rows": [], "at": 0.0}
_labels_lock = threading.Lock()


@api.get("/labels")
def label_checks() -> list[dict[str, Any]]:
    """The latest label checks from every store, newest first; viewers share one read every NOTICES_SECONDS."""
    with _labels_lock:
        if time.monotonic() - _labels["at"] > NOTICES_SECONDS:
            _labels["rows"] = labels.recent()
            _labels["at"] = time.monotonic()
        return _labels["rows"]


router.include_router(api)
