"""Model Armor screening of the drafter, run through the whole workflow with a fake model and a fake Model Armor."""

import base64
import json

import pytest
from fastapi.testclient import TestClient
from google.adk.apps import App, ResumabilityConfig
from google.adk.artifacts import InMemoryArtifactService
from google.adk.integrations.model_armor import ModelArmorConfig
from google.adk.models import Gemini, LlmResponse
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.cloud import modelarmor_v1 as ma
from google.genai import types

from app import fast_api_app, screening
from app.agent import root_agent
from app.store import incident_id_for, store

TEMPLATES = "projects/p/locations/us-central1/templates"
YOGHURT = "recall:yoghurt_listeria"
FOUND = ma.FilterMatchState.MATCH_FOUND

_MATCHES = {
    "pi_and_jailbreak": lambda: ma.FilterResult(
        pi_and_jailbreak_filter_result=ma.PiAndJailbreakFilterResult(match_state=FOUND)
    ),
    "sdp": lambda: ma.FilterResult(
        sdp_filter_result=ma.SdpFilterResult(
            inspect_result=ma.SdpInspectResult(match_state=FOUND)
        )
    ),
}


def _result(matched: list[str]) -> ma.SanitizationResult:
    return ma.SanitizationResult(
        filter_match_state=FOUND if matched else ma.FilterMatchState.NO_MATCH_FOUND,
        invocation_result=ma.InvocationResult.SUCCESS,
        filter_results={name: _MATCHES[name]() for name in matched},
    )


class FakeArmor:
    """Model Armor's async client. Each plan entry is the filters that match, or an exception the call raises."""

    def __init__(self, prompt=(), response=()):
        self.plans = {"prompt": list(prompt), "response": list(response)}
        self.screened: dict[str, list[str]] = {"prompt": [], "response": []}

    def _answer(self, direction: str, text: str):
        self.screened[direction].append(text)
        planned = self.plans[direction].pop(0) if self.plans[direction] else []
        if isinstance(planned, Exception):
            raise planned
        return _result(planned)

    async def sanitize_user_prompt(self, request):
        return ma.SanitizeUserPromptResponse(
            sanitization_result=self._answer("prompt", request.user_prompt_data.text)
        )

    async def sanitize_model_response(self, request):
        return ma.SanitizeModelResponseResponse(
            sanitization_result=self._answer(
                "response", request.model_response_data.text
            )
        )


@pytest.fixture
def model(monkeypatch, recall_draft) -> list:
    """The drafter's model: every call returns the consistent yoghurt draft and records the request."""
    requests = []

    async def generate(self, llm_request, stream=False):
        requests.append(llm_request)
        yield LlmResponse(
            content=types.Content(
                role="model", parts=[types.Part(text=recall_draft.model_dump_json())]
            )
        )

    monkeypatch.setattr(Gemini, "generate_content_async", generate)
    return requests


def _desk(monkeypatch, armor: FakeArmor) -> TestClient:
    plugin = screening.DraftScreen(
        config=ModelArmorConfig(
            prompt_template_name=f"{TEMPLATES}/psd-prompt-screen",
            response_template_name=f"{TEMPLATES}/psd-response-screen",
            block_on_screening_failure=False,
        ),
        client=armor,
    )
    runner = Runner(
        app=App(
            root_agent=root_agent,
            name="app",
            resumability_config=ResumabilityConfig(is_resumable=True),
            plugins=[plugin],
        ),
        session_service=InMemorySessionService(),
        artifact_service=InMemoryArtifactService(),
    )
    monkeypatch.setattr(fast_api_app, "_incident_runner", lambda: runner)
    return TestClient(fast_api_app.app, client=("127.0.0.1", 50000))


def _push(client: TestClient, message_id: str = "m1"):
    data = base64.b64encode(
        json.dumps({"candidate_id": YOGHURT, "kind": "recall"}).encode()
    ).decode()
    return client.post(
        "/trigger/candidates",
        json={
            "message": {"data": data, "messageId": message_id, "attributes": {}},
            "subscription": "projects/p/subscriptions/psd-candidates-agent",
        },
    )


