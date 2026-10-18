"""Model Armor screening of notice text at ingestion.

A flagged notice is still extracted, because the regulator's facts are needed; the flag travels with it to the
coordinator. Screening never blocks ingestion: a failed call leaves the flag unknown (None) and records why.
"""

import logging
import os
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from google.api_core.client_options import ClientOptions
from google.cloud import modelarmor_v1

from app import bq

logger = logging.getLogger(__name__)

NOTICE_TEMPLATE = os.environ.get("MODEL_ARMOR_NOTICE_TEMPLATE", "psd-notice-screen")


@dataclass(frozen=True)
class Screen:
    flagged: bool | None
    filters: list[str] = field(default_factory=list)
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"flagged": self.flagged, "filters": self.filters, "reason": self.reason}


@cache
def _client() -> modelarmor_v1.ModelArmorClient:
    # Templates and sanitize calls live on the regional endpoint only; the global one serves floor settings.
    return modelarmor_v1.ModelArmorClient(
        transport="rest",
        client_options=ClientOptions(
            api_endpoint=f"modelarmor.{bq.location()}.rep.googleapis.com"
        ),
    )


def _matched(results: dict[str, Any]) -> list[str]:
    """Names of the filters whose result, at any depth, says MATCH_FOUND."""

    def found(value: Any) -> bool:
        if isinstance(value, dict):
            return value.get("match_state") == "MATCH_FOUND" or any(
                found(v) for v in value.values()
            )
        if isinstance(value, list):
            return any(found(v) for v in value)
        return False

    return sorted(name for name, result in results.items() if found(result))


def screen(text: str) -> Screen:
    name = f"projects/{bq.client().project}/locations/{bq.location()}/templates/{NOTICE_TEMPLATE}"
    try:
        response = _client().sanitize_user_prompt(
            request=modelarmor_v1.SanitizeUserPromptRequest(
                name=name, user_prompt_data=modelarmor_v1.DataItem(text=text)
            )
        )
    except Exception as e:
        logger.warning("Model Armor screening failed for %s: %s", name, e)
        return Screen(flagged=None, reason=f"{type(e).__name__}: {e}"[:300])
    result = modelarmor_v1.SanitizeUserPromptResponse.to_dict(
        response, use_integers_for_enums=False
    ).get("sanitization_result", {})
    filters = _matched(result.get("filter_results") or {})
    return Screen(
        flagged=result.get("filter_match_state") == "MATCH_FOUND" or bool(filters),
        filters=filters,
    )
