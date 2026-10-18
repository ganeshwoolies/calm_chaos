from types import SimpleNamespace

import pytest

from app import evidence


def _stand(candidate_id):
    return evidence.stand_in(candidate_id)


def test_a_recall_traces_the_codes_its_notice_names(pol) -> None:
    params = evidence.lineage_params(_stand("recall:yoghurt_listeria"), pol)
    assert params == {
        "product_id": "P48812",
        "codes": ["B2026-091"],
        "best_before_from": None,
        "best_before_to": None,
    }


def test_a_notice_without_codes_traces_its_best_before_range(pol) -> None:
    stand = _stand("recall:yoghurt_listeria")
    stand["notice"]["extract"]["batch_codes"] = []
    params = evidence.lineage_params(stand, pol)
    assert (params["codes"], params["best_before_from"], params["best_before_to"]) == (
        [],
        "2026-10-30",
        "2026-10-30",
    )


def test_several_best_before_dates_trace_from_the_earliest_to_the_latest(pol) -> None:
    stand = _stand("recall:yoghurt_listeria")
    stand["notice"]["extract"]["batch_codes"] = []
    stand["notice"]["extract"]["date_codes"] = [
        {"kind": "best_before", "from": "2026-11-19", "to": None},
        {"kind": "use_by", "from": "2026-10-01", "to": None},
        {"kind": "best_before", "from": "2026-11-05", "to": "2026-11-07"},
    ]
    params = evidence.lineage_params(stand, pol)
    assert (params["best_before_from"], params["best_before_to"]) == (
        "2026-11-05",
        "2026-11-19",
    )


def test_a_best_before_with_no_start_traces_every_batch(pol) -> None:
    stand = _stand("recall:yoghurt_listeria")
    stand["notice"]["extract"]["batch_codes"] = []
    stand["notice"]["extract"]["date_codes"] = [
        {"kind": "best_before", "from": "2026-11-05"},
        {"kind": "best_before", "from": None, "to": "2026-11-19"},
    ]
    params = evidence.lineage_params(stand, pol)
    assert (params["best_before_from"], params["best_before_to"]) == (None, None)


def test_a_label_traces_lots_only_when_a_rule_proposes_a_hold(pol) -> None:
    assert evidence.lineage_params(_stand("label:P50211:7a0d3f"), pol)["codes"] == [
        "L2026-0311"
    ]
    assert evidence.lineage_params(_stand("label:P31007:4c19e2"), pol) is None


def test_bigquery_evidence_carries_the_attested_receipt(monkeypatch) -> None:
    monkeypatch.setenv("PSD_EVIDENCE_SOURCE", "bigquery")
    product = {
        "product_id": "P48812",
        "name": "Vanilla Yoghurt",
        "brand": "Morrowdale",
        "size": "1kg",
        "category": "food",
        "supplier_id": "SUP-004",
        "supplier_name": "Morrowdale Dairy Co",
    }
    rows = [
        {
            "row_kind": "store",
            "batch_id": "BAT-P48812-091",
            "code": "B2026-091",
            "store_id": "S004",
            "delivered": 24,
            "last_delivered": "2026-10-12T00:00:00+00:00",
            "on_hand": 18,
            "aisle": "7",
            "order_id": None,
        }
    ]
    calls = {}

    def run_attested(concept, params, used_by):
        calls.update(concept=concept, params=params, used_by=used_by)
        return SimpleNamespace(receipt_id="rcpt-abc123", result=rows)

    monkeypatch.setattr(evidence.bq, "rows", lambda sql, parameters=(): [product])
    monkeypatch.setattr(evidence.attest, "run_attested", run_attested)
    pack = evidence.load("recall:yoghurt_listeria", used_by="incident:inc-1")
    assert pack.lineage.receipt_id == "rcpt-abc123" and pack.receipts == ["rcpt-abc123"]
    assert (
        pack.product.name == "Vanilla Yoghurt"
        and pack.lineage.store_rows[0].on_hand == 18
    )
    assert (
        calls["concept"] == evidence.LINEAGE
        and calls["params"]["order_lookback_days"] == 30
    )


def test_a_product_missing_from_bigquery_names_the_fix(monkeypatch) -> None:
    monkeypatch.setenv("PSD_EVIDENCE_SOURCE", "bigquery")
    monkeypatch.setattr(evidence.bq, "rows", lambda sql, parameters=(): [])
    with pytest.raises(LookupError, match=r"load_truth.py"):
        evidence.load("recall:yoghurt_listeria", used_by="t")


