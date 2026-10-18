"""Schema metric: the last draft the drafter wrote is an IncidentText. Score 1.0 or 0.0.

Checked without importing the app, so the metric runs wherever the eval runs: the draft must parse as a JSON object with
the required IncidentText fields, of the right kinds.
"""

import json

REQUIRED = {
    "title": str,
    "narrative": str,
    "evidence": list,
    "considerations": list,
    "vendor_case_body": str,
    "qa_alert": str,
}


def evaluate(instance):
    data = instance.get("agent_data") or {}
    if isinstance(data, str):
        data = json.loads(data or "{}")
    drafts = [
        part.get("text")
        for turn in data.get("turns") or []
        for event in turn.get("events") or []
        if str(event.get("author", "")).endswith("_drafter")
        for part in (event.get("content") or {}).get("parts") or []
        if part.get("text")
    ]
    if not drafts:
        return {"score": 0.0, "explanation": "no draft in the trace"}
    try:
        draft = json.loads(drafts[-1])
    except ValueError as e:
        return {"score": 0.0, "explanation": f"the last draft is not JSON: {e}"}
    wrong = [
        field
        for field, kind in REQUIRED.items()
        if not isinstance(draft.get(field), kind)
        or (kind is str and not draft.get(field))
    ]
    if wrong:
        return {
            "score": 0.0,
            "explanation": "missing or wrong fields: " + ", ".join(wrong),
        }
    return {"score": 1.0, "explanation": "the last draft is a complete IncidentText"}
