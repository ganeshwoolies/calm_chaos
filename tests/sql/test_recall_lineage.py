"""recall_lineage.sql through run_attested, on small tables in psd_test whose answers are known."""

from datetime import UTC, datetime

import pytest
from google.cloud import bigquery

from app import bq
from app.attest import run_attested
from data.load_truth import apply_ddl, load_table
from tests.sql.conftest import require_table

LINEAGE = "/computations/recall-lineage.md"
AS_OF = datetime(2026, 10, 17, tzinfo=UTC)

TABLES = {
    "batches": [
        {
            "batch_id": "BA1",
            "product_id": "PA",
            "kind": "batch",
            "code": "B2026-001",
            "produced_on": "2026-10-01",
            "best_before": "2026-11-01",
            "supplier_id": "SUP-T",
        },
        {
            "batch_id": "BA2",
            "product_id": "PA",
            "kind": "batch",
            "code": "B2026-002",
            "produced_on": "2026-09-01",
            "best_before": "2026-12-01",
            "supplier_id": "SUP-T",
        },
        {
            "batch_id": "BB1",
            "product_id": "PB",
            "kind": "lot",
            "code": "L2026-0001",
            "produced_on": "2026-09-20",
            "best_before": None,
            "supplier_id": "SUP-T",
        },
    ],
    "deliveries": [
        {
            "delivery_id": "D1",
            "batch_id": "BA1",
            "dc_id": "DC-T",
            "store_id": "S001",
            "delivered_at": "2026-10-10T00:00:00Z",
            "qty": 10,
        },
        {
            "delivery_id": "D2",
            "batch_id": "BA1",
            "dc_id": "DC-T",
            "store_id": "S001",
            "delivered_at": "2026-10-12T00:00:00Z",
            "qty": 5,
        },
        {
            "delivery_id": "D3",
            "batch_id": "BA1",
            "dc_id": "DC-T",
            "store_id": "S002",
            "delivered_at": "2026-10-18T00:00:00Z",
            "qty": 8,
        },
        {
            "delivery_id": "D4",
            "batch_id": "BA2",
            "dc_id": "DC-T",
            "store_id": "S003",
            "delivered_at": "2026-10-05T00:00:00Z",
            "qty": 6,
        },
        {
            "delivery_id": "D5",
            "batch_id": "BB1",
            "dc_id": "DC-T",
            "store_id": "S004",
            "delivered_at": "2026-10-01T00:00:00Z",
            "qty": 3,
        },
    ],
    "store_stock": [
        {
            "store_id": "S001",
            "product_id": "PA",
            "batch_id": "BA1",
            "on_hand": 7,
            "aisle": "3",
            "as_of": "2026-10-17T00:00:00Z",
        },
        {
            "store_id": "S003",
            "product_id": "PA",
            "batch_id": "BA2",
            "on_hand": 2,
            "aisle": "4",
            "as_of": "2026-10-17T00:00:00Z",
        },
    ],
    "online_orders": [
        {
            "order_id": "O1",
            "customer_ref": "c1",
            "store_id": "S001",
            "ordered_at": "2026-10-15T00:00:00Z",
            "status": "collected",
            "channel_pref": "email",
        },
        {
            "order_id": "O2",
            "customer_ref": "c2",
            "store_id": "S002",
            "ordered_at": "2026-08-01T00:00:00Z",
            "status": "collected",
            "channel_pref": "sms",
        },
        {
            "order_id": "O3",
            "customer_ref": "c3",
            "store_id": "S003",
            "ordered_at": "2026-10-16T00:00:00Z",
            "status": "delivered",
            "channel_pref": "app",
        },
    ],
    "order_lines": [
        {"order_id": "O1", "product_id": "PA", "batch_id": "BA1", "qty": 1},
        {"order_id": "O2", "product_id": "PA", "batch_id": "BA1", "qty": 1},
        {"order_id": "O3", "product_id": "PA", "batch_id": "BA2", "qty": 2},
    ],
}


@pytest.fixture(scope="module", autouse=True)
def lineage_tables():
    require_table("psd_test")
    client = bq.client()
    apply_ddl(client, "psd_test")
    for name, rows in TABLES.items():
        load_table(client, "psd_test", name, rows)


@pytest.fixture(autouse=True)
def _test_dataset(monkeypatch):
    monkeypatch.setenv("PSD_DATASET", "psd_test")


def _run(product_id, codes, start=None, end=None):
    receipt = run_attested(
        LINEAGE,
        {
            "product_id": product_id,
            "codes": codes,
            "best_before_from": start,
            "best_before_to": end,
            "as_of": AS_OF,
            "order_lookback_days": 30,
        },
        used_by="test:recall_lineage",
    )
    stores = [
        (r["store_id"], r["delivered"], r["on_hand"])
        for r in receipt.result
        if r["row_kind"] == "store"
    ]
    orders = sorted(r["order_id"] for r in receipt.result if r["row_kind"] == "order")
    return receipt, stores, orders


def test_named_codes_exclude_later_deliveries_and_old_orders() -> None:
    receipt, stores, orders = _run("PA", ["B2026-001"])
    assert stores == [("S001", 15, 7)]
    assert orders == ["O1"]
    assert next(r for r in receipt.result if r["row_kind"] == "store")[
        "last_delivered"
    ].startswith("2026-10-12")


def test_no_codes_traces_the_best_before_range() -> None:
    _, stores, orders = _run("PA", [], "2026-11-15", "2026-12-15")
    assert stores == [("S003", 6, 2)] and orders == ["O3"]


def test_no_codes_and_no_dates_traces_every_batch() -> None:
    _, stores, orders = _run("PA", [])
    assert sorted(s for s, _, _ in stores) == ["S001", "S003"] and orders == [
        "O1",
        "O3",
    ]
    _, stores, _ = _run("PB", [])
    assert stores == [("S004", 3, 0)]


def test_the_receipt_is_recorded_as_passing() -> None:
    receipt, _, _ = _run("PA", ["B2026-001"])
    recorded = bq.rows(
        "SELECT attested, job_id FROM attestations WHERE receipt_id = @r",
        [bigquery.ScalarQueryParameter("r", "STRING", receipt.receipt_id)],
    )
    assert recorded == [{"attested": True, "job_id": receipt.job_id}]
