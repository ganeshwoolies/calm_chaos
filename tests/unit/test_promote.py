import base64
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import fast_api_app as agents_app
from app import learn, memory, promote
from app.knowledge import REPO_DIR, load_bundle
from app.store import LocalStore, store
from tools.okf_validate import validate

ENGINE = "projects/p/locations/us-central1/reasoningEngines/42"
AT = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
STALE = AT + timedelta(days=180)
SUPPLIER = {"supplier_id": "SUP-019"}


class FakeGitHub:
    """The calls promote makes, on an in-memory repository with one base branch."""

    def __init__(self, files: dict[str, str] | None = None):
        self.branches = {"main": "sha-main"}
        self.base = dict(files or {})
        self.writes: dict[str, dict[str, str]] = {}
        self.pulls: dict[int, dict] = {}
        self.labels: dict[int, list[str]] = {}
        self.auto: list[str] = []
        self.ancestors: set[tuple[str, str]] = set()

    def file(self, path, ref):
        text = (
            self.base.get(path) if ref == "main" else self.writes.get(ref, {}).get(path)
        )
        return (text, f"sha:{path}") if text is not None else None

    def branch_sha(self, branch):
        return self.branches[branch]

    def create_branch(self, branch, sha):
        assert branch not in self.branches
        self.branches[branch] = sha
        self.writes[branch] = {}

    def put_file(self, path, text, message, branch, sha):
        assert sha == (f"sha:{path}" if path in self.base else None)
        self.writes[branch][path] = text

    def open_pull(self, head, base, title, body):
        number = len(self.pulls) + 1
        self.pulls[number] = {
            "number": number,
            "node_id": f"PR_{number}",
            "html_url": f"https://github.com/o/r/pull/{number}",
            "head": head,
            "base": base,
            "title": title,
            "body": body,
            "state": "open",
            "merged": False,
            "merge_commit_sha": None,
        }
        return self.pulls[number]

    def label(self, number, labels):
        self.labels[number] = labels

    def auto_merge(self, node_id):
        self.auto.append(node_id)

    def pull(self, number):
        return self.pulls[number]

    def is_ancestor(self, sha, of):
        return (sha, of) in self.ancestors


class Bank:
    """Memory Bank's memories client, as promotion and the Learned tab use it."""

    def __init__(self):
        self.held = {}
        self.deleted = []

    def add(self, memory_id, fact, scope):
        name = f"{ENGINE}/memories/{memory_id}"
        self.held[name] = SimpleNamespace(
            name=name,
            fact=fact,
            scope=scope,
            topics=[],
            update_time=AT,
            expire_time=None,
        )
        return name

    def list(self, *, name):
        return list(self.held.values())

    def get(self, *, name):
        return self.held[name]

    def delete(self, *, name):
        self.deleted.append(name)
        self.held.pop(name, None)


@pytest.fixture
def bank(monkeypatch) -> Bank:
    fake = Bank()
    monkeypatch.setenv("GOOGLE_CLOUD_AGENT_ENGINE_ID", "42")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    monkeypatch.setattr(learn, "memories", lambda: fake)
    return fake


def _linked(
    s: LocalStore, bank: Bank, memory_id: str, scope: dict, incidents: list[str]
) -> str:
    name = bank.add(
        memory_id,
        "Brightway Toys had a missing button battery warning on lot L2026-0311",
        scope,
    )
    for incident_id in incidents:
        s.incidents[incident_id] = {
            "incident_id": incident_id,
            "kind": "label",
            "hazard_type": "injury",
            "supplier_id": "SUP-019",
            "supplier_name": "Brightway Toys",
            "product_id": "P50211",
            "product_name": "Little Explorers Light-Up Dinosaur",
            "approved_at": "2026-10-16T10:00:00+00:00",
        }
        s.link_memory(
            {
                "link_id": learn.link_id(incident_id, scope),
                "incident_id": incident_id,
                "scope": scope,
                "facts": [],
                "source": "approved_incident",
                "memory_names": [name],
                "status": "generated",
                "promotion_pr": None,
            }
        )
    return name


