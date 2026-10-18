"""The scoreboard's computations through run_attested, on a small world whose answers are known.

The world goes into a dataset of its own, made for the module and deleted after it, so rows streamed into psd_test by
other runs cannot change an answer. Times are fixed except the publishing ones, which published-vs-landed reads within
the last two days.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from google.cloud import bigquery

from app import bq
from app.attest import run_attested
from data.load_truth import apply_ddl, load_table
from tests.sql.conftest import require_table

T0 = datetime(2026, 10, 10, tzinfo=UTC)
L0 = datetime(2026, 10, 11, tzinfo=UTC)
RECENT = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
APPROVED = T0 + timedelta(minutes=30)
YOGHURT_CANDIDATE = "recall:aaa111:P48812"
MUESLI_CANDIDATE = "label:P31007:abc123"


def _at(t: datetime, minutes: float = 0) -> str:
    return (t + timedelta(minutes=minutes)).isoformat()


def _version(collection: str, record_id: str, written: datetime, record: dict) -> dict:
    return {
        "collection": collection,
        "record_id": record_id,
        "written_at": written.isoformat(),
        "record": record,
    }


def _world() -> dict[str, list[dict]]:
    yoghurt = {
        "incident_id": "inc-1",
        "candidate_id": YOGHURT_CANDIDATE,
        "kind": "recall",
        "product_id": "P48812",
        "created_at": _at(T0, 17),
        "proposed": {"severity": "critical"},
    }
    muesli = {
        "incident_id": "inc-2",
        "candidate_id": MUESLI_CANDIDATE,
        "kind": "label",
        "product_id": "P31007",
        "created_at": _at(L0, 2),
        "proposed": {"severity": "high"},
    }
    tasks = [
        ("t1", "inc-1", "S001", "verified_clear", 20, None),
        ("t2", "inc-1", "S002", "not_clear", 25, None),
        ("t2-r1", "inc-1", "S002", "verified_clear", 50, "t2"),
        ("t3", "inc-2", "S012", "open", None, None),
    ]
    return {
        "recall_notices": [
            {
                "guid": "FICTIONAL-TEST:fsanz:yoghurt_listeria:1",
                "feed": "test",
                "published_at": _at(T0),
                "first_seen": _at(T0, 10),
                "match_status": "matched",
                "matched_product_id": "P48812",
                "candidate_id": YOGHURT_CANDIDATE,
            },
            {
                "guid": "FICTIONAL-TEST:fsanz:yoghurt_500g_decoy:1",
                "feed": "test",
                "published_at": _at(T0),
                "first_seen": _at(T0, 10),
                "match_status": "not_in_range",
            },
            {
                "guid": "live-notice-1",
                "feed": "fsanz",
                "published_at": _at(T0),
                "first_seen": _at(T0, 12),
                "match_status": "not_in_range",
            },
        ],
        "incident_candidates": [
            {
                "candidate_id": YOGHURT_CANDIDATE,
                "kind": "recall",
                "created_at": _at(T0, 16),
            },
            {
                "candidate_id": MUESLI_CANDIDATE,
                "kind": "label",
                "created_at": _at(L0, 1),
            },
        ],
        "truth_recalls": [
            {
                "scenario": "yoghurt_listeria",
                "product_id": "P48812",
                "expected_match_status": "matched",
            },
            {"scenario": "yoghurt_500g_decoy", "expected_match_status": "not_in_range"},
        ],
        "label_checks": [
            {
                "check_id": "lc-1",
                "store_id": "S012",
                "checked_at": _at(L0),
                "status": "findings",
                "product_id": "P31007",
                "lot": "B2026-118",
                "findings": [
                    {"rule": "allergen_missing_in_listing", "severity": "high"}
                ],
                "candidate_id": MUESLI_CANDIDATE,
            },
            {
                "check_id": "lc-2",
                "store_id": "S004",
                "checked_at": _at(L0, 5),
                "status": "checked",
                "product_id": "P48812",
                "lot": "B2026-104",
                "findings": [],
            },
        ],
        "truth_labels": [
            {
                "fixture": "muesli_almond",
                "product_id": "P31007",
                "lot": "B2026-118",
                "expected_rules": ["allergen_missing_in_listing"],
            },
            {
                "fixture": "yoghurt_clean",
                "product_id": "P48812",
                "lot": "B2026-104",
                "expected_rules": [],
            },
        ],
        "publish_log": [
            {
                "event_id": e,
                "published_at": _at(RECENT, i),
                "ok": True,
                "topic": "psd-events",
            }
            for i, e in enumerate(("e1", "e2", "e3"))
        ]
        # A label candidate goes to psd-agents, not to events, so the tile must not count it as missing.
        + [
            {
                "event_id": "lc-1",
                "published_at": _at(RECENT, 4),
                "ok": True,
                "topic": "psd-incident-candidates",
            }
        ],
        "events": [
            {"event_id": "e1", "publish_time": _at(RECENT, 1)},
            {"event_id": "e1", "publish_time": _at(RECENT, 2)},
            {"event_id": "e2", "publish_time": _at(RECENT, 2)},
        ],
        "desk_records": [
            # An earlier version of the yoghurt incident, which the views must pass over.
            _version(
                "incidents",
                "inc-1",
                T0 + timedelta(minutes=20),
                {**yoghurt, "status": "awaiting_approval"},
            ),
            _version(
                "incidents",
                "inc-1",
                APPROVED + timedelta(minutes=50),
                {
                    **yoghurt,
                    "status": "closed",
                    "approved_at": _at(APPROVED),
                    "closed_at": _at(APPROVED, 50),
                    "approved": {
                        "actions": {
                            "message_orders": ["O1", "O2"],
                            "targets": {"message_minutes": 30, "shelf_minutes": 60},
                        }
                    },
                },
            ),
            _version(
                "incidents",
                "inc-2",
                L0 + timedelta(minutes=20),
                {
                    **muesli,
                    "status": "verifying",
                    "approved_at": _at(L0, 20),
                    "approved": {"actions": {"message_orders": [], "targets": {}}},
                },
            ),
            *[
                _version(
                    "tasks",
                    task_id,
                    T0 + timedelta(hours=2),
                    {
                        "task_id": task_id,
                        "incident_id": incident_id,
                        "store_id": store_id,
                        "status": status,
                        "verified_at": _at(APPROVED, minutes) if minutes else None,
                        "reissue_of": reissue_of,
                    },
                )
                for task_id, incident_id, store_id, status, minutes, reissue_of in tasks
            ],
            *[
                _version(
                    "outbox",
                    f"msg-{order}",
                    T0 + timedelta(hours=1),
                    {
                        "message_id": f"msg-{order}",
                        "incident_id": "inc-1",
                        "audience": "customer",
                        "status": "sent",
                        "sent_at": _at(APPROVED, n + 1),
                    },
                )
                for n, order in enumerate(("O1", "O2"))
            ],
            _version(
                "listing_changes",
                "lst-1",
                L0 + timedelta(minutes=20),
                {
                    "change_id": "lst-1",
                    "incident_id": "inc-2",
                    "product_id": "P31007",
                    "change": {"field": "allergens"},
                    "applied_at": _at(L0, 20),
                },
            ),
        ],
    }


@pytest.fixture(scope="module")
def dataset():
    require_table("psd_test")
    client = bq.client()
    name = f"psd_test_metrics_{uuid.uuid4().hex[:8]}"
    made = bigquery.Dataset(f"{client.project}.{name}")
    made.location = bq.location()
    client.create_dataset(made)
    try:
        apply_ddl(client, name)
        for table, rows in _world().items():
            load_table(client, name, table, rows)
        yield name
    finally:
        client.delete_dataset(
            f"{client.project}.{name}", delete_contents=True, not_found_ok=True
        )


@pytest.fixture(autouse=True)
def _in_dataset(dataset, monkeypatch):
    monkeypatch.setenv("PSD_DATASET", dataset)


def _rows(metric: str) -> list[dict]:
    receipt = run_attested(f"/computations/{metric}.md", {}, used_by="test:metrics")
    assert receipt.attested
    return receipt.result


def test_minutes_to_candidate() -> None:
    (row,) = _rows("minutes-to-candidate")
    assert row["notices"] == 1
    assert (row["median_minutes"], row["max_minutes"]) == (6.0, 6.0)
    assert row["max_minutes_from_published"] == 16.0


def test_minutes_to_approve() -> None:
    (row,) = _rows("minutes-to-approve")
    assert row["incidents"] == 2 and row["max_minutes"] == 19.0


def test_customers_messaged() -> None:
    (row,) = _rows("customers-messaged")
    assert (row["incidents"], row["messages_sent"], row["orders_to_message"]) == (
        1,
        2,
        2,
    )
    assert row["sent_ratio"] == 1.0 and row["max_minutes"] == 2.0
    assert row["within_target"] == 1


def test_minutes_to_shelf_clear() -> None:
    (row,) = _rows("minutes-to-shelf-clear")
    assert (row["incidents_clear"], row["incidents_verifying"]) == (1, 1)
    assert (row["median_minutes"], row["max_minutes"], row["within_target"]) == (
        50.0,
        50.0,
        1,
    )


def test_stores_verified_counts_a_store_once_and_a_reissue_as_a_task() -> None:
    total, yoghurt, muesli = _rows("stores-verified")
    assert total["incident_id"] is None
    assert (
        total["stores_tasked"],
        total["stores_verified"],
        total["tasks_issued"],
    ) == (
        3,
        2,
        4,
    )
    assert (
        yoghurt["incident_id"],
        yoghurt["stores_verified"],
        yoghurt["tasks_open"],
    ) == (
        "inc-1",
        2,
        0,
    )
    assert (muesli["incident_id"], muesli["tasks_open"]) == ("inc-2", 1)


def test_listing_fix_minutes() -> None:
    (row,) = _rows("listing-fix-minutes")
    assert (row["fixes"], row["median_minutes"], row["max_minutes"]) == (1, 20.0, 20.0)


def test_notice_outcomes_lead_with_the_total() -> None:
    rows = _rows("notice-outcomes")
    assert (rows[0]["feed"], rows[0]["notices"]) == (None, 3)
    assert {(r["feed"], r["match_status"], r["notices"]) for r in rows[1:]} == {
        ("fsanz", "not_in_range", 1),
        ("test", "matched", 1),
        ("test", "not_in_range", 1),
    }


def test_label_findings() -> None:
    rows = _rows("label-findings")
    assert [(r["measure"], r["n"]) for r in rows] == [
        ("checks", 2),
        ("candidates_raised", 1),
        ("findings", 1),
    ]
    assert (rows[2]["rule"], rows[2]["severity"]) == (
        "allergen_missing_in_listing",
        "high",
    )


def test_published_vs_landed_finds_the_gap_and_the_duplicate() -> None:
    total = _rows("published-vs-landed")[0]
    assert total["hour"] is None
    assert (
        total["published"],
        total["landed"],
        total["missing"],
        total["duplicates"],
    ) == (3, 2, 1, 1)


def test_match_eval_against_the_truth_tables() -> None:
    recall, label = _rows("match-eval")
    assert recall["detection"] == "recall_match"
    assert (
        recall["judged"],
        recall["predicted"],
        recall["expected"],
        recall["correct"],
    ) == (
        2,
        1,
        1,
        1,
    )
    assert (recall["precision"], recall["recall"], recall["status_agrees"]) == (
        1.0,
        1.0,
        2,
    )
    assert label["detection"] == "label_findings"
    assert (label["judged"], label["precision"], label["recall"]) == (2, 1.0, 1.0)
