import importlib.util
import json
from pathlib import Path

from tools import eval_gate

EVAL = Path(__file__).resolve().parents[1] / "eval"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, EVAL / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trajectory = _load("trajectory")
draft_schema = _load("draft_schema")

DRAFT = {
    "title": "Morrowdale Vanilla Yoghurt 1kg, batch B2026-091: possible Listeria",
    "narrative": "The regulator recalled batch B2026-091.",
    "evidence": ["14 stores hold the batch"],
    "considerations": [],
    "vendor_case_body": "P48812, batch B2026-091.",
    "qa_alert": "Critical recall.",
}


def _run(*extra: dict, draft: dict | None = None, pause: bool = True) -> dict:
    """A recall run as the eval trace records it, up to the approval pause."""
    events = [
        {"author": "product_safety_desk", "state_delta": {"candidate": {}}},
        {
            "author": "product_safety_desk",
            "state_delta": {"evidence": {}, "incident_id": "inc-1"},
        },
        {
            "author": "product_safety_desk",
            "content": {
                "parts": [
                    {
                        "text": "Proposed by policy for recall:x (severity critical):\n- pull"
                    }
                ]
            },
        },
        {"author": "product_safety_desk", "state_delta": {"proposed": {}}},
        {
            "author": "product_safety_desk",
            "state_delta": {"skill_instructions": "...", "knowledge_block": "..."},
        },
        {
            "author": "recall_drafter",
            "state_delta": {"draft": {}},
            "content": {"parts": [{"text": json.dumps(draft or DRAFT)}]},
        },
        {"author": "product_safety_desk", "state_delta": {"validation_error": ""}},
        *extra,
    ]
    if pause:
        events.append(
            {
                "author": "product_safety_desk",
                "content": {
                    "parts": [
                        {
                            "function_call": {
                                "name": "adk_request_input",
                                "id": "approve:inc-1",
                            }
                        }
                    ]
                },
            }
        )
    return {"agent_data": {"turns": [{"events": events}]}}


def test_a_run_that_pauses_after_drafting_scores_one() -> None:
    assert trajectory.evaluate(_run())["score"] == 1.0
    assert draft_schema.evaluate(_run())["score"] == 1.0


def test_the_trace_may_arrive_as_a_json_string() -> None:
    run = _run()
    run["agent_data"] = json.dumps(run["agent_data"])
    assert trajectory.evaluate(run)["score"] == 1.0


def test_the_graded_trace_keeps_only_events_with_content() -> None:
    run = _run()
    events = run["agent_data"]["turns"][0]["events"]
    run["agent_data"]["turns"][0]["events"] = [e for e in events if e.get("content")]
    assert trajectory.evaluate(run)["score"] == 1.0


def test_a_run_without_the_proposal_scores_zero() -> None:
    run = _run()
    events = run["agent_data"]["turns"][0]["events"]
    run["agent_data"]["turns"][0]["events"] = [
        e for e in events if e.get("content") and "Proposed by" not in json.dumps(e)
    ]
    out = trajectory.evaluate(run)
    assert out["score"] == 0.0 and "proposal" in out["explanation"]


def test_a_run_that_never_pauses_scores_zero() -> None:
    out = trajectory.evaluate(_run(pause=False))
    assert out["score"] == 0.0 and "pause" in out["explanation"]


def test_execution_before_approval_scores_zero() -> None:
    out = trajectory.evaluate(
        _run({"author": "product_safety_desk", "state_delta": {"decision": {}}})
    )
    assert out["score"] == 0.0 and "executed before approval" in out["explanation"]


def test_a_redraft_still_counts_as_in_order() -> None:
    second = {
        "author": "recall_drafter",
        "state_delta": {"draft": {}},
        "content": {"parts": [{"text": json.dumps(DRAFT)}]},
    }
    assert trajectory.evaluate(_run(second))["score"] == 1.0


def test_an_incomplete_draft_fails_the_schema() -> None:
    out = draft_schema.evaluate(_run(draft={"title": "x"}))
    assert out["score"] == 0.0 and "narrative" in out["explanation"]


def _results(**means) -> dict:
    return {
        "summary_metrics": [
            {"metric_name": name, "mean_score": mean, "num_cases_error": 0}
            for name, mean in means.items()
        ]
    }


def test_the_gate_holds_every_bar() -> None:
    assert (
        eval_gate.check(
            _results(custom_response_quality=4.6, trajectory=1.0, draft_schema=1.0)
        )
        == []
    )
    missed = eval_gate.check(_results(custom_response_quality=3.9, trajectory=0.94))
    assert [p.split(":")[0] for p in missed] == [
        "custom_response_quality",
        "trajectory",
        "draft_schema",
    ]