def _bundle_with(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "knowledge"
    shutil.copytree(REPO_DIR / "knowledge", root)
    for path, text in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def test_a_promotion_opens_one_pull_request_on_learned_only(bank, tmp_path) -> None:
    s = LocalStore()
    name = _linked(s, bank, "m1", SUPPLIER, ["inc-a", "inc-b"])
    gh = FakeGitHub(
        {
            f"{promote.LEARNED}/index.md": (
                REPO_DIR / "knowledge/learned/index.md"
            ).read_text(encoding="utf-8")
        }
    )
    result = promote.promote(
        s,
        name,
        bank.get(name=name).fact,
        "amy@calmchaos.test",
        STALE,
        gh,
        "local-x",
        AT,
    )

    assert result["pr"] == 1 and not result["already_open"]
    (branch,) = list(gh.writes)
    written = gh.writes[branch]
    assert all(p.startswith("knowledge/learned/") for p in written)
    note = written["knowledge/learned/suppliers/SUP-019.md"]
    assert "type: Supplier Note" in note and 'by: "human:amy@calmchaos.test"' in note
    assert "[^inc-a][^inc-b]" in note and "resource: incidents/inc-a" in note
    assert gh.labels[1] == ["promotion"] and gh.auto == ["PR_1"]
    assert gh.pulls[1]["base"] == "main"
    assert all(link["promotion_pr"] == 1 for link in s.memory_links.values())
    assert s.audit[-1]["action"] == "promote_observation"

    # What the pull request writes keeps the bundle valid.
    root = _bundle_with(tmp_path, written)
    assert validate(root) == []
    concept = load_bundle(root).get("/learned/suppliers/SUP-019.md")
    assert concept is not None and concept.usable(AT)


def test_promoting_again_while_open_is_a_no_op(bank) -> None:
    s = LocalStore()
    name = _linked(s, bank, "m1", SUPPLIER, ["inc-a"])
    gh = FakeGitHub()
    promote.promote(s, name, "Fact", "amy", STALE, gh, "v", AT)
    again = promote.promote(
        s, name, "Fact", "amy", STALE, gh, "v", AT + timedelta(minutes=1)
    )
    assert again["already_open"] and again["pr"] == 1 and len(gh.pulls) == 1


def test_a_second_promotion_appends_to_the_note_on_the_base_branch(
    bank, tmp_path
) -> None:
    s = LocalStore()
    first = _linked(s, bank, "m1", SUPPLIER, ["inc-a"])
    gh = FakeGitHub()
    promote.promote(s, first, "First observation", "amy", STALE, gh, "v", AT)
    gh.base.update(gh.writes[next(iter(gh.writes))])  # merged

    second = _linked(s, bank, "m2", SUPPLIER, ["inc-c"])
    for link in s.memory_links.values():
        if second in link["memory_names"]:
            link["promotion_pr"] = None
    promote.promote(
        s, second, "Second observation", "raj", STALE, gh, "v", AT + timedelta(hours=1)
    )
    note = list(gh.writes.values())[-1]["knowledge/learned/suppliers/SUP-019.md"]
    assert (
        "First observation.[^inc-a]" in note and "Second observation.[^inc-c]" in note
    )
    assert note.count("human:") == 2
    assert note.count("[^inc-a]:") == 1 and note.count("[^inc-c]:") == 1
    root = _bundle_with(tmp_path, list(gh.writes.values())[-1])
    assert validate(root) == []


def test_coordinator_practice_becomes_one_playbook_note(bank, tmp_path) -> None:
    s = LocalStore()
    name = _linked(s, bank, "m9", {"playbook": "psd"}, ["inc-a", "inc-b"])
    gh = FakeGitHub()
    result = promote.promote(
        s,
        name,
        "Coordinators edited the QA alert before approving label incidents",
        "amy",
        STALE,
        gh,
        "v",
        AT,
    )
    assert result["path"] == "knowledge/learned/playbook/coordinator-practice.md"
    written = list(gh.writes.values())[-1]
    note = written[result["path"]]
    assert "type: Playbook" in note and "# Trigger" in note and "# Steps" in note
    assert validate(_bundle_with(tmp_path, written)) == []


def test_a_past_stale_after_is_refused(bank) -> None:
    s = LocalStore()
    name = _linked(s, bank, "m1", SUPPLIER, ["inc-a"])
    with pytest.raises(ValueError):
        promote.promote(
            s, name, "Fact", "amy", AT - timedelta(days=1), FakeGitHub(), "v", AT
        )


def test_settle_deletes_merged_and_deployed_and_returns_closed(bank) -> None:
    s = LocalStore()
    merged = _linked(s, bank, "m1", SUPPLIER, ["inc-a"])
    closed = _linked(s, bank, "m2", {"product_id": "P50211"}, ["inc-b"])
    waiting = _linked(s, bank, "m3", {"store_id": "S012"}, ["inc-c"])
    gh = FakeGitHub()
    for n in (merged, closed, waiting):
        promote.promote(s, n, "Fact", "amy", STALE, gh, "v", AT)
    gh.pulls[1].update(state="closed", merged=True, merge_commit_sha="abc1234")
    gh.ancestors.add(("abc1234", "def5678"))
    gh.pulls[2].update(state="closed", merged=False)

    assert promote.settle(s, "def5678", gh) == {
        "settled": 1,
        "returned": 1,
        "waiting": 1,
    }
    assert bank.deleted == [merged]
    by_memory = {link["memory_names"][0]: link for link in s.memory_links.values()}
    assert by_memory[merged]["status"] == "promoted"
    assert by_memory[merged]["promoted_to"] == "knowledge/learned/suppliers/SUP-019.md"
    assert (
        by_memory[closed]["promotion_pr"] is None
        and by_memory[closed]["status"] == "generated"
    )
    assert by_memory[waiting]["promotion_pr"] == 3


def test_a_merge_not_yet_deployed_waits(bank) -> None:
    s = LocalStore()
    name = _linked(s, bank, "m1", SUPPLIER, ["inc-a"])
    gh = FakeGitHub()
    promote.promote(s, name, "Fact", "amy", STALE, gh, "v", AT)
    gh.pulls[1].update(state="closed", merged=True, merge_commit_sha="abc1234")
    assert promote.settle(s, "0000000", gh)["waiting"] == 1 and bank.deleted == []


def test_retrieval_leaves_out_an_observation_awaiting_its_merge(
    bank, monkeypatch
) -> None:
    s = LocalStore()
    name = _linked(s, bank, "m1", SUPPLIER, ["inc-a"])
    found = SimpleNamespace(memory=bank.get(name=name), distance=0.1)
    monkeypatch.setattr(memory, "_ask", lambda *a: [found])
    assert [o.name for o in memory.retrieve(s, [SUPPLIER], "q")[0]] == [name]
    promote.promote(s, name, "Fact", "amy", STALE, FakeGitHub(), "v", AT)
    assert memory.retrieve(s, [SUPPLIER], "q")[0] == []


def test_delete_drops_the_memory_unless_a_promotion_is_open(bank) -> None:
    s = LocalStore()
    name = _linked(s, bank, "m1", SUPPLIER, ["inc-a"])
    other = _linked(s, bank, "m2", SUPPLIER, ["inc-b"])
    promote.promote(s, other, "Fact", "amy", STALE, FakeGitHub(), "v", AT)
    with pytest.raises(ValueError):
        promote.delete_observation(s, other, "amy")
    assert promote.delete_observation(s, name, "amy")["deleted"] == name
    (link,) = [
        link for link in s.memory_links.values() if link["incident_id"] == "inc-a"
    ]
    assert link["status"] == "deleted" and link["memory_names"] == []


def test_the_learned_list_joins_memory_bank_with_the_links(bank) -> None:
    s = LocalStore()
    name = _linked(s, bank, "m1", SUPPLIER, ["inc-a", "inc-b"])
    bank.add("m7", "An observation from before the links", {"store_id": "S001"})
    promote.promote(s, name, "Fact", "amy", STALE, FakeGitHub(), "v", AT)
    by_id = {o["id"]: o for o in promote.observations(s)}
    assert by_id["m1"]["incidents"] == ["inc-a", "inc-b"]
    assert by_id["m1"]["promotion"]["pr"] == 1
    assert by_id["m7"]["incidents"] == [] and by_id["m7"]["promotion"] is None


def test_the_routes_say_why_promotion_is_unavailable(bank, monkeypatch) -> None:
    monkeypatch.delenv("PSD_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("PSD_GITHUB_REPO", "o/r")
    client = TestClient(agents_app.app, client=("127.0.0.1", 50000))
    name = _linked(store, bank, "m1", SUPPLIER, ["inc-a"])
    listed = client.get("/desk/memories").json()
    assert listed["promotion"] == {
        "available": False,
        "reason": "no GitHub token is configured (PSD_GITHUB_TOKEN)",
    }
    assert [o["name"] for o in listed["observations"]] == [name]
    resp = client.post(
        "/desk/memories/m1/promote",
        json={"actor": "amy", "stale_after": STALE.isoformat()},
    )
    assert resp.status_code == 503 and "PSD_GITHUB_TOKEN" in resp.json()["detail"]
    assert (
        client.delete("/desk/memories/m1", params={"actor": "amy"}).status_code == 200
    )
    assert bank.deleted == [name]


def test_the_rest_client_sends_what_github_expects() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        if (
            request.url.path.endswith("/contents/knowledge/learned/index.md")
            and request.method == "GET"
        ):
            return httpx.Response(
                200,
                json={
                    "content": base64.b64encode(b"# Learned\n").decode(),
                    "sha": "s1",
                },
            )
        if request.url.path.endswith("/compare/abc...def"):
            return httpx.Response(200, json={"status": "ahead"})
        if request.url.path == "/graphql":
            return httpx.Response(200, json={"data": {}})
        return httpx.Response(404, json={})

    gh = promote.RestGitHub("o/r", "t", transport=httpx.MockTransport(handler))
    assert gh.file("knowledge/learned/index.md", "main") == ("# Learned\n", "s1")
    assert gh.file("knowledge/learned/suppliers/x.md", "main") is None
    assert gh.is_ancestor("abc", "def")
    gh.auto_merge("PR_1")
    assert json.loads(seen[-1][2])["variables"] == {"id": "PR_1"}
