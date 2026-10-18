import re
from typing import get_args

import pytest

from app import policy
from app.actions import propose
from app.knowledge import load_bundle
from app.schemas import Severity
from tests.knowledge_copy import REPO_BUNDLE, copy_bundle, edit_concept


@pytest.fixture
def repo_policy() -> policy.Policy:
    """The repository's values whatever their review state: these tests pin the numbers, not the verification."""
    return policy.build(load_bundle(REPO_BUNDLE), require_usable=False)


def test_values_are_the_design_section_12_values(repo_policy) -> None:
    p = repo_policy
    assert p.recall.severity_by_hazard == {
        "microbial": "critical",
        "allergen": "critical",
        "electrical_fire": "critical",
        "choking": "critical",
        "injury": "high",
        "chemical": "high",
        "foreign_matter": "high",
        "spoilage": "medium",
        "quality_only": "low",
    }
    targets = {
        s: (t.customers_messaged, t.shelves_clear)
        for s, t in p.recall.targets_minutes.items()
    }
    assert targets == {
        "critical": (30, 60),
        "high": (120, 240),
        "medium": (1440, 1440),
        "low": (None, None),
    }
    assert p.recall.checkout_block_severities == ["critical"]
    assert p.recall.store_action_severities == ["critical", "high", "medium"]
    assert p.recall.checkout_block_drop_needs_reason is True
    assert (p.recall.exposure_days, p.recall.order_lookback_days) == (30, 30)
    assert (
        p.match.barcode_first,
        p.match.top_k,
        p.match.max_distance,
        p.match.ambiguity_gap,
    ) == (True, 5, 0.25, 0.05)
    assert p.match.require_model_confirmation is True
    assert p.labels.min_legibility == 0.6
    assert (
        p.labels.catalogue_match.max_distance,
        p.labels.catalogue_match.same_size_required,
    ) == (0.20, True)
    assert (
        p.labels.targets_minutes["critical"].holds_verified,
        p.labels.targets_minutes["critical"].listing_fixed,
    ) == (60, 120)
    assert len(p.labels.rules) == 8
    assert p.handling.dismiss_suppress_hours == 24


def test_code_severities_are_the_taxonomy(repo_policy) -> None:
    assert set(get_args(Severity)) == set(repo_policy.severity_order)
    assert repo_policy.max_severity(["low", "critical", "high"]) == "critical"


def test_fixture_findings_agree_with_the_label_rules(
    repo_policy, dinosaur, muesli
) -> None:
    """Fixture findings stand in for diff_label's output, which takes severity and actions from the rules."""
    for evidence in (dinosaur, muesli):
        for finding in (f for c in evidence.checks for f in c.findings):
            rule = repo_policy.label_rule(finding.rule)
            assert finding.severity == repo_policy.finding_severity(finding)
            assert finding.actions == list(rule.actions)
            assert (
                finding.hazard_type
                == repo_policy.finding_hazard(finding)
                == evidence.hazard_type
            )


def test_a_value_changes_in_the_bundle_only(tmp_path, yoghurt) -> None:
    root = copy_bundle(tmp_path / "knowledge")
    edit_concept(
        root,
        policy.RECALL,
        targets_minutes={
            "critical": {"customers_messaged": 30, "shelves_clear": 45},
            "high": {"customers_messaged": 120, "shelves_clear": 240},
            "medium": {"customers_messaged": 1440, "shelves_clear": 1440},
            "low": {"customers_messaged": None, "shelves_clear": None},
        },
    )
    assert propose(yoghurt, policy.build(load_bundle(root))).targets.shelf_minutes == 45


def test_a_hazard_outside_the_taxonomy_stops_the_proposal(yoghurt, pol) -> None:
    yoghurt.hazard_type = "radiation"
    with pytest.raises(
        ValueError, match=re.escape("not in /policy/hazard-taxonomy.md")
    ):
        propose(yoghurt, pol)


def test_a_draft_policy_stops_the_run(tmp_path) -> None:
    root = copy_bundle(tmp_path / "knowledge")
    edit_concept(root, policy.LABELS, status="draft")
    with pytest.raises(
        policy.PolicyUnavailable,
        match=re.escape("label-rules.md cannot be used: status is draft"),
    ):
        policy.build(load_bundle(root))


def test_the_excerpt_names_its_concepts(pol) -> None:
    assert policy.RECALL in pol.as_text("recall") and "within 60 min" in pol.as_text(
        "recall"
    )
    assert policy.LABELS in pol.as_text(
        "label"
    ) and "button battery: critical" in pol.as_text("label")
