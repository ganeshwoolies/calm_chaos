"""Evidence for one candidate, as an EvidencePack.

From BigQuery by default: the product and its supplier, and lineage through the attested recall-lineage computation.
A recall candidate raised by the scope job reads its notice, extract and match from recall_notices, and its lineage from
the receipt the scope job recorded, which is used only if it attested; lineage does not run again. A label candidate
raised by the label check reads its checks from label_checks, and runs lineage on their lots when a rule proposes a
hold. The stand-ins tests use are fixtures in data/fixtures, read before either table. PSD_EVIDENCE_SOURCE=
fixtures reads whole packs from data/fixtures/evidence instead, for tests that run offline; data/write_fixtures.py
writes those packs from the same generated world BigQuery holds.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.cloud import bigquery

from app import attest, bq, policy
from app.schemas import EvidencePack, LabelFinding, Lineage, LineageRow, Product

LINEAGE = "/computations/recall-lineage.md"
STAND_IN_FOLDERS = ("notices", "label_checks")

_PRODUCT_SQL = """SELECT p.product_id, p.name, p.brand, p.size, p.category, p.supplier_id, s.name AS supplier_name
FROM products AS p
JOIN suppliers AS s USING (supplier_id)
WHERE p.product_id = @product_id"""

_NOTICE_SQL = """SELECT n.guid, n.feed, n.title, n.url, n.attribution, n.published_at, n.first_seen, n.recall_extract,
  n.matched_product_id, n.match_method, n.match_distance, n.receipt_id, e.hazard_type
FROM recall_notices AS n
LEFT JOIN v_events_dedup AS e USING (event_id)
WHERE n.candidate_id = @candidate_id"""

_LABEL_CHECKS_SQL = """SELECT l.check_id, l.store_id, l.checked_at, l.photo_uri, l.product_id, l.lot, l.findings,
  CONCAT(p.brand, ' ', p.name, ' ', p.size) AS product_label
