# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Modified by the Product Safety Desk team.

import asyncio
import base64
import collections
import contextlib
import functools
import json
import logging
import os
from collections.abc import AsyncIterator

from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.cli.trigger_routes import (
    TRIGGER_DELIVERY_STATE_KEY,
    GoogleOidcVerifier,
    PubSubTriggerRequest,
)
from google.adk.runners import Runner
from google.genai import types

from app import executor, knowledge, learn, memory, policy, promote, trace
from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.nodes import _action_lines, render_card
from app.schemas import (
    Candidate,
    Decision,
    DeployedCommit,
    IncidentText,
    Promotion,
    ProposedActions,
    ShelfVerdict,
)
from app.store import DRAFTING_LEASE_SECONDS, RUNNABLE, incident_id_for, store

load_dotenv()
logger = logging.getLogger(__name__)
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)
otel_to_cloud = True

# Caller auth for the candidate push and the coordinator routes. On Cloud Run, PSD_TRIGGER_AUDIENCE is the service
# URL and every call must carry a Google-signed OIDC token for it, owned by one of PSD_TRIGGER_SERVICE_ACCOUNTS
# when that is set. Without an audience (local development) only loopback callers are served.
TRIGGER_AUDIENCE = os.getenv("PSD_TRIGGER_AUDIENCE") or None
TRIGGER_SERVICE_ACCOUNTS = [
    s for s in os.getenv("PSD_TRIGGER_SERVICE_ACCOUNTS", "").split(",") if s
] or None
_oidc_verifier = (
    GoogleOidcVerifier(TRIGGER_AUDIENCE, allowed_emails=TRIGGER_SERVICE_ACCOUNTS)
    if TRIGGER_AUDIENCE
    else None
)

# Every incident run belongs to the desk, not to whichever subscription delivered the candidate.
DESK_USER_ID = "desk"


def _local_trigger_verifier(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            status_code=403,
            detail="Set PSD_TRIGGER_AUDIENCE to accept triggers from other hosts.",
        )


async def _verify_caller(request: Request) -> None:
    if _oidc_verifier:
        await _oidc_verifier(request)
    else:
        _local_trigger_verifier(request)


AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app
    from app.agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = adk_app.name
    await attach_a2a_routes(
        app,
        agent=root_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=f"/a2a/{adk_app.name}",
    )
    # Inside startup, while Cloud Run boosts the CPU; a Memory Bank that is down never stops the service starting.
    try:
        await asyncio.wait_for(asyncio.to_thread(memory.warm), timeout=20)
    except Exception as e:
        logger.warning("Memory Bank warm-up failed: %s", e)
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=os.getenv("PSD_DEV_UI") == "1",
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=otel_to_cloud,
    lifespan=lifespan,
)
app.title = "product-safety-desk"
app.description = "API for interacting with the Agent product-safety-desk"


@functools.cache
def _incident_runner() -> Runner:
    from app.agent import app as adk_app

    # The shared services are the ones the /run routes use, so a coordinator's resume finds this session.
    return Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
    )


# Serialises deliveries of one candidate inside this instance; admission makes later ones a no-op.
_candidate_locks: collections.defaultdict[str, asyncio.Lock] = collections.defaultdict(
    asyncio.Lock
)


async def _run_incident(runner: Runner, session_id: str, text: str, delivery: dict):
    errors = []
    async for event in runner.run_async(
        user_id=DESK_USER_ID,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        state_delta={TRIGGER_DELIVERY_STATE_KEY: delivery},
    ):
        if event.error_code:
            errors.append(
                {
                    "author": event.author,
                    "code": event.error_code,
                    "message": event.error_message,
                }
            )
    return errors


