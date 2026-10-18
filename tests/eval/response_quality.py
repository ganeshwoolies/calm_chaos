"""Local LLM-as-judge for `custom_response_quality` (see eval_config.yaml)."""

import threading

from google import genai
from google.genai import types
from pydantic import BaseModel

_local = threading.local()


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def _client() -> genai.Client:
    """One client per grading thread.

    The eval SDK grades cases on its own thread pool; this initialization runs once
    per thread. Avoids creating a new client for each eval case, which would re-do
    ADC and the TLS handshake every time. Each thread gets its own client, because
    google-auth freezes the SSL context after the first connection when a client
    certificate is present.
    """
    client = getattr(_local, "client", None)
    if client is None:
        # The Gemini platform, with Application Default Credentials.
        client = _local.client = genai.Client()
    return client


def evaluate(instance):
    reference = instance.get("reference")
    rubric = (
        "The agent is a retail product-safety desk. The prompt is an incident candidate; the final response is "
        "the incident card shown to a coordinator before approval, and the trace holds the evidence and the "
        "proposed actions the drafter received. Grade the card on a 1-5 scale (1 poor, 5 excellent): every "
        "store id, batch or lot code and figure appears in the evidence or the proposed actions (any invented "
        "identifier or figure caps the score at 2); the narrative states what happened, the scale, and what "
        "approval will do; considerations raise only real doubts; a customer message, when present, is plain, "
        "names the product and batch, says what to do and how to get a refund, and contains no order numbers "
        "or promises beyond the refund; the text describes the proposed actions without changing them; the text may "
        "draw on the verified playbook in the trace but never contradicts the proposed actions or the policy."
    )
    if reference:
        rubric += (
            " The response should agree with the expected answer below; penalize "
            "factual disagreement with it."
        )
    prompt = (
        f"You are an expert QA evaluator for an enterprise AI assistant. {rubric}\n"
        f"User Prompt: {instance.get('prompt', '')}\n"
        f"Final Response: {instance.get('response', '')}\n"
    )
    if reference:
        prompt += f"Expected Answer (ground truth): {reference}\n"
    prompt += f"Full Agent Trace: {instance.get('agent_data', '')}\n"

    response = _client().models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,  # deterministic grading
            response_mime_type="application/json",
            response_schema=_Verdict,  # guaranteed schema-valid JSON
        ),
    )
    verdict = response.parsed
    if verdict is None:  # model returned nothing usable
        return {"score": 0, "explanation": response.text or ""}
    return {"score": max(1, min(5, verdict.score)), "explanation": verdict.explanation}