FROM label_checks AS l
JOIN products AS p USING (product_id)
WHERE l.candidate_id = @candidate_id
ORDER BY l.checked_at"""


def fixtures_dir() -> Path:
    return Path(
        os.environ.get("PSD_FIXTURES_DIR")
        or Path(__file__).resolve().parent.parent / "data" / "fixtures"
    )


def source() -> str:
    return os.environ.get("PSD_EVIDENCE_SOURCE", "bigquery")


def _find(folder: str, candidate_id: str) -> dict[str, Any] | None:
    for path in sorted((fixtures_dir() / folder).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("candidate_id") == candidate_id:
            return data
    return None


def from_fixture(candidate_id: str) -> EvidencePack | None:
    data = _find("evidence", candidate_id)
    return EvidencePack.model_validate(data) if data else None


def stand_in(candidate_id: str) -> dict[str, Any] | None:
    """The notice or label checks for a candidate: stand-ins until the recall trigger and the label check write them."""
    for folder in STAND_IN_FOLDERS:
        if data := _find(folder, candidate_id):
            return data
    return None


def lineage_params(stand: dict[str, Any], pol: policy.Policy) -> dict[str, Any] | None:
    """The recall-lineage parameters a candidate needs, or None when no figure depends on lineage.

    A recall traces the codes its notice names, or when it names none, one range from the earliest to the latest
    best-before date it names. A label check traces the lots read from the packs, and only when one of its findings'
    rules proposes a hold.
    """
    if stand["kind"] == "recall":
        extract = stand["notice"]["extract"]
        codes = list(extract.get("batch_codes") or [])
        dates = [
            d for d in extract.get("date_codes") or [] if d.get("kind") == "best_before"
        ]
        # A date with no "to" is a range of one day. A date with no "from" leaves the range open, and an open range is
        # traced as every batch (best_before_from NULL), never narrowed to its end.
        bounds = [(d.get("from"), d.get("to") or d.get("from")) for d in dates]
        start, end = (
            (min(s for s, _ in bounds), max(e for _, e in bounds))
            if bounds and not codes and all(s for s, _ in bounds)
            else (None, None)
        )
        return {
            "product_id": stand["product_id"],
            "codes": codes,
            "best_before_from": start,
            "best_before_to": end,
        }
    lots = sorted({c["lot"] for c in stand["checks"] if c.get("lot")})
    holds = any(
        "hold" in pol.label_rule(f["rule"]).actions
        for c in stand["checks"]
        for f in c["findings"]
    )
    if not (holds and lots):
        return None
    return {
        "product_id": stand["product_id"],
        "codes": lots,
        "best_before_from": None,
        "best_before_to": None,
    }


def pack(
    stand: dict[str, Any], product: Product, lineage: Lineage | None
) -> EvidencePack:
    return EvidencePack(
        candidate_id=stand["candidate_id"],
        kind=stand["kind"],
        product=product,
        hazard_type=stand["hazard_type"],
        title_hint=stand["title_hint"],
        notice=stand.get("notice"),
        match=stand.get("match"),
        checks=stand.get("checks") or [],
        lineage=lineage,
        prior_incidents=stand.get("prior_incidents") or [],
    )


def _product(product_id: str) -> Product:
    rows = bq.rows(
        _PRODUCT_SQL,
        [bigquery.ScalarQueryParameter("product_id", "STRING", product_id)],
    )
    if not rows:
        raise LookupError(
            f"product {product_id} is not in {bq.dataset()}.products; load the synthetic data with data/load_truth.py"
        )
    return Product.model_validate(rows[0])


def _title_hint(product: Product, extract: dict[str, Any], hazard_type: str) -> str:
    codes = extract.get("batch_codes") or []
    batch = f" batch {', '.join(codes)}" if codes else ""
    return f"{product.brand} {product.name} {product.size}{batch} {extract.get('hazard_detail') or hazard_type} recall"


def _recall(candidate_id: str) -> EvidencePack | None:
    rows = bq.rows(
        _NOTICE_SQL,
        [bigquery.ScalarQueryParameter("candidate_id", "STRING", candidate_id)],
    )
    if not rows:
        return None
    n = rows[0]
    receipt = attest.load_receipt(n["receipt_id"]) if n["receipt_id"] else None
    if receipt is None or receipt.concept != LINEAGE:
        raise attest.AttestationFailed(
            f"candidate {candidate_id} has no passing {LINEAGE} receipt (receipt {n['receipt_id']})"
        )
    raw = n["recall_extract"]
    extract = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    product = _product(n["matched_product_id"])
    hazard_type = n["hazard_type"] or "quality_only"
    stand = {
        "candidate_id": candidate_id,
        "kind": "recall",
        "hazard_type": hazard_type,
        "title_hint": _title_hint(product, extract, hazard_type),
        "notice": {
            "guid": n["guid"],
            "feed": n["feed"],
            "title": n["title"],
            "url": n["url"],
            "attribution": n["attribution"],
            "published_at": n["published_at"] or n["first_seen"],
            "extract": {k: v for k, v in extract.items() if v is not None},
        },
        "match": {
            "method": n["match_method"],
            "distance": n["match_distance"],
            "confirmed": True,
        },
    }
    lineage = Lineage(
        receipt_id=receipt.receipt_id,
        as_of=str(receipt.params["as_of"]),
        rows=[LineageRow.model_validate(r) for r in receipt.result],
    )
    return pack(stand, product, lineage)


def _label_stand(candidate_id: str, pol: policy.Policy) -> dict[str, Any] | None:
    """A label candidate's checks from label_checks, in the stand-in's shape."""
    rows = bq.rows(
        _LABEL_CHECKS_SQL,
        [bigquery.ScalarQueryParameter("candidate_id", "STRING", candidate_id)],
    )
    if not rows:
        return None
    checks = [
        {
            "check_id": r["check_id"],
            "store_id": r["store_id"],
            "checked_at": r["checked_at"],
            "photo_uri": r["photo_uri"],
            "lot": r["lot"],
            "findings": json.loads(r["findings"])
            if isinstance(r["findings"], str)
            else list(r["findings"] or []),
        }
        for r in rows
    ]
    findings = [LabelFinding.model_validate(f) for c in checks for f in c["findings"]]
    worst = max(findings, key=lambda f: pol.severity_order.index(f.severity))
    lot = next((c["lot"] for c in checks if c["lot"]), None)
    return {
        "candidate_id": candidate_id,
        "kind": "label",
        "product_id": rows[0]["product_id"],
        "hazard_type": worst.hazard_type,
        "title_hint": f"{rows[0]['product_label']}{f' lot {lot}' if lot else ''}: "
        f"{worst.rule.replace('_', ' ')} ({worst.value})",
        "checks": checks,
        "prior_incidents": [],
    }


def load(candidate_id: str, used_by: str) -> EvidencePack | None:
    if source() == "fixtures":
        return from_fixture(candidate_id)
    stand = stand_in(candidate_id)
    if stand is None and candidate_id.startswith("recall:"):
        return _recall(candidate_id)
    if stand is None and candidate_id.startswith("label:"):
        stand = _label_stand(candidate_id, policy.current())
    if stand is None:
        return None
    pol = policy.current()
    product = _product(stand["product_id"])
    lineage = None
    if params := lineage_params(stand, pol):
        as_of = datetime.now(UTC).replace(microsecond=0)
        receipt = attest.run_attested(
            LINEAGE,
            {
                **params,
                "as_of": as_of,
                "order_lookback_days": pol.recall.order_lookback_days,
            },
            used_by=used_by,
        )
        lineage = Lineage(
            receipt_id=receipt.receipt_id,
            as_of=as_of.isoformat(),
            rows=[LineageRow.model_validate(r) for r in receipt.result],
        )
    return pack(stand, product, lineage)
