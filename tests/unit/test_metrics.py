"""The scoreboard: tiles from the bundle's metrics, numbers only from attested computations, one run shared a minute."""

import pytest
from fastapi.testclient import TestClient

from api import main, metrics
from app import attest
from app.knowledge import load_bundle
from tests.knowledge_copy import copy_bundle, edit_concept

FAILS = "/computations/published-vs-landed.md"


def _metrics() -> list:
    bundle = load_bundle()
    return sorted(
        (c for c in bundle.concepts.values() if c.type == "Metric"),
        key=lambda c: c.meta["order"],
    )


def test_every_metric_has_its_attested_computation_beside_it() -> None:
    bundle = load_bundle()
    found = _metrics()
    assert [m.meta["order"] for m in found] == list(range(1, 11))
    for m in found:
        computation = bundle.get(m.meta["computation"])
        assert computation is not None and computation.type == "Attested Computation"
        assert computation.title == m.title and computation.meta["parameters"] == []
        sql = (bundle.root / computation.meta["computation"].lstrip("/")).read_text(
            encoding="utf-8"
        )
        assert f" AS {m.meta['headline']}" in sql, m.path


@pytest.fixture
def runs(monkeypatch) -> list:
    """Every computation the scoreboard runs; published-vs-landed fails its attestation."""
    calls: list = []

    def run(concept, params, used_by, **kwargs):
        calls.append(concept)
        if concept == FAILS:
            raise attest.AttestationFailed(f"{concept} failed attestation: SQL differs")
        return attest.Receipt(
            receipt_id=f"rcpt-{len(calls):04d}",
            concept=concept,
            knowledge_version="v",
            params=params,
            job_id="job",
            executed_sql="",
            result=[{"median_minutes": 4.5, "notices": 3}],
            attested=True,
            reason=None,
            used_by=used_by,
            created_at="2026-10-18T00:00:00+00:00",
        )

    monkeypatch.setattr(attest, "run_attested", run)
    monkeypatch.setattr(metrics, "_cache", {"at": 0.0, "board": None})
    return calls


def test_a_tile_shows_its_receipt_and_one_that_fails_a_dash(runs) -> None:
    tiles = metrics.scoreboard()["tiles"]
    assert [t["title"] for t in tiles][:2] == [
        "Minutes to candidate",
        "Minutes to approve",
    ]
    (failed,) = [t for t in tiles if t["computation"] == FAILS]
    assert "rows" not in failed and "SQL differs" in failed["unavailable"]
    shown = [t for t in tiles if t["computation"] != FAILS]
    assert all(t["receipt_id"].startswith("rcpt-") and t["rows"] for t in shown)


def test_an_unreviewed_metric_runs_nothing(runs, tmp_path, monkeypatch) -> None:
    root = copy_bundle(tmp_path / "knowledge")
    edit_concept(root, "/metrics/stores-verified.md", status="draft", verified=None)
    monkeypatch.setenv("PSD_KNOWLEDGE_DIR", str(root))
    tiles = metrics.scoreboard()["tiles"]
    (waiting,) = [t for t in tiles if t["metric"] == "/metrics/stores-verified.md"]
    assert waiting["unavailable"].startswith("awaiting review")
    assert "/computations/stores-verified.md" not in runs


def test_viewers_share_one_run_a_minute(runs) -> None:
    metrics.scoreboard()
    metrics.scoreboard()
    assert len(runs) == 10


def test_the_scoreboard_is_public(runs, monkeypatch) -> None:
    monkeypatch.setenv("PSD_DESK_PASSCODE", "lark-2026")
    browser = TestClient(main.app, client=("203.0.113.9", 50000))
    board = browser.get("/metrics")
    assert board.status_code == 200 and len(board.json()["tiles"]) == 10
    page = browser.get("/desk")
    assert "Scoreboard" in page.text and 'href="/metrics"' in page.text
