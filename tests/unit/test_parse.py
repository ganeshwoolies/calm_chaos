import base64
import json

from google.genai import types

from app.nodes import parse_candidate


def _run(text: str) -> list:
    return list(
        parse_candidate(
            types.Content(role="user", parts=[types.Part.from_text(text=text)])
        )
    )


def test_bare_candidate() -> None:
    events = _run('{"candidate_id": "recall:yoghurt_listeria", "kind": "recall"}')
    assert events[-1].output == {
        "candidate_id": "recall:yoghurt_listeria",
        "kind": "recall",
    }
    assert events[-1].actions.route == "candidate"


def test_trigger_wrapper() -> None:
    # The candidate push endpoint hands the node {"data": <decoded JSON>, "attributes": {...}}.
    text = json.dumps(
        {
            "data": {"candidate_id": "label:P31007:4c19e2", "kind": "label"},
            "attributes": {},
        }
    )
    assert _run(text)[-1].output["kind"] == "label"


def test_trigger_wrapper_with_json_string_data() -> None:
    inner = json.dumps({"candidate_id": "label:P31007:4c19e2", "kind": "label"})
    assert (
        _run(json.dumps({"data": inner}))[-1].output["candidate_id"]
        == "label:P31007:4c19e2"
    )


def test_not_a_candidate_ends_with_guidance() -> None:
    for text in [
        "Hi!",
        '{"candidate_id": "x", "kind": "complaint"}',
        base64.b64encode(b"junk").decode(),
    ]:
        events = _run(text)
        assert "not an incident candidate" in events[0].content.parts[0].text
        assert events[-1].actions.route == "stop"
