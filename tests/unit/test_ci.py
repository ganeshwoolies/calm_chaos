from pathlib import Path

import yaml

from tools import check_promotion_pr

INFRA = Path(__file__).resolve().parents[2] / "infra"


def test_a_promotion_pull_request_may_change_only_learned() -> None:
    learned = [
        "knowledge/learned/suppliers/SUP-019.md",
        "knowledge/learned/index.md",
        "knowledge/learned/log.md",
    ]
    assert check_promotion_pr.strays("promote/m1-1792", learned) == []
    assert check_promotion_pr.strays(
        "promote/m1-1792", [*learned, "knowledge/policy/recall-response.md"]
    ) == ["knowledge/policy/recall-response.md"]
    # Any other branch is reviewed by its code owners instead.
    assert check_promotion_pr.strays("feature/x", ["app/agent.py"]) == []


def _steps(name: str) -> dict:
    config = yaml.safe_load((INFRA / name).read_text(encoding="utf-8"))
    return {s["id"]: s for s in config["steps"]}


def test_the_main_pipeline_gates_the_deploy() -> None:
    steps = list(_steps("cloudbuild.yaml"))
    assert steps.index("eval-gate") < steps.index("deploy")
    assert steps.index("lint-and-unit-tests") < steps.index("image")
    assert steps[-1] == "settle-promotions"
    assert (
        "PSD_EVIDENCE_SOURCE=fixtures" in _steps("cloudbuild.yaml")["eval-gate"]["env"]
    )


def test_the_pull_request_check_runs_the_promotion_rule() -> None:
    script = _steps("cloudbuild-pr.yaml")["knowledge-lint-and-unit-tests"]["args"][-1]
    assert "tools/check_promotion_pr.py" in script and "pytest tests/unit" in script
