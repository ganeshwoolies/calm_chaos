import json

from app.knowledge import REPO_DIR, load_bundle
from app.policy import build
from data import gen_eval_cases


def _cases() -> list[dict]:
    return json.loads(gen_eval_cases.DATASET.read_text(encoding="utf-8"))["eval_cases"]


def _evidence(candidate_id: str) -> dict:
    for path in (REPO_DIR / "data" / "fixtures" / "evidence").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["candidate_id"] == candidate_id:
            return data
    raise AssertionError(f"no evidence for {candidate_id}")


def test_the_dataset_covers_every_hazard_and_every_label_rule() -> None:
    pol = build(load_bundle(REPO_DIR / "knowledge"), require_usable=False)
    cases = _cases()
    assert len(cases) == 16 and len({c["eval_case_id"] for c in cases}) == 16
    recalls, rules = set(), set()
    for case in cases:
        prompt = json.loads(case["prompt"]["parts"][0]["text"])
        evidence = _evidence(prompt["candidate_id"])
        assert case["reference"]["response"]["parts"][0]["text"]
        if prompt["kind"] == "recall":
            recalls.add(evidence["hazard_type"])
        else:
            rules |= {f["rule"] for c in evidence["checks"] for f in c["findings"]}
    hazards_with_playbooks = {h.id for h in pol.taxonomy.hazard_types if h.playbook}
    assert recalls == hazards_with_playbooks
    assert rules == {r.id for r in pol.labels.rules}


def test_the_generated_cases_are_in_sync() -> None:
    pol = build(load_bundle(REPO_DIR / "knowledge"), require_usable=False)
    for path, text in gen_eval_cases.stand_ins(pol).items():
        assert path.read_text(encoding="utf-8") == text, f"{path.name} is out of date"
    assert gen_eval_cases.DATASET.read_text(encoding="utf-8") == gen_eval_cases.dataset(
        pol
    )