@app.post("/trigger/candidates", dependencies=[Depends(_verify_caller)])
async def trigger_candidate(req: PubSubTriggerRequest) -> dict:
    """Push endpoint of psd-candidates-agent: one session per incident, named by the incident id.

    ADK's own Pub/Sub trigger opens a session with a random id per delivery; this one derives the session from the
    candidate, so a redelivery lands in the incident's session or is acknowledged without running. A 5xx asks
    Pub/Sub to redeliver; a 400 dead-letters a message that is not a candidate.
    """
    try:
        payload = json.loads(base64.b64decode(req.message.data or "").decode("utf-8"))
        candidate = Candidate.model_validate(payload)
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=400, detail=f"Not an incident candidate: {e}"
        ) from e
    incident_id = incident_id_for(candidate.candidate_id)
    delivery = {
        "source": "pubsub",
        "id": req.message.messageId,
        "subscription": req.subscription,
        "publish_time": req.message.publishTime,
    }
    async with _candidate_locks[incident_id]:
        admission = store.admission(candidate.candidate_id)
        if admission not in RUNNABLE:
            logger.info("candidate %s not run: %s", candidate.candidate_id, admission)
            return {"status": admission, "incident_id": incident_id}
        runner = _incident_runner()
        session_service = runner.session_service
        app_name = runner.app_name
        if not await session_service.get_session(
            app_name=app_name, user_id=DESK_USER_ID, session_id=incident_id
        ):
            await session_service.create_session(
                app_name=app_name, user_id=DESK_USER_ID, session_id=incident_id
            )
        text = json.dumps({"data": payload, "attributes": req.message.attributes or {}})
        try:
            errors = await asyncio.wait_for(
                _run_incident(runner, incident_id, text, delivery),
                timeout=DRAFTING_LEASE_SECONDS,
            )
        except Exception as e:
            logger.exception("incident run %s raised", incident_id)
            errors = [{"author": None, "code": type(e).__name__, "message": str(e)}]
        # Error events also mark attempts that a node retry recovered from, so the outcome is the incident's status:
        # a run that neither paused nor stopped cleanly has failed.
        incident = store.find_incident_for_candidate(candidate.candidate_id)
        if incident and incident["status"] in ("drafting", "failed"):
            node = errors[-1]["author"] if errors else None
            store.mark_failed(
                incident_id, node or "workflow", errors or "ended without pausing"
            )
            raise HTTPException(
                status_code=500,
                detail=f"Incident run {incident_id} failed: {incident['failure']}",
            )
    return {
        "status": incident["status"] if incident else "no_evidence",
        "incident_id": incident_id,
    }


def _incident_view(incident: dict) -> dict:
    """What the coordinator sees of one incident: its card, tasks and messages, never the raw evidence."""
    incident_id = incident["incident_id"]
    tasks = sorted(
        (t for t in store.tasks.values() if t["incident_id"] == incident_id),
        key=lambda t: t["task_id"],
    )
    messages = [m for m in store.outbox.values() if m["incident_id"] == incident_id]
    customer = next((m for m in messages if m["audience"] == "customer"), None)
    drafted = bool(incident.get("draft") and incident.get("proposed"))
    return {
        "incident_id": incident_id,
        "candidate_id": incident.get("candidate_id"),
        "kind": incident.get("kind"),
        "status": incident.get("status"),
        "title": (
            (incident.get("approved") or {}).get("text") or incident.get("draft") or {}
        ).get("title"),
        "product_id": incident.get("product_id"),
        "product_name": incident.get("product_name"),
        "severity": (incident.get("proposed") or {}).get("severity"),
        "created_at": incident.get("created_at"),
        "attempt": incident.get("attempt"),
        "failure": incident.get("failure"),
        "screening": incident.get("screening"),
        "card": render_card(incident) if drafted else None,
        "detail": _card_parts(incident) if drafted else None,
        "tasks": [
            {
                **{
                    k: t.get(k)
                    for k in (
                        "task_id",
                        "store_id",
                        "kind",
                        "code",
                        "aisle",
                        "qty_on_hand",
                        "status",
                        "due_at",
                    )
                },
                "note": (t.get("verification") or {}).get("note"),
            }
            for t in tasks
        ],
        "messages": dict(collections.Counter(m["audience"] for m in messages)),
        "customer_message": (
            {"subject": customer["subject"], "body": customer["body"]}
            if customer
            else None
        ),
        "editable": _editable(incident)
        if incident.get("status") == "awaiting_approval" and drafted
        else None,
        "approval": (
            {
                "approved_by": incident.get("approved_by"),
                "approved_at": incident.get("approved_at"),
                "edits": incident.get("edits") or [],
                "notes": (incident.get("approved") or {}).get("notes") or [],
            }
            if incident.get("approved")
            else None
        ),
    }


