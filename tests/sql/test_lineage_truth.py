"""The lineage and attestation layer of the evaluation: attested lineage on the loaded world equals the truth tables."""

from datetime import UTC, datetime

import pytest

from app import bq
from app.attest import run_attested
from tests.sql.conftest import require_table

LINEAGE = "/computations/recall-lineage.md"


@pytest.fixture(autouse=True)
def _loaded(monkeypatch):
    monkeypatch.setenv("PSD_DATASET", "psd")
    require_table("psd", "truth_recalls")


def _lineage(
    product_id: str, codes: list[str]
) -> tuple[dict[str, int], set[str], bool]:
    receipt = run_attested(
        LINEAGE,
        {
            "product_id": product_id,
            "codes": codes,
            "as_of": datetime.now(UTC),
            "order_lookback_days": 30,
        },
        used_by="test:lineage_truth",
    )
    on_hand = {
        r["store_id"]: r["on_hand"]
        for r in receipt.result
        if r["row_kind"] == "store" and r["on_hand"]
    }
    orders = {r["order_id"] for r in receipt.result if r["row_kind"] == "order"}
    return on_hand, orders, receipt.attested


def test_recall_scenarios_equal_the_truth() -> None:
    scenarios = bq.rows(
        "SELECT * FROM truth_recalls WHERE product_id IS NOT NULL ORDER BY scenario"
    )
    assert scenarios
    for s in scenarios:
        on_hand, orders, attested = _lineage(s["product_id"], s["codes"])
        assert attested, s["scenario"]
        assert sorted(on_hand) == s["stores_on_hand"], s["scenario"]
        assert sum(on_hand.values()) == s["units_on_hand"], s["scenario"]
        assert sorted(orders) == s["online_orders"], s["scenario"]


def test_label_holds_equal_the_truth() -> None:
    fixtures = bq.rows(
        "SELECT * FROM truth_labels WHERE ARRAY_LENGTH(hold_stores) > 0 ORDER BY fixture"
    )
    assert fixtures
    for f in fixtures:
        on_hand, _, attested = _lineage(f["product_id"], [f["lot"]])
        assert attested and sorted(on_hand) == f["hold_stores"], f["fixture"]
        assert sum(on_hand.values()) == f["units_on_hand"], f["fixture"]
