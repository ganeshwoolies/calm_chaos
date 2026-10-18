"""An incident run's trajectory for the coordinator: its session events as one short line per step.

A step is an event that carries something: a delivery or a reply, a node's route or state change, text a node wrote, a
draft, a pause or an error. Checkpoints and the outputs a resumed run replays carry nothing and are left out. State is
shown by its keys only, so evidence and instructions never reach the page; a redraft shows its reason and a draft its
Model Armor verdicts.
"""

import json
from datetime import UTC, datetime
from typing import Any

from google.adk.events import Event

from app import screening
from app.executor import DEMO_NOTICE

REQUEST_INPUT = "adk_request_input"
_LIMIT = 240


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _LIMIT else text[: _LIMIT - 1] + "…"


def _headline(text: str) -> str:
    """The first line that says something: the fiction notice heads every card and is skipped."""
    for line in text.splitlines():
        line = line.strip().replace("**", "")
        if line and line != DEMO_NOTICE:
            return _clip(line)
    return ""


def _node(event: Event) -> str:
    last = (event.node_info.path or "").rsplit("/", 1)[-1]
    return last.split("@", 1)[0] if last else event.author


def _reply(response: Any) -> str:
    """What a coordinator or a store answered at a pause."""
    raw = (response.response or {}).get("result")
    try:
        answer = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except ValueError:
        return _clip(str(raw))
    if "decision" in answer:
        edits = [
            k for k in ("remove_stores", "pull_stores", "add_stores") if answer.get(k)
        ]
        if answer.get("checkout_block") is not None:
            edits.append("checkout_block")
        edits += [f"text.{k}" for k, v in (answer.get("text") or {}).items() if v]
        reason = f"; reason: {answer['reason']}" if answer.get("reason") else ""
        changed = f" with edits to {', '.join(edits)}" if edits else ""
        return f"{answer['decision']} by {answer.get('actor', 'coordinator')}{changed}{reason}"
    if "verdict" in answer:
        note = f" ({answer['note']})" if answer.get("note") else ""
        return f"{answer['verdict']}{note}"
    return _clip(json.dumps(answer))


def _delivery(text: str) -> str:
    try:
        data = json.loads(text).get("data") or {}
        if isinstance(data, str):
            data = json.loads(data)
        return f"delivered candidate {data['candidate_id']} ({data.get('kind', '?')})"
    except (ValueError, AttributeError, KeyError, TypeError):
        return _clip(text)


def _draft(event: Event, text: str) -> str:
    try:
        title = json.loads(text).get("title") or ""
    except (ValueError, AttributeError):
        title = ""
    usage = event.usage_metadata
    tokens = (
        f" ({usage.prompt_token_count} tokens in, {usage.candidates_token_count} out)"
        if usage and usage.prompt_token_count is not None
        else ""
    )
    return f"draft: {_clip(title)}{tokens}" if title else f"no draft{tokens}"


def _screening(delta: dict[str, Any]) -> str:
    verdicts = delta.get(screening.SCREEN_KEY) or {}
    parts = [
        f"{direction} {v.get('verdict')}"
        + (f" ({', '.join(v['filters'])})" if v.get("filters") else "")
        for direction, v in verdicts.items()
    ]
    return f"; Model Armor: {', '.join(parts)}" if parts else ""


def step(event: Event) -> dict[str, Any] | None:
    """One event as a step, or None when it carries nothing to show."""
    parts = (event.content.parts if event.content else None) or []
    calls = [p.function_call for p in parts if p.function_call]
    replies = [p.function_response for p in parts if p.function_response]
    text = "".join(p.text for p in parts if p.text and not p.thought).strip()
    delta = event.actions.state_delta or {}
    route = event.actions.route
    if event.error_code:
        kind, summary = (
            "error",
            _clip(f"{event.error_code}: {event.error_message or ''}"),
        )
    elif event.author == "user" and replies:
        kind, summary = (
            "resume",
            "; ".join(f"{r.id} answered: {_reply(r)}" for r in replies),
        )
    elif event.author == "user" and text:
        kind, summary = "delivery", _delivery(text)
    elif any(c.name == REQUEST_INPUT for c in calls):
        kind = "pause"
        summary = "paused for " + ", ".join(
            str(c.id) for c in calls if c.name == REQUEST_INPUT
        )
    elif event.author.endswith("_drafter") and (text or screening.SCREEN_KEY in delta):
        kind, summary = "draft", _draft(event, text) + _screening(delta)
    elif text:
        kind, summary = "note", _headline(text)
    elif route is not None or delta:
        kind = "step"
        bits = [f"route {route}"] if route is not None else []
        if delta.get("validation_error"):
            bits.append(_clip(str(delta["validation_error"])).rstrip("."))
        keys = sorted(k for k in delta if not k.startswith("_"))
        if keys:
            bits.append("state " + ", ".join(keys))
        summary = "; ".join(bits)
    else:
        return None
    return {
        "at": datetime.fromtimestamp(event.timestamp, UTC).isoformat(),
        "node": _node(event),
        "kind": kind,
        "summary": summary,
    }


def steps(events: list[Event]) -> list[dict[str, Any]]:
    """Every event's step; the pauses one node makes together read as one step."""
    out: list[dict[str, Any]] = []
    waiting: list[str] = []
    for event in events:
        s = step(event)
        if s is None:
            continue
        if s["kind"] == "pause":
            ids = s["summary"].removeprefix("paused for ").split(", ")
            if out and out[-1]["kind"] == "pause" and out[-1]["node"] == s["node"]:
                waiting += ids
                out[-1]["summary"] = _waiting(waiting)
                continue
            waiting = ids
        out.append(s)
    return out


def _waiting(ids: list[str]) -> str:
    if len(ids) <= 2:
        return "paused for " + ", ".join(ids)
    return f"paused for {len(ids)} replies: {ids[0]}, {ids[1]} and {len(ids) - 2} more"
