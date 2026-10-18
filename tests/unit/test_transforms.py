import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.agent import MODEL
from app.knowledge import REPO_DIR, load_bundle
from app.policy import build
from tools import gen_transforms

TRANSFORMS = REPO_DIR / "transforms"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")

EVENT = {
    "event_id": "evt_1",
    "source": "recall",
    "feed": "test",
    "guid": "test:fsanz:yoghurt_listeria:1",
    "title": "Morrowdale Vanilla Yoghurt 1kg",
    "url": "https://storage.cloud.google.com/b/test/notices/n.html",
    "published_at": "2026-10-17T00:00:00+00:00",
    "text": "x" * 13000,
    "screen": {"flagged": False, "filters": []},
}
EXTRACT = {
    "product_name": "Vanilla Yoghurt",
    "brand": "Morrowdale",
    "sizes": ["1kg"],
    "batch_codes": ["B2026-091"],
    "category": "food",
    "hazard_type": "microbial",
    "summary": "Possible Listeria in one batch.",
    "confidence": 0.9,
}


def _run(tmp_path: Path, file: str, function: str, message: dict) -> dict:
    """Runs one transform under Node, as Pub/Sub would call it, and returns the message it hands on."""
    script = tmp_path / "run.js"
    script.write_text(
        (TRANSFORMS / file).read_text(encoding="utf-8")
        + f"\nconst out = {function}({json.dumps(message)}, {{}});\n"
        + "process.stdout.write(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    done = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=30
    )
    if done.returncode:
        raise RuntimeError(done.stderr)
    return json.loads(done.stdout)


def _request(tmp_path: Path) -> dict:
    out = _run(
        tmp_path,
        "shape_request.js",
        "shapeRequest",
        {"data": json.dumps(EVENT), "attributes": {"source": "recall"}},
    )
    return {**out, "data": json.loads(out["data"])}


def _flatten(tmp_path: Path, model_output: object) -> tuple[dict, dict]:
    request = _request(tmp_path)["data"]
    out = _run(
        tmp_path,
        "flatten_result.js",
        "flattenResult",
        {
            "data": json.dumps(
                {"original_message": request, "model_output": model_output}
            )
        },
    )
    return json.loads(out["data"]), out["attributes"]


@needs_node
def test_the_request_carries_the_event_inside_the_model_call(tmp_path) -> None:
    out = _request(tmp_path)
    request = out["data"]
    assert request["model"] == f"google/{MODEL}"
    assert request["response_format"] == {"type": "json_object"}
    system, user = request["messages"]
    assert system["role"] == "system" and "untrusted" in system["content"]
    carried = json.loads(user["content"])
    assert carried["event_id"] == "evt_1" and carried["guid"] == EVENT["guid"]
    assert carried["submitted_at"] == EVENT["published_at"]
    assert len(carried["text"]) == 12000 and carried["screen_flagged"] is False
    assert out["attributes"] == {"source": "recall", "event_id": "evt_1"}


@needs_node
def test_an_event_from_an_unknown_source_fails_the_publish(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="unknown source"):
        _run(
            tmp_path,
            "shape_request.js",
            "shapeRequest",
            {"data": json.dumps({**EVENT, "source": "other"}), "attributes": {}},
        )


@needs_node
def test_a_fenced_model_answer_becomes_the_tagged_row_with_policy_severity(
    tmp_path,
) -> None:
    answer = {
        "choices": [{"message": {"content": f"```json\n{json.dumps(EXTRACT)}\n```"}}]
    }
    row, attributes = _flatten(tmp_path, answer)
    assert row["event_id"] == "evt_1" and row["guid"] == EVENT["guid"]
    assert row["product_name"] == "Morrowdale Vanilla Yoghurt"
    assert (row["category"], row["hazard_type"], row["severity"]) == (
        "food",
        "microbial",
        "critical",
    )
    assert json.loads(row["recall_extract"])["batch_codes"] == ["B2026-091"]
    assert row["tag_error"] is None and row["model"] == MODEL
    assert attributes == {
        "source": "recall",
        "severity": "critical",
        "hazard_type": "microbial",
        "event_id": "evt_1",
    }


@needs_node
def test_a_model_answer_that_will_not_parse_lands_with_tag_error(tmp_path) -> None:
    row, _ = _flatten(tmp_path, {"choices": [{"message": {"content": "not json"}}]})
    assert row["tag_error"]
    assert (row["category"], row["hazard_type"], row["severity"]) == (
        "other",
        "quality_only",
        "low",
    )
    assert row["product_name"] == EVENT["title"] and row["recall_extract"] == "{}"


@needs_node
def test_a_hazard_outside_the_taxonomy_is_quality_only(tmp_path) -> None:
    answer = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({**EXTRACT, "hazard_type": "radiation"})
                }
            }
        ]
    }
    row, _ = _flatten(tmp_path, answer)
    assert (row["hazard_type"], row["severity"]) == ("quality_only", "low")


def test_the_generated_blocks_match_the_bundle() -> None:
    pol = build(load_bundle(REPO_DIR / "knowledge"), require_usable=False)
    for name, block in gen_transforms.blocks(pol).items():
        path = TRANSFORMS / name
        assert gen_transforms.render(path, block) == path.read_text(encoding="utf-8"), (
            f"run uv run python tools/gen_transforms.py ({name} is out of date)"
        )


def test_the_gcloud_files_chain_inference_then_flatten_on_the_global_endpoint() -> None:
    files = {
        p.name: yaml.safe_load(t) for p, t in gen_transforms.gcloud_files("p").items()
    }
    (topic,) = files["topic-transforms.yaml"]
    assert topic["javascriptUdf"]["functionName"] == "shapeRequest"
    inference, flatten = files["subscription-transforms.yaml"]
    assert (
        inference["aiInference"]["endpoint"]
        == f"projects/p/locations/global/publishers/google/models/{MODEL}"
    )
    assert flatten["javascriptUdf"]["functionName"] == "flattenResult"
    assert flatten["javascriptUdf"]["code"] == (
        TRANSFORMS / "flatten_result.js"
    ).read_text(encoding="utf-8")


def test_matching_confirms_with_the_desk_model_and_embeds_both_sides_alike() -> None:
    match = (REPO_DIR / "sql" / "match_recalls.sql").read_text(encoding="utf-8")
    embed = (REPO_DIR / "sql" / "embed_catalogue.sql").read_text(encoding="utf-8")
    assert re.findall(r"AI\.IF\(.*?endpoint => '([^']+)'", match, re.DOTALL) == [MODEL]
    spec = r"endpoint => '([^']+)',\s*model_params => JSON '([^']+)'"
    assert re.findall(spec, match) == re.findall(spec, embed) != []
