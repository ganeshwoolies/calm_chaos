import itertools
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import learn, memory
from app.store import LocalStore

ENGINE = "projects/p/locations/us-central1/reasoningEngines/42"
NOW = datetime(2026, 10, 17, tzinfo=UTC)


class FakeMemories:
    """Memory Bank's memories client: generate, retrieve and delete, all in memory."""

    def __init__(self):
        self.generated, self.deleted, self.held = [], [], {}
        self.ids = itertools.count(1)
        self.slow_scopes: set[str] = set()
        self.fail_scopes: set[str] = set()

    def generate(self, *, name, direct_memories_source, scope, config):
        if str(scope) in self.fail_scopes:
            raise RuntimeError("Memory Bank unavailable")
        self.generated.append(
            (scope, direct_memories_source["direct_memories"], config)
        )
        made = []
        for fact in direct_memories_source["direct_memories"]:
            mem = SimpleNamespace(
                name=f"{name}/memories/m{next(self.ids)}",
                fact=fact["fact"],
                update_time=NOW,
                create_time=NOW,
            )
            self.held.setdefault(str(scope), []).append(mem)
            made.append(SimpleNamespace(memory=mem, action="CREATED"))
        return SimpleNamespace(response=SimpleNamespace(generated_memories=made))

    def retrieve(
        self,
        *,
        name,
        scope,
        similarity_search_params=None,
        simple_retrieval_params=None,
    ):
        if str(scope) in self.slow_scopes:
            time.sleep(0.5)
        return [
            SimpleNamespace(
                memory=m, distance=0.2 if similarity_search_params else None
            )
            for m in self.held.get(str(scope), [])
        ]

    def delete(self, *, name):
        self.deleted.append(name)
        for held in self.held.values():
            held[:] = [m for m in held if m.name != name]


@pytest.fixture
def bank(monkeypatch) -> FakeMemories:
    fake = FakeMemories()
    monkeypatch.setenv("GOOGLE_CLOUD_AGENT_ENGINE_ID", "42")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    monkeypatch.setattr(learn, "memories", lambda: fake)
    return fake


def _incident(incident_id: str) -> dict:
    return {"incident_id": incident_id, "hazard_type": "microbial"}


def _fact(scope: dict, topic: str, fact: str) -> dict:
    return {"scope": scope, "topic": topic, "fact": fact}


FACTS = [
    _fact(
        {"product_id": "P48812"},
        "product_incident_history",
        "P48812 had a Listeria recall of batch B2026-091.",
    ),
    _fact(
        {"supplier_id": "SUP-004"},
        "supplier_quality_history",
        "SUP-004 had a microbial recall.",
    ),
    _fact(
        {"store_id": "S004"},
        "store_execution_pattern",
        "S004 cleared its shelf at the first check.",
    ),
]


def test_each_scope_is_generated_once_and_linked_to_its_incident(bank) -> None:
    store = LocalStore()
    links = learn.remember(store, _incident("inc-1"), FACTS, "approved_incident")
    assert len(bank.generated) == 3 and {link["status"] for link in links} == {
        "generated"
    }
    _, memories_sent, config = bank.generated[0]
    assert memories_sent[0]["topics"] == [
        {"custom_memory_topic_label": "product_incident_history"}
    ]
    assert config["metadata"]["incident_id"] == {"string_value": "inc-1"}
    assert config["metadata"]["source"] == {"string_value": "approved_incident"}
    assert config["metadata_merge_strategy"] == "MERGE"
    (product_link,) = [
        link
        for link in store.memory_links.values()
        if link["scope"] == {"product_id": "P48812"}
    ]
    assert product_link["memory_names"] == [f"{ENGINE}/memories/m1"]
    assert product_link["facts"] == [
        {"fact": FACTS[0]["fact"], "topic": "product_incident_history"}
    ]