INCIDENT = incident_id_for(YOGHURT)


def test_without_templates_nothing_is_screened(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_ARMOR_PROMPT_TEMPLATE", raising=False)
    monkeypatch.delenv("MODEL_ARMOR_RESPONSE_TEMPLATE", raising=False)
    assert screening.plugins() == []


def test_templates_are_named_in_the_desks_project_and_region(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    monkeypatch.setenv("PSD_REGION", "us-central1")
    monkeypatch.setenv("MODEL_ARMOR_PROMPT_TEMPLATE", "psd-prompt-screen")
    monkeypatch.setenv("MODEL_ARMOR_RESPONSE_TEMPLATE", "psd-response-screen")
    (plugin,) = screening.plugins()
    assert plugin._config.prompt_template_name == f"{TEMPLATES}/psd-prompt-screen"
    assert plugin._config.response_template_name == f"{TEMPLATES}/psd-response-screen"
    assert plugin._config.block_on_screening_failure is False


def test_a_draft_is_screened_once_each_way_and_the_verdicts_kept(
    monkeypatch, model
) -> None:
    armor = FakeArmor()
    r = _push(_desk(monkeypatch, armor))
    assert r.status_code == 200 and r.json()["status"] == "awaiting_approval"
    assert len(model) == 1
    assert [len(armor.screened[d]) for d in ("prompt", "response")] == [1, 1]
    # The evidence is screened, not the system instruction built from the bundle and the proposal.
    assert "B2026-091" in armor.screened["prompt"][0]
    assert "computed by policy" not in armor.screened["prompt"][0]
    assert json.loads(armor.screened["response"][0])["title"].startswith("Morrowdale")
    assert store.incidents[INCIDENT]["screening"] == {
        "prompt": {"verdict": "passed", "filters": []},
        "response": {"verdict": "passed", "filters": []},
    }


def test_a_blocked_prompt_is_never_drafted_or_retried(monkeypatch, model) -> None:
    armor = FakeArmor(prompt=[["pi_and_jailbreak"]])
    client = _desk(monkeypatch, armor)
    r = _push(client)
    assert r.status_code == 200 and r.json()["status"] == "blocked"
    assert model == [] and len(armor.screened["prompt"]) == 1
    incident = store.incidents[INCIDENT]
    assert incident["status"] == "blocked" and incident["proposed"]["store_actions"]
    assert incident["screening"]["prompt"] == {
        "verdict": "blocked",
        "filters": ["pi_and_jailbreak"],
    }
    # A redelivery is acknowledged without a run, so Pub/Sub stops asking.
    again = _push(client, "m2")
    assert again.status_code == 200 and again.json()["status"] == "blocked"
    assert len(armor.screened["prompt"]) == 1
    view = client.get("/desk/incidents").json()[0]
    assert view["status"] == "blocked" and view["card"] is None
    assert view["screening"]["prompt"]["verdict"] == "blocked"


def test_a_blocked_draft_is_redrafted_with_the_reason(monkeypatch, model) -> None:
    armor = FakeArmor(response=[["sdp"]])
    r = _push(_desk(monkeypatch, armor))
    assert r.status_code == 200 and r.json()["status"] == "awaiting_approval"
    assert len(model) == 2
    assert "Model Armor blocked it (sdp)" in model[1].config.system_instruction
    incident = store.incidents[INCIDENT]
    assert incident["redrafts"] == 1
    assert incident["screening"]["response"] == {"verdict": "passed", "filters": []}


def test_a_failed_screening_call_lets_the_draft_go_on_unscreened(
    monkeypatch, model
) -> None:
    armor = FakeArmor(prompt=[RuntimeError("Model Armor unavailable")])
    r = _push(_desk(monkeypatch, armor))
    assert r.status_code == 200 and r.json()["status"] == "awaiting_approval"
    assert len(model) == 1
    prompt = store.incidents[INCIDENT]["screening"]["prompt"]
    assert prompt["verdict"] == "unscreened" and "unavailable" in prompt["reason"]
