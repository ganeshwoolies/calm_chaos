"""Model Armor screening of the drafters' prompts and responses, through ADK's ModelArmorPlugin.

The plugin screens the drafter's user message, which carries the evidence and with it every untrusted text the drafter
reads (notice extracts, label reads), and the draft the model returns. The system instruction is the governed bundle,
the actions code proposed and observations the executor assembled, and is not screened.

Each verdict is kept in state under SCREEN_KEY by direction: passed, blocked (with the filters that matched), or
unscreened when the call failed. A block leaves the drafter with no text, so the draft never reaches the coordinator and
validate_and_persist decides what follows. Templates come from MODEL_ARMOR_PROMPT_TEMPLATE and
MODEL_ARMOR_RESPONSE_TEMPLATE; with neither set nothing is screened, so tests and local runs make no calls.
"""

import contextvars
import os
from collections.abc import Awaitable
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.integrations.model_armor import ModelArmorConfig, ModelArmorPlugin
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.cloud import modelarmor_v1
from google.genai import types

from app import bq

SCREEN_KEY = "screen"

# What the screening call inside the running callback returned; the base plugin keeps only whether to block.
_seen: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "psd_screen_seen", default=None
)


def matched_filters(result: modelarmor_v1.SanitizationResult) -> list[str]:
    """Names of the filters whose result, at any depth, says MATCH_FOUND."""
    results = (
        modelarmor_v1.SanitizationResult.to_dict(
            result, use_integers_for_enums=False
        ).get("filter_results")
        or {}
    )

    def found(value: Any) -> bool:
        if isinstance(value, dict):
            return value.get("match_state") == "MATCH_FOUND" or any(
                found(v) for v in value.values()
            )
        if isinstance(value, list):
            return any(found(v) for v in value)
        return False

    return sorted(name for name, r in results.items() if found(r))


def blocked(screen: dict[str, Any], direction: str) -> bool:
    return (screen.get(direction) or {}).get("verdict") == "blocked"


class DraftScreen(ModelArmorPlugin):
    """ModelArmorPlugin that records every verdict in state and answers a block with no text."""

    async def _sanitize_user_prompt(
        self, text: str, template_name: str
    ) -> modelarmor_v1.SanitizationResult:
        return await _observe(super()._sanitize_user_prompt(text, template_name))

    async def _sanitize_model_response(
        self, text: str, template_name: str
    ) -> modelarmor_v1.SanitizationResult:
        return await _observe(super()._sanitize_model_response(text, template_name))

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        _seen.set(None)
        response = await super().before_model_callback(
            callback_context=callback_context, llm_request=llm_request
        )
        return _settle(callback_context, "prompt", response)

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        _seen.set(None)
        response = await super().after_model_callback(
            callback_context=callback_context, llm_response=llm_response
        )
        return _settle(callback_context, "response", response)


async def _observe(
    call: Awaitable[modelarmor_v1.SanitizationResult],
) -> modelarmor_v1.SanitizationResult:
    try:
        result = await call
    except Exception as e:
        _seen.set({"verdict": "unscreened", "reason": f"{type(e).__name__}: {e}"[:300]})
        raise
    if result.invocation_result != modelarmor_v1.InvocationResult.SUCCESS:
        _seen.set(
            {
                "verdict": "unscreened",
                "reason": f"invocation result {result.invocation_result.name}",
                "filters": matched_filters(result),
            }
        )
    else:
        _seen.set({"verdict": "passed", "filters": matched_filters(result)})
    return result


def _settle(
    callback_context: CallbackContext, direction: str, response: LlmResponse | None
) -> LlmResponse | None:
    seen = _seen.get()
    if seen is None:
        return response
    was_blocked = bool(
        response and (response.custom_metadata or {}).get("model_armor_blocked")
    )
    verdicts = dict(callback_context.state.get(SCREEN_KEY) or {})
    verdicts[direction] = {**seen, "verdict": "blocked"} if was_blocked else seen
    callback_context.state[SCREEN_KEY] = verdicts
    if not was_blocked:
        return response
    # Blank text: the drafter's schema then yields no output instead of failing, so the block is not retried as an
    # error and validate_and_persist reads the verdict from state.
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=" ")]),
        custom_metadata=response.custom_metadata,
    )


def template(variable: str) -> str | None:
    """The full name of the template the variable names, in the desk's project and region."""
    template_id = os.environ.get(variable)
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not (template_id and project):
        return None
    return f"projects/{project}/locations/{bq.location()}/templates/{template_id}"


def plugins() -> list[ModelArmorPlugin]:
    prompt = template("MODEL_ARMOR_PROMPT_TEMPLATE")
    response = template("MODEL_ARMOR_RESPONSE_TEMPLATE")
    if not (prompt or response):
        return []
    return [
        DraftScreen(
            config=ModelArmorConfig(
                prompt_template_name=prompt,
                response_template_name=response,
                # A Model Armor outage must not stop a recall being drafted; the verdict records it as unscreened.
                block_on_screening_failure=False,
            )
        )
    ]