def test_without_an_instance_nothing_is_sent(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_AGENT_ENGINE_ID", raising=False)
    monkeypatch.setattr(
        learn, "memories", lambda: pytest.fail("Memory Bank was called")
    )
    assert (
        learn.remember(LocalStore(), _incident("inc-1"), FACTS, "approved_incident")
        == []
    )
    assert memory.retrieve(LocalStore(), [{"product_id": "P48812"}], "q") == ([], False)


def test_a_failed_generation_is_recorded_and_the_close_goes_on(bank) -> None:
    bank.fail_scopes.add(str({"supplier_id": "SUP-004"}))
    store = LocalStore()
    links = learn.remember(store, _incident("inc-1"), FACTS, "approved_incident")
    failed = [link for link in links if link["status"] == "failed"]
    assert len(failed) == 1 and "unavailable" in failed[0]["error"]


def test_a_retry_generates_failed_links_again_from_their_facts(bank) -> None:
    bank.fail_scopes.update(str(f["scope"]) for f in FACTS)
    store = LocalStore()
    store.incidents["inc-1"] = _incident("inc-1")
    learn.remember(store, _incident("inc-1"), FACTS, "approved_incident")
    bank.fail_scopes.clear()
    first, *_ = sorted(store.memory_links.values(), key=lambda link: link["created_at"])
    (retried,) = learn.retry(store, limit=1)
    assert retried["link_id"] == first["link_id"]
    assert retried["status"] == "generated" and retried["error"] is None
    assert bank.generated[-1][1] == [
        {"fact": f["fact"], "topics": [{"custom_memory_topic_label": f["topic"]}]}
        for f in first["facts"]
    ]
    assert bank.generated[-1][2]["metadata"]["incident_id"] == {"string_value": "inc-1"}
    assert len(learn.retry(store)) == 2
    assert {link["status"] for link in store.memory_links.values()} == {"generated"}
    assert learn.retry(store) == []


def test_a_dismissal_revokes_the_incidents_memories_and_regenerates_the_scope(
    bank,
) -> None:
    store = LocalStore()
    store.incidents["inc-1"] = _incident("inc-1")
    learn.remember(store, _incident("inc-1"), FACTS[:1], "approved_incident")
    learn.remember(
        store,
        _incident("inc-2"),
        [
            _fact(
                {"product_id": "P48812"},
                "product_incident_history",
                "P48812 had a second recall.",
            )
        ],
        "approved_incident",
    )
    deleted = learn.revoke(store, _incident("inc-1"))
    assert deleted == [f"{ENGINE}/memories/m1"]
    assert (
        store.memory_links[learn.link_id("inc-1", {"product_id": "P48812"})]["status"]
        == "revoked"
    )
    regenerated = store.memory_links[learn.link_id("inc-2", {"product_id": "P48812"})]
    assert regenerated["status"] == "generated" and regenerated["memory_names"] == [
        f"{ENGINE}/memories/m3"
    ]


def test_retrieval_scores_skips_pending_promotions_and_renders_with_age(bank) -> None:
    store = LocalStore()
    learn.remember(store, _incident("inc-1"), FACTS, "approved_incident")
    store_link = learn.link_id("inc-1", {"store_id": "S004"})
    store.update_link(store_link, promotion_pr=12)
    scopes = memory.scopes_for("SUP-004", "P48812", ["S004"])
    found, timed_out = memory.retrieve(
        store, scopes, "Morrowdale yoghurt", now=NOW + timedelta(days=3)
    )
    assert not timed_out
    assert {o.fact for o in found} == {FACTS[0]["fact"], FACTS[1]["fact"]}
    assert all(
        o.name not in store.memory_links[store_link]["memory_names"] for o in found
    )
    block = memory.render(found, now=NOW + timedelta(days=3))
    assert block.startswith("<OBSERVATIONS unverified>") and "3 days old" in block


def test_a_slow_scope_is_left_out_within_the_budget(bank, monkeypatch) -> None:
    store = LocalStore()
    learn.remember(store, _incident("inc-1"), FACTS[:2], "approved_incident")
    bank.slow_scopes.add(str({"supplier_id": "SUP-004"}))
    monkeypatch.setenv("PSD_MEMORY_BUDGET_MS", "100")
    found, timed_out = memory.retrieve(
        store, memory.scopes_for("SUP-004", "P48812", []), "q", now=NOW
    )
    assert timed_out and [o.fact for o in found] == [FACTS[0]["fact"]]


def test_warming_reads_the_playbook_scope_once_and_needs_an_engine(
    bank, monkeypatch
) -> None:
    asked = []
    monkeypatch.setattr(memory, "_ask", lambda name, scope, query: asked.append(scope))
    memory.warm()
    assert asked == [{"playbook": "psd"}]
    monkeypatch.delenv("GOOGLE_CLOUD_AGENT_ENGINE_ID")
    memory.warm()
    assert len(asked) == 1


def test_no_observations_render_as_none_yet() -> None:
    assert memory.render([]) == "none yet"
