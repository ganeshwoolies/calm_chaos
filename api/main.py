"""psd-api: the recall poller, the relay, the scope job, the label check and the shelf check, with the coordinator and
store pages and the public scoreboard (GET /metrics).

    uv run uvicorn api.main:app --port 8081

On Cloud Run, Cloud Scheduler calls /internal/poll-recalls and /internal/scope, and Pub/Sub pushes psd-events-tag to
/internal/relay, each with an OIDC token (PSD_INTERNAL_AUDIENCE), so the service holds no loop and can scale to zero.
Locally, PSD_LOCAL_PULL=1 consumes the two subscriptions by streaming pull instead (the relay on psd-events-tag, and a
forwarder from psd-candidates-agent to the incident workflow at PSD_AGENTS_URL), and PSD_LOCAL_SCHEDULE=1 polls the
feeds every 15 minutes and runs the scope job every minute.
"""

import base64
import contextlib
import logging
import os
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from google.adk.cli.trigger_routes import GoogleOidcVerifier, PubSubTriggerRequest
from google.cloud import pubsub_v1
from google.cloud.pubsub_v1.subscriber.message import Message

from api import agents, desk, metrics, recalls, relay, scope, store
from app import bq
from app.store import DRAFTING_LEASE_SECONDS

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CANDIDATES_SUBSCRIPTION = "psd-candidates-agent"
SCOPE_SECONDS = 60


# Callers of the internal routes. On Cloud Run, Cloud Scheduler and Pub/Sub push call them with a Google-signed OIDC
# token for PSD_INTERNAL_AUDIENCE (the service URL), owned by one of PSD_INTERNAL_SERVICE_ACCOUNTS. Without an
# audience (local development) only loopback callers are served.
INTERNAL_AUDIENCE = os.getenv("PSD_INTERNAL_AUDIENCE") or None
INTERNAL_SERVICE_ACCOUNTS = [
    s for s in os.getenv("PSD_INTERNAL_SERVICE_ACCOUNTS", "").split(",") if s
] or None
_internal_verifier = (
    GoogleOidcVerifier(INTERNAL_AUDIENCE, allowed_emails=INTERNAL_SERVICE_ACCOUNTS)
    if INTERNAL_AUDIENCE
    else None
)


async def _internal_only(request: Request) -> None:
    if _internal_verifier:
        await _internal_verifier(request)
        return
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            status_code=403, detail="Internal routes answer loopback callers only."
        )


def _pull(
    subscription: str, handler: Callable[[Message], bool], max_messages: int
) -> Callable[[], None]:
    """Streaming pull with the handler's verdict as ack or nack; returns the function that stops it."""
    subscriber = pubsub_v1.SubscriberClient()
    path = subscriber.subscription_path(bq.client().project, subscription)

    def callback(message: Message) -> None:
        try:
            ok = handler(message)
        except Exception:
            logger.exception(
                "%s: handler raised on message %s", subscription, message.message_id
            )
            ok = False
        if ok:
            message.ack()
        else:
            message.nack()

    future = subscriber.subscribe(
        path,
        callback=callback,
        flow_control=pubsub_v1.types.FlowControl(max_messages=max_messages),
    )
    logger.info("pulling %s", path)

    def stop() -> None:
        future.cancel()
        with contextlib.suppress(Exception):
            future.result(timeout=30)
        subscriber.close()

    return stop


def _every(seconds: float, job: Callable[[], Any], name: str) -> Callable[[], None]:
    """Runs job now and then every `seconds` on a daemon thread; returns the function that stops it."""
    stopped = threading.Event()

    def loop() -> None:
        while not stopped.is_set():
            try:
                job()
            except Exception:
                logger.exception("%s failed", name)
            stopped.wait(seconds)

    threading.Thread(target=loop, name=name, daemon=True).start()
    return stopped.set


def _relay_pulled(message: Message) -> bool:
    return relay.relay(message.data, dict(message.attributes), message.message_id)


def _forward_candidate(message: Message) -> bool:
    """Delivers a candidate to the incident workflow as Pub/Sub push would, so its push route runs unchanged."""
    envelope = {
        "message": {
            "data": base64.b64encode(message.data).decode("ascii"),
            "attributes": dict(message.attributes),
            "messageId": message.message_id,
            "publishTime": message.publish_time.isoformat(),
        },
        "subscription": f"projects/{bq.client().project}/subscriptions/{CANDIDATES_SUBSCRIPTION}",
    }
    response = agents.call(
        "POST",
        "/trigger/candidates",
        json=envelope,
        timeout=DRAFTING_LEASE_SECONDS + 60,
    )
    if response.is_success:
        logger.info(
            "candidate %s delivered: %s", message.message_id, response.text[:200]
        )
        return True
    logger.warning(
        "candidate %s refused with %d: %s",
        message.message_id,
        response.status_code,
        response.text[:500],
    )
    return False


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    stops: list[Callable[[], None]] = []
    # 1 pulls both subscriptions; "relay" or "candidates" pulls one, while the other is delivered by push.
    pulls = os.environ.get("PSD_LOCAL_PULL", "")
    if pulls in ("1", "relay"):
        stops.append(_pull(relay.SUBSCRIPTION, _relay_pulled, max_messages=10))
    if pulls in ("1", "candidates"):
        stops.append(_pull(CANDIDATES_SUBSCRIPTION, _forward_candidate, max_messages=2))
    if os.environ.get("PSD_LOCAL_SCHEDULE") == "1":
        stops.append(
            _every(recalls.POLL_INTERVAL.total_seconds(), recalls.poll, "poll-recalls")
        )
        stops.append(_every(SCOPE_SECONDS, scope.run, "scope"))
    yield
    for stop in stops:
        stop()


app = FastAPI(title="psd-api", lifespan=lifespan)
app.include_router(desk.router)
app.include_router(store.router)
app.include_router(metrics.router)


@app.post("/internal/poll-recalls", dependencies=[Depends(_internal_only)])
def poll_recalls() -> dict[str, Any]:
    return recalls.poll()


@app.post("/internal/scope", dependencies=[Depends(_internal_only)])
def run_scope() -> dict[str, Any]:
    return scope.run()


@app.post("/internal/relay", status_code=204, dependencies=[Depends(_internal_only)])
def relay_push(push: PubSubTriggerRequest) -> Response:
    """Push form of the relay: a 5xx asks Pub/Sub to redeliver."""
    message = push.message
    data = base64.b64decode(message.data or "")
    if not relay.relay(data, message.attributes or {}, message.messageId or ""):
        raise HTTPException(
            status_code=503, detail="Publish to the tagged topic failed; redeliver."
        )
    return Response(status_code=204)
