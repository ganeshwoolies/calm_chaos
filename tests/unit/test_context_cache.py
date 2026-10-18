"""The app's context cache through ADK's own Gemini model code, with the Gemini client faked: drafting creates no cache."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.adk.artifacts import InMemoryArtifactService
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from app import fast_api_app
from app.agent import app as adk_app
from app.store import incident_id_for, store

YOGHURT = "recall:yoghurt_listeria"


class FakeGenai:
    """A Vertex AI genai client: every draft replies with the next text; creating a cache fails the test."""

    vertexai = True

    def __init__(self, texts: list[str]):
        self.configs: list[types.GenerateContentConfig] = []
        self.caches_created: list[dict] = []
        self._api_client = SimpleNamespace(
            project="p", location="global", _http_options=SimpleNamespace(base_url=None)
        )
        outer = self

        class Models:
            async def generate_content(self, *, model, contents, config):
                outer.configs.append(config)
                return types.GenerateContentResponse(
                    candidates=[
                        types.Candidate(
                            content=types.Content(
                                role="model", parts=[types.Part(text=texts.pop(0))]
                            ),
                            finish_reason=types.FinishReason.STOP,
                        )
                    ],
                    # Past min_tokens, so only the cache's own rules can keep it from being created.
                    usage_metadata=types.GenerateContentResponseUsageMetadata(
                        prompt_token_count=6000,
                        candidates_token_count=400,
                        total_token_count=6400,
                    ),
                )

        class Caches:
            async def create(self, **kwargs):
                outer.caches_created.append(kwargs)
                raise AssertionError("drafting created a context cache")

        self.aio = SimpleNamespace(models=Models(), caches=Caches())


@pytest.fixture
def genai(monkeypatch, recall_draft) -> FakeGenai:
    inconsistent = recall_draft.model_copy(
        update={"narrative": recall_draft.narrative + " Store S999 also reported it."}
    )
    fake = FakeGenai([inconsistent.model_dump_json(), recall_draft.model_dump_json()])
    monkeypatch.setattr(Gemini, "api_client", property(lambda self: fake))
    runner = Runner(
        app=adk_app,
        session_service=InMemorySessionService(),
        artifact_service=InMemoryArtifactService(),
    )
    monkeypatch.setattr(fast_api_app, "_incident_runner", lambda: runner)
    fake.runner = runner
    return fake


def test_a_draft_and_its_redraft_create_no_cache(genai) -> None:
    assert adk_app.context_cache_config.min_tokens == 4096
    data = base64.b64encode(
        json.dumps({"candidate_id": YOGHURT, "kind": "recall"}).encode()
    ).decode()
    r = TestClient(fast_api_app.app, client=("127.0.0.1", 50000)).post(
        "/trigger/candidates",
        json={
            "message": {"data": data, "messageId": "m1", "attributes": {}},
            "subscription": "projects/p/subscriptions/psd-candidates-agent",
        },
    )
    assert r.status_code == 200 and r.json()["status"] == "awaiting_approval"
    assert store.incidents[incident_id_for(YOGHURT)]["redrafts"] == 1
    _, redraft = genai.configs
    assert "S999" in redraft.system_instruction
    # Both requests carried their whole instruction; none was served from a cache.
    assert all(c.cached_content is None and c.system_instruction for c in genai.configs)
    assert genai.caches_created == []
    # ADK's cache manager ran on both drafts and recorded a prefix fingerprint, but no cache.
    session = asyncio.run(
        genai.runner.session_service.get_session(
            app_name="app", user_id="desk", session_id=incident_id_for(YOGHURT)
        )
    )
    cached = [e.cache_metadata for e in session.events if e.cache_metadata]
    assert len(cached) == 2
    assert all(m.fingerprint and m.cache_name is None for m in cached)