def _card_parts(incident: dict) -> dict:
    """The card in parts for the page to lay out, from the same text and actions render_card reads."""
    approved = incident.get("approved")
    draft = IncidentText.model_validate(
        approved["text"] if approved else incident["draft"]
    )
    proposed = ProposedActions.model_validate(
        approved["actions"] if approved else incident["proposed"]
    )
    return {
        "basis": "approved" if approved else "proposed",
        "narrative": draft.narrative,
        "actions": [line.removeprefix("- ") for line in _action_lines(proposed)],
        "considerations": proposed.considerations + draft.considerations,
        "evidence": draft.evidence,
        "receipts": proposed.receipts,
        "customer_message": (
            draft.customer_message.model_dump() if draft.customer_message else None
        ),
    }


_STORE_FIELDS = ("store_id", "batch_id", "code", "action", "qty_on_hand", "aisle")
_TEXT_FIELDS = ("title", "narrative", "supplier_notice", "vendor_case_body", "qa_alert")


def _editable(incident: dict) -> dict:
    """What the coordinator may change before approving: the proposal's rows and the draft's texts."""
    proposed = ProposedActions.model_validate(incident["proposed"])
    draft = IncidentText.model_validate(incident["draft"])
    pol = policy.current()
    text = {f: getattr(draft, f) for f in _TEXT_FIELDS if getattr(draft, f) is not None}
    if draft.customer_message is not None:
        text["customer_message_subject"] = draft.customer_message.subject
        text["customer_message_body"] = draft.customer_message.body
    return {
        "store_actions": [
            a.model_dump(mode="json", include=set(_STORE_FIELDS))
            for a in proposed.store_actions
        ],
        "optional_store_actions": [
            a.model_dump(mode="json", include=set(_STORE_FIELDS))
            for a in proposed.optional_store_actions
        ],
        "checkout_block": proposed.checkout_block,
        "checkout_block_drop_needs_reason": proposed.checkout_block
        and pol.recall.checkout_block_drop_needs_reason
        and pol.checkout_block(proposed.severity),
        "orders_to_message": len(proposed.message_orders),
        "listing_fixes": [f.model_dump(mode="json") for f in proposed.listing_fixes],
        "text": text,
    }


async def _resume(incident_id: str, interrupt_id: str, reply: dict) -> list[dict]:
    """Answers the run's pending RequestInput, as POST /run with a function response does."""
    message = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=interrupt_id,
                    name="adk_request_input",
                    response={"result": json.dumps(reply)},
                )
            )
        ],
    )
    errors = []
    async for event in _incident_runner().run_async(
        user_id=DESK_USER_ID, session_id=incident_id, new_message=message
    ):
        if event.error_code:
            errors.append(
                {
                    "author": event.author,
                    "code": event.error_code,
                    "message": event.error_message,
                }
            )
    return errors


@app.get("/desk/incidents", dependencies=[Depends(_verify_caller)])
def desk_incidents() -> list[dict]:
    """Every incident, newest first."""
    incidents = sorted(
        store.incidents.values(), key=lambda i: i.get("created_at") or "", reverse=True
    )
    return [_incident_view(i) for i in incidents]


@app.post(
    "/desk/incidents/{incident_id}/decision", dependencies=[Depends(_verify_caller)]
)
async def desk_decision(incident_id: str, decision: Decision) -> dict:
    """The coordinator's approval or dismissal, given to the paused run."""
    if incident_id not in store.incidents:
        raise HTTPException(status_code=404, detail=f"No incident {incident_id}")
    async with _candidate_locks[incident_id]:
        incident = store.get_incident(incident_id)
        if incident["status"] != "awaiting_approval":
            raise HTTPException(
                status_code=409, detail=f"{incident_id} is {incident['status']}"
            )
        # Refused before the run resumes, so the coordinator can fix the decision while the incident still waits.
        problems = executor.check_decision(
            ProposedActions.model_validate(incident["proposed"]),
            IncidentText.model_validate(incident["draft"]),
            decision,
        )
        if problems:
            said = "; ".join(problems)
            raise HTTPException(
                status_code=400, detail=said[0].upper() + said[1:] + "."
            )
        errors = await asyncio.wait_for(
            _resume(
                incident_id, incident["interrupt_id"], decision.model_dump(mode="json")
            ),
            timeout=DRAFTING_LEASE_SECONDS,
        )
    if errors:
        logger.error("decision on %s: %s", incident_id, errors)
    return _incident_view(store.get_incident(incident_id))


