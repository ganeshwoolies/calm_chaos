from datetime import UTC, datetime

import pytest

from app import knowledge
from app.knowledge import Concept, PolicyUnavailable, load_bundle, typed_values
from tests.knowledge_copy import edit_concept

RECALL = "/policy/recall-response.md"
PLAYBOOK = "/playbooks/microbial.md"


def _concept(**meta) -> Concept:
    return Concept(path="/x.md", meta={"type": "Reference", **meta}, body="")


def test_a_bare_verified_mapping_is_one_event() -> None:
    c = _concept(verified={"by": "human:reviewer-1", "at": "2026-10-01T00:00:00Z"})
    assert [v.by for v in c.verified] == ["human:reviewer-1"]


def test_absent_status_means_stable() -> None:
    assert _concept().status == "stable"


def test_trust_tiers() -> None:
    assert _concept().trust_tier == "unverified"
    assert (
        _concept(
            verified=[{"by": "psd/promote@1", "at": "2026-10-01T00:00:00Z"}]
        ).trust_tier
        == "machine-confirmed"
    )
    assert (
        _concept(
            verified=[{"by": "human:reviewer-1", "at": "2026-10-01T00:00:00Z"}]
        ).trust_tier
        == "human-reviewed"
    )


def test_stale_from_the_instant_itself() -> None:
    c = _concept(stale_after="2026-10-01T00:00:00Z")
    assert not c.is_stale(datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC))
    assert c.is_stale(datetime(2026, 10, 1, tzinfo=UTC))


@pytest.mark.parametrize(
    ("meta", "reason"),
    [
        ({"status": "draft"}, "status is draft"),
        (
            {"verified": [{"by": "psd/promote@1", "at": "2026-10-01T00:00:00Z"}]},
            "not verified by a human",
        ),
        (
            {"verified": [{"by": "human:reviewer-1"}], "stale_after": "2026-10-01"},
            "not an ISO 8601 instant",
        ),
        (
            {
                "verified": [{"by": "human:reviewer-1"}],
                "stale_after": "2026-01-01T00:00:00Z",
            },
            "stale since",
        ),
    ],
)
def test_unusable_reasons(meta, reason) -> None:
    assert reason in (_concept(**meta).unusable_reason() or "")


def test_unknown_keys_and_types_are_kept(tmp_path) -> None:
    (tmp_path / "odd.md").write_text(
        "---\ntype: Recipe\nflavour: mild\n---\nbody\n", encoding="utf-8"
    )
    (tmp_path / "notype.md").write_text("---\ntitle: no type\n---\n", encoding="utf-8")
    bundle = load_bundle(tmp_path)
    assert bundle.get("/odd.md").meta["flavour"] == "mild"
    assert "/notype.md" in bundle.unreadable


def test_knowledge_version_follows_every_byte(verified_bundle, monkeypatch) -> None:
    before = knowledge.knowledge_version()
    log = verified_bundle / "log.md"
    log.write_text(log.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert knowledge.knowledge_version() != before
    monkeypatch.setenv("PSD_KNOWLEDGE_VERSION", "3f2c1a9")
    assert knowledge.knowledge_version() == "3f2c1a9"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": "draft"}, "status is draft"),
        (
            {"verified": [{"by": "psd/promote@1", "at": "2026-10-01T00:00:00Z"}]},
            "not verified by a human",
        ),
        ({"stale_after": "2026-01-01T00:00:00Z"}, "stale since"),
        ({"exposure_days": -1}, "invalid values"),
        ({"severity_by_hazard": {"microbial": "urgent"}}, "not in the taxonomy"),
    ],
)
def test_policy_is_refused_when_not_usable(tmp_path, changes, message) -> None:
    from tests.knowledge_copy import copy_bundle

    root = copy_bundle(tmp_path / "knowledge")
    edit_concept(root, RECALL, **changes)
    with pytest.raises(PolicyUnavailable, match=message):
        typed_values(load_bundle(root), [RECALL, "/policy/hazard-taxonomy.md"])


def test_only_usable_knowledge_reaches_the_prompt(verified_bundle, tmp_path) -> None:
    shown = knowledge.for_incident(PLAYBOOK, "SUP-004", "P48812", ["S001"])
    assert [c.path for c in shown] == [PLAYBOOK]
    block = knowledge.render(shown)
    assert block.startswith("<KNOWLEDGE verified>") and "human:test-reviewer" in block

    edit_concept(verified_bundle, PLAYBOOK, status="draft")
    try:
        assert knowledge.for_incident(PLAYBOOK, "SUP-004", "P48812", ["S001"]) == []
        assert knowledge.render([]).startswith("none")
    finally:
        edit_concept(verified_bundle, PLAYBOOK, status="stable")


def test_promoted_notes_are_found_by_scope(verified_bundle) -> None:
    note = verified_bundle / "learned" / "suppliers" / "SUP-004.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ntype: Supplier Note\ntitle: Morrowdale\nstatus: stable\n"
        "verified: [{by: 'human:reviewer-1', at: '2026-10-01T00:00:00Z'}]\nstale_after: 2099-01-01T00:00:00Z\n---\n"
        "Two microbial recalls this year.\n",
        encoding="utf-8",
    )
    try:
        paths = [c.path for c in knowledge.for_incident(None, "SUP-004", "P48812", [])]
        assert paths == ["/learned/suppliers/SUP-004.md"]
    finally:
        note.unlink()
        note.parent.rmdir()
