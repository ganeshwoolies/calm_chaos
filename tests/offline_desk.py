"""psd-agents in process for tests: the drafter's model faked, sessions in memory, candidates pushed as Pub/Sub would."""

import base64
import json

import httpx
from fastapi.testclient import TestClient
from google.adk.artifacts import InMemoryArtifactService
from google.adk.models import Gemini, LlmResponse
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from app import fast_api_app
from app.agent import app as adk_app
from app.schemas import IncidentText


def desk(monkeypatch, draft: IncidentText) -> TestClient:
    """The agents app on loopback, whose drafter always returns draft."""

    async def generate(self, llm_request, stream=False):
        yield LlmResponse(
            content=types.Content(
                role="model", parts=[types.Part(text=draft.model_dump_json())]
            ),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=6100, candidates_token_count=420
            ),
        )

    monkeypatch.setattr(Gemini, "generate_content_async", generate)
    runner = Runner(
        app=adk_app,
        session_service=InMemorySessionService(),
        artifact_service=InMemoryArtifactService(),
    )
    monkeypatch.setattr(fast_api_app, "_incident_runner", lambda: runner)
    return TestClient(fast_api_app.app, client=("127.0.0.1", 50000))


def push(
    client: TestClient, candidate_id: str, kind: str = "recall", message_id: str = "m1"
) -> httpx.Response:
    data = base64.b64encode(
        json.dumps({"candidate_id": candidate_id, "kind": kind}).encode()
    ).decode()
    return client.post(
        "/trigger/candidates",
        json={
            "message": {"data": data, "messageId": message_id, "attributes": {}},
            "subscription": "projects/p/subscriptions/psd-candidates-agent",
        },
    )
