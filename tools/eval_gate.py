"""The drafting eval's bars (design section 18), checked on a grade results file. Exits 1 when any bar is missed.

    uv run python tools/eval_gate.py [artifacts/grade_results/results_<time>.json]

Without a path it reads the newest file in artifacts/grade_results. The bars: rubric mean at least 4 of 5, trajectory
1.0 (every step in order, nothing executed before approval, and so no invented identifiers, which the workflow redrafts
and finally fails on), every draft a complete IncidentText, and no case that errored.
"""

import argparse
import json
import sys
from pathlib import Path

RESULTS_DIR = Path("artifacts") / "grade_results"
BARS = {
    "custom_response_quality": 4.0,
    "trajectory": 1.0,
    "draft_schema": 1.0,
}


def check(results: dict) -> list[str]:
    """One line per missed bar; empty when the eval passes."""
    summary = {m["metric_name"]: m for m in results.get("summary_metrics") or []}
    problems = []
    for name, bar in BARS.items():
        metric = summary.get(name)
        if metric is None:
            problems.append(f"{name}: not in the results")
            continue
        if metric.get("num_cases_error"):
            problems.append(f"{name}: {metric['num_cases_error']} case(s) errored")
        mean = metric.get("mean_score")
        if mean is None or mean < bar:
            problems.append(f"{name}: mean {mean} is below {bar}")
    return problems


def newest(directory: Path = RESULTS_DIR) -> Path:
    files = sorted(directory.glob("results_*.json"))
    if not files:
        raise SystemExit(f"no results_*.json in {directory}")
    return files[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", nargs="?", type=Path)
    args = parser.parse_args()
    path = args.results or newest()
    problems = check(json.loads(path.read_text(encoding="utf-8")))
    for problem in problems:
        print(problem)
    print(
        f"{path}: "
        + ("eval gate passed" if not problems else f"{len(problems)} bar(s) missed")
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