@app.get("/desk/incidents/{incident_id}/trace", dependencies=[Depends(_verify_caller)])
async def desk_trace(incident_id: str) -> dict:
    """The incident run's trajectory, step by step, from its session."""
    incident = store.incidents.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"No incident {incident_id}")
    runner = _incident_runner()
    session = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id=incident.get("user_id") or DESK_USER_ID,
        session_id=incident.get("session_id") or incident_id,
    )
    if session is None:
        raise HTTPException(
            status_code=404, detail=f"No session for {incident_id} on this service"
        )
    return {
        "incident_id": incident_id,
        "session_id": session.id,
        "steps": trace.steps(session.events),
    }


@app.post("/desk/tasks/{task_id}/verdict", dependencies=[Depends(_verify_caller)])
async def desk_verdict(task_id: str, verdict: ShelfVerdict) -> dict:
    """A store's shelf verdict for one task, given to the run waiting on it."""
    task = store.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"No task {task_id}")
    incident_id = task["incident_id"]
    async with _candidate_locks[incident_id]:
        if store.tasks[task_id]["status"] != "open":
            raise HTTPException(
                status_code=409, detail=f"{task_id} is {store.tasks[task_id]['status']}"
            )
        errors = await _resume(
            incident_id, f"verify:{task_id}", verdict.model_dump(mode="json")
        )
    if errors:
        logger.error("verdict on %s: %s", task_id, errors)
    return _incident_view(store.get_incident(incident_id))


@app.post("/desk/memory/retry", dependencies=[Depends(_verify_caller)])
def desk_memory_retry(limit: int | None = Query(default=None, ge=1)) -> dict:
    """Failed observations generated again from the facts their links kept, oldest first, at most limit of them."""
    links = learn.retry(store, limit)
    return {
        "retried": len(links),
        "generated": sum(link["status"] == "generated" for link in links),
        "errors": sorted({link["error"] for link in links if link["error"]}),
        "still_failed": sum(
            link["status"] == "failed" for link in store.memory_links.values()
        ),
    }


def _memory_name(memory_id: str) -> str:
    engine = learn.engine_name()
    if not engine:
        raise HTTPException(status_code=503, detail="No Memory Bank is configured.")
    if not memory_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail=f"Not a memory id: {memory_id}")
    return f"{engine}/memories/{memory_id}"


@app.get("/desk/memories", dependencies=[Depends(_verify_caller)])
def desk_memories() -> dict:
    """Every observation with its source incidents and promotion state, and whether promotion is available."""
    reason = promote.unavailable_reason()
    return {
        "observations": promote.observations(store),
        "promotion": {"available": reason is None, "reason": reason},
    }


@app.delete("/desk/memories/{memory_id}", dependencies=[Depends(_verify_caller)])
def desk_memory_delete(memory_id: str, actor: str = Query(min_length=1)) -> dict:
    name = _memory_name(memory_id)
    try:
        return promote.delete_observation(store, name, actor)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.post("/desk/memories/{memory_id}/promote", dependencies=[Depends(_verify_caller)])
def desk_memory_promote(memory_id: str, promotion: Promotion) -> dict:
    """Opens the pull request that makes this observation a verified note in knowledge/learned/."""
    name = _memory_name(memory_id)
    try:
        gh = promote.github()
    except promote.PromotionUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if not promote.linked(store, name):
        raise HTTPException(
            status_code=404, detail=f"No observation {memory_id} the desk generated"
        )
    try:
        fact = promotion.text or learn.memories().get(name=name).fact
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"Memory Bank could not read {memory_id}: {e}"
        ) from e
    if not fact:
        raise HTTPException(status_code=404, detail=f"Observation {memory_id} is empty")
    try:
        return promote.promote(
            store,
            name,
            fact,
            promotion.actor,
            promotion.stale_after,
            gh,
            knowledge.knowledge_version(),
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/internal/promotions/settle", dependencies=[Depends(_verify_caller)])
def promotions_settle(commit: DeployedCommit) -> dict:
    """Called by the build after a deploy: merged and deployed promotions delete their memory."""
    try:
        gh = promote.github()
    except promote.PromotionUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return promote.settle(store, commit.deployed_sha, gh)


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
