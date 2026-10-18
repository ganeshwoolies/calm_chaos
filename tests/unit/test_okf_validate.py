import pytest

from tests.knowledge_copy import REPO_BUNDLE, copy_bundle, edit_concept
from tools.okf_validate import validate

RECALL = "/policy/recall-response.md"
PLAYBOOK = "/playbooks/microbial.md"


def test_the_repository_bundle_is_valid() -> None:
    assert validate(REPO_BUNDLE) == []


def test_a_verified_copy_is_valid(tmp_path) -> None:
    assert validate(copy_bundle(tmp_path / "knowledge")) == []


def _write(root, rel, text) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("break_it", "expected"),
    [
        (
            lambda r: edit_concept(r, PLAYBOOK, type="Recipe"),
            "type 'Recipe' is not one of",
        ),
        (lambda r: edit_concept(r, PLAYBOOK, title=None), "missing title"),
        (
            lambda r: edit_concept(r, RECALL, verified=None),
            "needs a verified entry by a human",
        ),
        (
            lambda r: edit_concept(r, RECALL, stale_after="2027-04-30"),
            "stale_after must be an ISO 8601 instant",
        ),
        (lambda r: edit_concept(r, RECALL, stale_after=None), "missing stale_after"),
        (lambda r: edit_concept(r, RECALL, sources=None), "missing sources"),
        (lambda r: edit_concept(r, RECALL, exposure_days=-3), "exposure_days"),
        (
            lambda r: edit_concept(
                r, RECALL, severity_by_hazard={"microbial": "urgent"}
            ),
            "not in the taxonomy",
        ),
        (
            lambda r: edit_concept(
                r,
                "/policy/label-rules.md",
                rules=[
                    {
                        "id": "x",
                        "condition": "c",
                        "severity": "low",
                        "hazard_type": "allergen",
                        "actions": ["recall"],
                    }
                ],
            ),
            "rules.0.actions.0",
        ),
        (
            lambda r: _write(
                r,
                "playbooks/microbial.md",
                (r / "playbooks/microbial.md")
                .read_text(encoding="utf-8")
                .replace("# Steps", "# Notes"),
            ),
            "needs a '# Steps' section",
        ),
        (
            lambda r: _write(
                r,
                "playbooks/extra.md",
                "---\ntype: Playbook\ntitle: t\ndescription: d\ntags: [x]\nstatus: draft\n---\n# Trigger\n# Steps\n",
            ),
            "not listed in any index.md",
        ),
        (
            lambda r: _write(r, "playbooks/index.md", "---\nokf_version: '0.2'\n---\n"),
            "below the root has no frontmatter",
        ),
        (
            lambda r: _write(r, "log.md", "# Log\n\n## yesterday\n"),
            "not a YYYY-MM-DD date",
        ),
        (
            lambda r: _write(r, "log.md", "# Log\n\n## 2026-10-01\n\n## 2026-10-17\n"),
            "not newest first",
        ),
        (
            lambda r: _write(
                r,
                "index.md",
                (r / "index.md").read_text(encoding="utf-8")
                + "\n* [Gone](policy/gone.md) - x\n",
            ),
            "broken link policy/gone.md",
        ),
        (
            lambda r: _write(
                r,
                "policy/match-rule.md",
                (r / "policy/match-rule.md").read_text(encoding="utf-8")
                + "\nSee [^nowhere].\n",
            ),
            "footnote [^nowhere] cites no source id",
        ),
    ],
)
def test_each_house_rule_fails_on_its_own(tmp_path, break_it, expected) -> None:
    root = copy_bundle(tmp_path / "knowledge")
    break_it(root)
    problems = validate(root)
    assert any(expected in p for p in problems), problems