SCOPED = "recall:1a2b3c4d:P48812"
NOTICE_ROW = {
    "guid": "test:fsanz:yoghurt_listeria:20261017T000000Z",
    "feed": "test",
    "title": "Morrowdale Vanilla Yoghurt 1kg",
    "url": "https://storage.cloud.google.com/b/test/notices/n.html",
    "attribution": "Fictional test notice: not issued by FSANZ or the ACCC",
    "published_at": "2026-10-17T00:00:00+00:00",
    "first_seen": "2026-10-17T00:01:00+00:00",
    "recall_extract": {
        "brand": "Morrowdale",
        "product_name": "Vanilla Yoghurt",
        "sizes": ["1kg"],
        "batch_codes": ["B2026-091"],
        "date_codes": None,
        "hazard_type": "microbial",
        "hazard_detail": "Listeria monocytogenes",
    },
    "matched_product_id": "P48812",
    "match_method": "embedding",
    "match_distance": 0.03,
    "receipt_id": "rcpt-scope00001",
    "hazard_type": "microbial",
}
PRODUCT_ROW = {
    "product_id": "P48812",
    "name": "Vanilla Yoghurt",
    "brand": "Morrowdale",
    "size": "1kg",
    "category": "food",
    "supplier_id": "SUP-004",
    "supplier_name": "Morrowdale Dairy Co",
}


def _scoped(monkeypatch, receipt) -> None:
    monkeypatch.setenv("PSD_EVIDENCE_SOURCE", "bigquery")
    monkeypatch.setattr(
        evidence.bq,
        "rows",
        lambda sql, parameters=(): (
            [NOTICE_ROW] if "recall_notices" in sql else [PRODUCT_ROW]
        ),
    )
    monkeypatch.setattr(evidence.attest, "load_receipt", lambda receipt_id: receipt)

    def run_attested(*args, **kwargs):
        raise AssertionError("a scoped candidate reuses the scope job's lineage")

    monkeypatch.setattr(evidence.attest, "run_attested", run_attested)


def test_a_scoped_recall_reads_its_notice_and_the_scope_jobs_receipt(
    monkeypatch,
) -> None:
    receipt = SimpleNamespace(
        receipt_id="rcpt-scope00001",
        concept=evidence.LINEAGE,
        params={"as_of": "2026-10-17T00:02:00+00:00"},
        result=[
            {
                "row_kind": "store",
                "batch_id": "BAT-P48812-091",
                "code": "B2026-091",
                "store_id": "S004",
                "delivered": 24,
                "last_delivered": "2026-10-15T00:00:00+00:00",
                "on_hand": 18,
                "aisle": "7",
                "order_id": None,
            }
        ],
    )
    _scoped(monkeypatch, receipt)
    pack = evidence.load(SCOPED, used_by="incident:inc-1")
    assert pack.candidate_id == SCOPED and pack.receipts == ["rcpt-scope00001"]
    assert pack.lineage.as_of == "2026-10-17T00:02:00+00:00"
    assert (
        pack.notice.guid == NOTICE_ROW["guid"] and pack.notice.extract.date_codes == []
    )
    assert pack.match.method == "embedding" and pack.match.confirmed
    assert pack.notice.attribution == NOTICE_ROW["attribution"]
    assert pack.hazard_type == "microbial"
    assert pack.title_hint == (
        "Morrowdale Vanilla Yoghurt 1kg batch B2026-091 Listeria monocytogenes recall"
    )


def test_a_scoped_recall_without_a_passing_receipt_shows_no_figures(
    monkeypatch,
) -> None:
    _scoped(monkeypatch, None)
    with pytest.raises(evidence.attest.AttestationFailed, match="rcpt-scope00001"):
        evidence.load(SCOPED, used_by="t")


def test_a_receipt_that_did_not_attest_is_never_loaded(monkeypatch) -> None:
    row = {"receipt_id": "rcpt-x", "attested": False}
    job = SimpleNamespace(result=lambda: [row])
    client = SimpleNamespace(project="p", query=lambda sql, job_config, location: job)
    assert evidence.attest.load_receipt("rcpt-x", client=client) is None
