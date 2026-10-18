"""The label check's SQL on live BigQuery, in psd_test: matching by barcode, the latest spec, the check and its candidate
in one transaction, completing a check the associate picks a product for, and reading a candidate's checks back.
Gemini, the photo store and publishing are stubbed; AI.EMBED is called by the match query."""

import json
import uuid
from typing import Any

import pytest
from google.cloud import bigquery

from api import labels
from app import bq, evidence, policy
from data.load_truth import apply_ddl, load_table
from tests.sql.conftest import require_table

PRODUCT = {
    "product_id": "PTL1",
    "name": "Light-Up Dinosaur",
    "brand": "Toddlewick",
    "size": "1 unit",
    "category": "toys",
    "subcategory": "toys",
    "barcode": "2000000900016",
    "supplier_id": "SUP-T",
    "unit_price": "19.00",
    "listing_text": "Toddlewick Light-Up Dinosaur 1 unit",
    "listing_allergens": [],
    "listing_warnings": ["not suitable for children under 3 years", "button battery"],
    "listing_marks": [],
    "listing_origin": "Made in Australia",
}


def _spec(version: str, warnings: list[str], changed_at: str) -> dict[str, Any]:
    return {
        "product_id": "PTL1",
        "version": version,
        "allergens": [],
        "warnings": warnings,
        "marks": [],
        "ingredients_text": "ABS plastic, LED, coin battery",
        "origin": "Made in Australia",
        "changed_at": changed_at,
        "supplier_id": "SUP-T",
    }


SPECS = [
    _spec("v1", ["not suitable for children under 3 years"], "2026-01-01T00:00:00Z"),
    _spec(
        "v2",
        ["not suitable for children under 3 years", "button battery"],
        "2026-06-01T00:00:00Z",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def label_tables():
    require_table("psd_test")
    client = bq.client()
    apply_ddl(client, "psd_test")
    load_table(client, "psd_test", "products", [PRODUCT])
    load_table(client, "psd_test", "supplier_specs", SPECS)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setenv("PSD_DATASET", "psd_test")
    published: list[str] = []
    monkeypatch.setattr(labels.scope, "_publish_candidates", lambda: published)
    monkeypatch.setattr(
        labels,
        "store_photo",
        lambda cid, image, mime: f"gs://test-photos/labels/{cid}.jpg",
    )
    monkeypatch.setattr(
        labels, "stores", lambda: ({"store_id": "S012"}, {"store_id": "S004"})
    )
    monkeypatch.setattr(
        labels, "vocabulary", lambda: labels.Vocabulary(["milk"], [], [])
    )
    monkeypatch.setattr(labels, "allergen_names", lambda: ["milk"])
    return published


def _read(lot: str) -> labels.LabelRead:
    return labels.LabelRead(
        brand="Toddlewick",
        product_name="Light-Up Dinosaur",
        size="1 unit",
        barcode="2000000900016",
        lot=lot,
        warnings=["not suitable for children under 3 years"],
        ingredients_text="ABS plastic, LED, coin battery",
        origin="Made in Australia",
        legibility=0.95,
    )


def _check(check_id: str) -> dict[str, Any]:
    (row,) = bq.rows(
        "SELECT * FROM label_checks WHERE check_id = @c",
        [bigquery.ScalarQueryParameter("c", "STRING", check_id)],
    )
    return row


def test_a_printed_barcode_matches_and_the_latest_spec_is_the_one_compared() -> None:
    found = labels.match(_read("L1"), policy.current().labels.catalogue_match)
    assert (found.status, found.product_id, found.method) == (
        "matched",
        "PTL1",
        "barcode",
    )
    facts = labels.facts("PTL1")
    assert facts.spec_version == "v2" and "button battery" in facts.spec_warnings


def test_a_check_and_its_candidate_are_written_together(monkeypatch) -> None:
    lot = f"L-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(labels, "read_label", lambda image, mime, vocab: _read(lot))
    result = labels.check("S012", "aGVsbG8=", "image/jpeg")
    assert result["status"] == "findings" and result["max_severity"] == "critical"
    row = _check(result["check_id"])
    assert (
        row["product_id"],
        row["match_method"],
        row["lot"],
        row["candidate_id"],
    ) == (
        "PTL1",
        "barcode",
        lot,
        result["candidate_id"],
    )
    findings = (
        json.loads(row["findings"])
        if isinstance(row["findings"], str)
        else row["findings"]
    )
    assert [f["rule"] for f in findings] == ["warning_missing_on_pack"]
    (candidate,) = bq.rows(
        "SELECT * FROM incident_candidates WHERE candidate_id = @c",
        [bigquery.ScalarQueryParameter("c", "STRING", result["candidate_id"])],
    )
    assert (
        candidate["kind"],
        candidate["product_id"],
        candidate["stores"],
        candidate["published"],
    ) == (
        "label",
        "PTL1",
        ["S012"],
        False,
    )
    assert result["candidate_id"] in {
        c["candidate_id"] for c in bq.rows(labels.scope._UNPUBLISHED_SQL)
    }

    # The same defect at a second store joins the candidate; evidence then reads both checks.
    again = labels.check("S004", "aGVsbG8=", "image/jpeg")
    assert again["candidate_id"] == result["candidate_id"]
    stand = evidence._label_stand(result["candidate_id"], policy.current())
    assert [c["store_id"] for c in stand["checks"]] == ["S012", "S004"]
    assert stand["title_hint"].startswith(
        f"Toddlewick Light-Up Dinosaur 1 unit lot {lot}"
    )
    assert result["check_id"] in {r["check_id"] for r in labels.recent()}


def test_a_pick_completes_a_check_no_product_matched(monkeypatch) -> None:
    lot = f"L-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(
        labels,
        "read_label",
        lambda image, mime, vocab: _read(lot).model_copy(update={"barcode": None}),
    )
    monkeypatch.setattr(
        labels,
        "match",
        lambda read, rule: labels.Matched(
            "needs_product",
            options=[
                {"product_id": "PTL1", "label": "Toddlewick Light-Up Dinosaur 1 unit"}
            ],
        ),
    )
    result = labels.check("S012", "aGVsbG8=", "image/jpeg")
    assert result["status"] == "needs_product"
    assert _check(result["check_id"])["match_options"] == ["PTL1"]
    done = labels.choose(result["check_id"], "PTL1", "S012")
    assert done["status"] == "findings" and done["candidate_id"]
    row = _check(result["check_id"])
    assert (row["status"], row["match_method"], row["candidate_id"]) == (
        "findings",
        "associate",
        done["candidate_id"],
    )
    with pytest.raises(labels.LabelError):
        labels.choose(result["check_id"], "PTL1", "S012")


def test_a_retake_keeps_no_read(monkeypatch) -> None:
    monkeypatch.setattr(
        labels,
        "read_label",
        lambda image, mime, vocab: _read("L9").model_copy(update={"legibility": 0.2}),
    )
    result = labels.check("S012", "aGVsbG8=", "image/jpeg")
    row = _check(result["check_id"])
    assert (row["status"], row["label_read"], row["lot"], row["candidate_id"]) == (
        "retake",
        None,
        None,
        None,
    )
    assert row["photo_uri"].startswith("gs://test-photos/labels/lc-")
