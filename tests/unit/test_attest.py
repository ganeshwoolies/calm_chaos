import json
from datetime import UTC, datetime

import pytest
from google.cloud import bigquery

from app import bq
from app.attest import AttestationFailed, run_attested
from app.knowledge import PolicyUnavailable
from tests.knowledge_copy import edit_concept

LINEAGE = "/computations/recall-lineage.md"
PARAMS = {
    "product_id": "P48812",
    "codes": ["B2026-091"],
    "as_of": datetime(2026, 10, 17, tzinfo=UTC),
    "order_lookback_days": 30,
}


class _Job:
    def __init__(self, executed: str, rows: list[dict]) -> None:
        self.query = executed
        self.job_id = "job-test-1"
        self._rows = rows

    def result(self) -> list[dict]:
        return self._rows


class _Client:
    project = "test-project"

    def __init__(self, rows=(), tamper: str = "", insert_errors=()) -> None:
        self.rows, self.tamper, self.insert_errors = (
            list(rows),
            tamper,
            list(insert_errors),
        )
        self.config: bigquery.QueryJobConfig | None = None
        self.inserted: list[tuple[str, list[dict]]] = []

    def query(self, sql, job_config, location):
        self.config = job_config
        return _Job(sql + self.tamper, self.rows)

    def insert_rows_json(self, table, rows):
        self.inserted.append((table, rows))
        return self.insert_errors


def test_a_passing_receipt_is_recorded_and_returned() -> None:
    row = {
        "row_kind": "store",
        "store_id": "S004",
        "on_hand": 18,
        "last_delivered": datetime(2026, 10, 12, tzinfo=UTC),
    }
    client = _Client(rows=[row])
    receipt = run_attested(LINEAGE, PARAMS, used_by="incident:inc-1", client=client)
    assert receipt.attested and receipt.reason is None
    assert receipt.result == [{**row, "last_delivered": "2026-10-12T00:00:00+00:00"}]
    table, [recorded] = client.inserted[0]
    assert table == "test-project.psd.attestations"
    assert recorded["receipt_id"] == receipt.receipt_id and recorded["attested"] is True
    assert json.loads(recorded["params"])["codes"] == ["B2026-091"]


def test_parameters_are_bound_by_name_and_type() -> None:
    client = _Client()
    run_attested(LINEAGE, {**PARAMS, "codes": []}, used_by="t", client=client)
    config = client.config
    assert config.default_dataset.dataset_id == "psd"
    assert config.maximum_bytes_billed == bq.MAX_BYTES_BILLED
    bound = {p.name: p for p in config.query_parameters}
    assert (
        isinstance(bound["codes"], bigquery.ArrayQueryParameter)
        and bound["codes"].values == []
    )
    assert (bound["best_before_from"].type_, bound["best_before_from"].value) == (
        "DATE",
        None,
    )
    assert (
        bound["as_of"].type_ == "TIMESTAMP"
        and bound["order_lookback_days"].type_ == "INT64"
    )


def test_executed_sql_that_differs_fails_but_is_recorded() -> None:
    client = _Client(tamper=" LIMIT 1")
    with pytest.raises(AttestationFailed, match="failed attestation"):
        run_attested(LINEAGE, PARAMS, used_by="t", client=client)
    assert client.inserted[0][1][0]["attested"] is False


def test_an_unrecorded_receipt_is_not_an_attestation() -> None:
    with pytest.raises(AttestationFailed, match="could not be recorded"):
        run_attested(
            LINEAGE, PARAMS, used_by="t", client=_Client(insert_errors=[{"index": 0}])
        )


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({**PARAMS, "sql": "DROP TABLE batches"}, "not declared"),
        (
            {k: v for k, v in PARAMS.items() if k != "product_id"},
            "product_id is required",
        ),
    ],
)
def test_only_declared_parameters_are_accepted(params, message) -> None:
    with pytest.raises(ValueError, match=message):
        run_attested(LINEAGE, params, used_by="t", client=_Client())


def test_an_unverified_computation_is_refused(verified_bundle) -> None:
    edit_concept(verified_bundle, LINEAGE, status="draft")
    try:
        with pytest.raises(PolicyUnavailable, match="status is draft"):
            run_attested(LINEAGE, PARAMS, used_by="t", client=_Client())
    finally:
        edit_concept(verified_bundle, LINEAGE, status="stable")
