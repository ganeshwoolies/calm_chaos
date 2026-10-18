"""The recall trigger's SQL on live BigQuery, in psd_test: the poller's insert, the scope job's transaction and outbox,
the evidence query, and catalogue embedding and matching over two products (AI.EMBED and AI.IF are called)."""

import json
import uuid
from typing import Any

import pytest
from google.cloud import bigquery

from api import recalls, scope
from app import bq, evidence
from app.knowledge import MatchRule
from data.load_truth import apply_ddl, load_table
from tests.sql.conftest import require_table

RULE = MatchRule(
    barcode_first=True,
    top_k=5,
    max_distance=0.25,
    ambiguity_gap=0.05,
    require_model_confirmation=True,
)


def _product(product_id: str, name: str, barcode: str) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "name": name,
        "brand": "Morrowdale",
        "size": "1kg",
        "category": "food",
        "subcategory": "dairy",
        "barcode": barcode,
        "supplier_id": "SUP-T",
        "unit_price": "5.50",
        "listing_text": f"Morrowdale {name} 1kg",
        "listing_allergens": ["milk"],
        "listing_warnings": [],
        "listing_marks": [],
        "listing_origin": "Australia",
    }


PRODUCTS = [
    _product("PT1", "Vanilla Yoghurt", "2000000000017"),
    _product("PT2", "Natural Yoghurt", "2000000000024"),
]


@pytest.fixture(scope="module", autouse=True)
def trigger_tables():
    require_table("psd_test")
    client = bq.client()
    apply_ddl(client, "psd_test")
    load_table(client, "psd_test", "products", PRODUCTS)


@pytest.fixture(autouse=True)
def _test_dataset(monkeypatch):
    monkeypatch.setenv("PSD_DATASET", "psd_test")


def _notice(guid: str) -> dict[str, Any]:
    """A notice as the poller builds it."""
    return {
        "event_id": f"evt_test_{uuid.uuid4().hex[:12]}",
        "source": "recall",
        "feed": "test",
        "guid": guid,
        "title": "FICTIONAL TEST: Morrowdale Vanilla Yoghurt 1kg",
        "url": "https://storage.cloud.google.com/bucket/test/notices/n.html",
        "attribution": "Fictional test notice: not issued by FSANZ or the ACCC",
        "published_at": "2026-10-17T00:00:00+00:00",
        "text": "FICTIONAL TEST: Morrowdale Vanilla Yoghurt 1kg\n\nBatch B1.",
        "screen": {"flagged": False, "filters": [], "reason": None},
        "screen_reason": None,
    }


def _guid() -> str:
    return f"FICTIONAL-TEST:fsanz:sql_test:{uuid.uuid4().hex[:12]}"


def _row(guid: str) -> dict[str, Any]:
    (row,) = bq.rows(
        "SELECT * FROM recall_notices WHERE guid = @guid",
        [bigquery.ScalarQueryParameter("guid", "STRING", guid)],
    )
    return row


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def test_a_polled_notice_is_recorded_pending_with_its_credit() -> None:
    guid = _guid()
    recalls._insert([_notice(guid)])
    row = _row(guid)
    assert row["match_status"] == "pending" and row["first_seen"]
    assert row["attribution"].startswith("Fictional test notice")
    assert row["published_at"].startswith("2026-10-17T00:00:00")


def test_outcome_matches_and_candidate_land_together_and_leave_by_the_outbox() -> None:
    guid = _guid()
    notice = _notice(guid)
    recalls._insert([notice])
    cid = scope.candidate_id(guid, "PT1")
    extract = {
        "brand": "Morrowdale",
        "product_name": "Vanilla Yoghurt",
        "batch_codes": ["B1"],
    }
    scope._write(
        [
            scope._outcome(
                guid,
                json.dumps(extract),
                "matched",
                product_id="PT1",
                method="embedding",
                distance=0.03,
                receipt_id="rcpt-sqltest",
                candidate_id=cid,
            )
        ],
        [
            {
                "event_id": notice["event_id"],
                "product_id": "PT1",
                "rank": 1,
                "method": "embedding",
                "distance": 0.03,
                "same_product": True,
            }
        ],
        [
            {
                "candidate_id": cid,
                "kind": "recall",
                "product_id": "PT1",
                "guid": guid,
                "batch_ids": ["BAT-1"],
                "event_ids": [notice["event_id"]],
                "stores": ["S001"],
                "online_orders": 2,
                "receipt_ids": ["rcpt-sqltest"],
            }
        ],
    )
    row = _row(guid)
    assert (row["match_status"], row["candidate_id"], row["matched_by"]) == (
        "matched",
        cid,
        "scope",
    )
    assert _json(row["recall_extract"])["batch_codes"] == ["B1"]
    matched = bq.rows(
        "SELECT product_id FROM recall_matches WHERE event_id = @e",
        [bigquery.ScalarQueryParameter("e", "STRING", notice["event_id"])],
    )
    assert [m["product_id"] for m in matched] == ["PT1"]

    assert cid in {c["candidate_id"] for c in bq.rows(scope._UNPUBLISHED_SQL)}
    bq.rows(
        scope._MARK_PUBLISHED_SQL,
        [bigquery.ArrayQueryParameter("ids", "STRING", [cid])],
    )
    assert cid not in {c["candidate_id"] for c in bq.rows(scope._UNPUBLISHED_SQL)}

    # The notice is no longer pending, so a repeated outcome changes nothing.
    scope._write([scope._outcome(guid, "{}", "not_in_range")], [], [])
    assert _row(guid)["match_status"] == "matched"

    (found,) = bq.rows(
        evidence._NOTICE_SQL,
        [bigquery.ScalarQueryParameter("candidate_id", "STRING", cid)],
    )
    assert (
        found["receipt_id"] == "rcpt-sqltest" and found["matched_product_id"] == "PT1"
    )
    assert (
        found["attribution"] and _json(found["recall_extract"])["brand"] == "Morrowdale"
    )


def test_catalogue_embedding_and_matching_run_on_bigquery() -> None:
    found = scope.match_notices(
        {
            "evt_barcode": {
                "brand": "Morrowdale",
                "product_name": "Vanilla Yoghurt",
                "sizes": ["1kg"],
                "barcodes": ["2000000000017"],
            },
            "evt_text": {
                "brand": "Morrowdale",
                "product_name": "Vanilla Yoghurt",
                "sizes": ["1kg"],
            },
        },
        RULE,
    )
    assert [(m.method, m.product_id) for m in found["evt_barcode"]] == [
        ("barcode", "PT1")
    ]
    considered = found["evt_text"]
    assert {m.product_id for m in considered} == {"PT1", "PT2"}
    assert scope.decide(considered, RULE) == scope.Decision(
        "matched",
        "PT1",
        "embedding",
        next(m.distance for m in considered if m.product_id == "PT1"),
    )
