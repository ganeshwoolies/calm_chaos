"""Trajectory metric: the incident run took the workflow's steps in order and executed nothing before approval.

The run is a deterministic graph, so the steps are checked exactly. The grader passes only events that carry content,
so the steps every trace shows are the policy's proposal ("Proposed by policy for ..."), at least one draft, and the
approval pause as the last event. When the trace also keeps its state-only events (the candidate, the evidence and the
drafting context, as a full trace does), those must come first, in order. A draft that cites an identifier or figure
the evidence lacks is redrafted and, after two retries, fails the run before the pause, so a run that scores 1.0 also
has no invented identifiers. Score 1.0 or 0.0.
"""

import json

CONTENT_STEPS = ("proposal", "draft", "pause")
STATE_STEPS = {
    "candidate": "candidate",
    "evidence": "evidence",
    "context": "skill_instructions",
}
ORDER = ("candidate", "evidence", "proposal", "context", "draft", "pause")
PROPOSAL = "Proposed by policy for "
# State keys and calls that only appear once a decision has been executed.
AFTER_APPROVAL_KEYS = {"decision", "current_task_id"}


def _events(instance) -> list[dict]:
    data = instance.get("agent_data") or {}
    if isinstance(data, str):
        data = json.loads(data or "{}")
    return [e for turn in data.get("turns") or [] for e in turn.get("events") or []]


def _parts(event: dict) -> list[dict]:
    return (event.get("content") or {}).get("parts") or []


def _call(part: dict) -> dict | None:
    return part.get("function_call") or part.get("functionCall")


def evaluate(instance):
    events = _events(instance)
    seen: dict[str, int] = {}
    problems = []
    for i, event in enumerate(events):
        keys = set((event.get("state_delta") or {}).keys())
        for step, key in STATE_STEPS.items():
            if key in keys:
                seen.setdefault(step, i)
        author = str(event.get("author", ""))
        if author.endswith("_drafter") and ("draft" in keys or _parts(event)):
            seen.setdefault("draft", i)
        for part in _parts(event):
            if str(part.get("text") or "").startswith(PROPOSAL):
                seen.setdefault("proposal", i)
            call = _call(part)
            if not call:
                continue
            call_id = str(call.get("id") or "")
            if call.get("name") == "adk_request_input" and call_id.startswith(
                "approve:"
            ):
                seen["pause"] = i
            elif call_id.startswith("verify:"):
                problems.append(f"a shelf check was asked before approval ({call_id})")
        if keys & AFTER_APPROVAL_KEYS:
            problems.append(
                f"executed before approval: {sorted(keys & AFTER_APPROVAL_KEYS)}"
            )
    missing = [s for s in CONTENT_STEPS if s not in seen]
    if any(s in seen for s in STATE_STEPS):
        missing += [s for s in STATE_STEPS if s not in seen]
    if missing:
        problems.append("missing steps: " + ", ".join(missing))
    present = [s for s in ORDER if s in seen]
    if [seen[s] for s in present] != sorted(seen[s] for s in present):
        problems.append(
            "steps out of order: " + " -> ".join(sorted(present, key=lambda s: seen[s]))
        )
    if "pause" in seen and seen["pause"] != len(events) - 1:
        problems.append("events follow the approval pause")
    if problems:
        return {"score": 0.0, "explanation": "; ".join(problems)}
    return {
        "score": 1.0,
        "explanation": "proposal, draft, then the approval pause, with nothing executed before it",
    }
