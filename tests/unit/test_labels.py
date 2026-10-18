import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import desk, labels, main, shelves, storelinks
from api.labels import Facts, LabelRead, Matched, diff_label
from app import evidence
from app.knowledge import load_bundle
from data import gen_labels
from data.gen_catalogue import build_catalogue, load_truth

ANCHOR = datetime(2026, 10, 17, tzinfo=UTC)


@pytest.fixture(scope="module")
def world():
    truth = load_truth()
    catalogue = build_catalogue(truth, ANCHOR)
    return truth, catalogue, gen_labels.packs(truth, ANCHOR)


@pytest.fixture
def names(verified_bundle) -> list[str]:
    return list(load_bundle(verified_bundle).get(labels.ALLERGENS).meta["names"])


def _facts(catalogue, pid: str) -> Facts:
    p = next(x for x in catalogue.products if x["product_id"] == pid)
    s = [x for x in catalogue.specs if x["product_id"] == pid][-1]
    return Facts(
        product_id=pid,
        brand=p["brand"],
        name=p["name"],
        size=p["size"],
        listing_allergens=p["listing_allergens"],
        listing_warnings=p["listing_warnings"],
        listing_marks=p["listing_marks"],
        listing_origin=p["listing_origin"],
        spec_version=s["version"],
        spec_allergens=s["allergens"],
        spec_warnings=s["warnings"],
        spec_marks=s["marks"],
        spec_ingredients=s["ingredients_text"],
    )


def _exact(pack: gen_labels.Pack) -> LabelRead:
    """A read that transcribes every printed fact exactly."""
    return LabelRead(
        brand=pack.brand,
        product_name=pack.name,
        size=pack.size,
        barcode=pack.barcode,
        lot=pack.lot,
        allergens=pack.allergens,
        warnings=pack.warnings,
        marks=pack.marks,
        ingredients_text=("Ingredients: " if pack.category == "food" else "Materials: ")
        + pack.ingredients,
        origin=pack.origin,
        legibility=1.0,
    )


def test_exact_reads_find_exactly_the_planted_defects(world, pol, names) -> None:
    truth, catalogue, packs = world
    for name, pack in packs.items():
        found = diff_label(_exact(pack), _facts(catalogue, pack.product_id), pol, names)
        assert sorted(f.rule for f in found) == sorted(pack.expected_rules), (
            name,
            found,
        )
    assert {f["id"] for f in truth["label_fixtures"]} <= set(packs)
    assert sum(1 for n in packs if n.startswith("clean_")) == 8


def test_each_fixture_finding_takes_its_severity_from_policy(world, pol, names) -> None:
    truth, catalogue, packs = world
    for f in truth["label_fixtures"]:
        found = diff_label(
            _exact(packs[f["id"]]), _facts(catalogue, f["product_id"]), pol, names
        )
        worst = pol.max_severity([x.severity for x in found]) if found else None
        assert worst == f["expected_severity"], f["id"]
    dino = diff_label(
        _exact(packs["dinosaur_battery_warning"]),
        _facts(catalogue, "P50211"),
        pol,
        names,
    )
    assert [(x.value, x.severity, x.hazard_type, x.actions) for x in dino] == [
        ("button battery", "critical", "injury", ["hold", "supplier_notice"])
    ]


def _facts_of(**changes) -> Facts:
    base = {
        "product_id": "P1",
        "brand": "Brand",
        "name": "Thing",
        "size": "500g",
        "listing_allergens": ["milk"],
        "listing_warnings": [],
        "listing_marks": [],
        "listing_origin": "Product of Australia",
        "spec_version": "v1",
        "spec_allergens": ["milk"],
        "spec_warnings": [],
        "spec_marks": [],
        "spec_ingredients": "Milk, sugar, cultures (A, B)",
    }
    return Facts(**{**base, **changes})


def _read(**changes) -> LabelRead:
    base = {
        "allergens": ["milk"],
        "ingredients_text": "Milk, sugar, cultures (A, B)",
        "origin": "Product of Australia",
        "legibility": 1.0,
    }
    return LabelRead(**{**base, **changes})


@pytest.mark.parametrize(
    ("read", "facts", "expected"),
    [
        (
            {"allergens": []},
            {},
            [("allergen_undeclared_on_pack", "milk", "critical")],
        ),
        (
            {"allergens": ["milk", "soya"]},
            {"spec_allergens": ["milk", "soy"]},
            [("allergen_missing_in_listing", "soy", "high")],
        ),
        (
            {},
            {"listing_allergens": ["milk", "egg"]},
            [("allergen_extra_in_listing", "egg", "low")],
        ),
        ({"allergens": ["Milk", "gluten"]}, {}, []),
        (
            {"warnings": ["keep out of reach of children"]},
            {"spec_warnings": ["keep out of reach of children"]},
            [("warning_missing_in_listing", "keep out of reach of children", "medium")],
        ),
        (
            {},
            {"spec_warnings": ["harmful if swallowed"]},
            [("warning_missing_on_pack", "harmful if swallowed", "high")],
        ),
        ({}, {"spec_marks": ["RCM"]}, [("mark_missing_on_pack", "RCM", "high")]),
        (
            {"ingredients_text": "Milk, sugar, cultures (A, B), gelatine"},
            {},
            [("ingredients_differ", "gelatine", "medium")],
        ),
        ({"ingredients_text": "Ingredients: milk, sugar, cultures (A,B)"}, {}, []),
        (
            {"origin": "Product of New Zealand"},
            {},
            [("origin_differs", "Product of New Zealand", "low")],
        ),
    ],
)
def test_each_rule(read, facts, expected, pol, names) -> None:
    found = diff_label(_read(**read), _facts_of(**facts), pol, names)
    assert [(f.rule, f.value, f.severity) for f in found] == expected


def test_a_defect_signature_ignores_the_store_and_keeps_the_lot(pol) -> None:
    f = pol.finding_for("warning_missing_on_pack", "warnings", "button battery")
    a = labels.candidate_id("P50211", "L2026-0311", [f])
    assert a == labels.candidate_id("P50211", "L2026-0311", [f])
    assert a != labels.candidate_id("P50211", "L2026-0312", [f])
    assert a.startswith("label:P50211:") and len(a.rsplit(":", 1)[1]) == 6


@pytest.fixture
def stubbed(monkeypatch, world, names):
    """labels.check with Gemini, the photo store, matching and BigQuery stubbed; returns what it wrote and published."""
    _, catalogue, packs = world
    seen: dict[str, Any] = {"scripts": [], "params": [], "published": 0}
    monkeypatch.setattr(
        labels, "stores", lambda: ({"store_id": "S012"}, {"store_id": "S004"})
    )
    monkeypatch.setattr(
        labels, "vocabulary", lambda: labels.Vocabulary(names, [], ["RCM"])
    )
    monkeypatch.setattr(
        labels, "store_photo", lambda cid, image, mime: f"gs://photos/labels/{cid}.jpg"
    )
    monkeypatch.setattr(labels, "facts", lambda pid: _facts(catalogue, pid))

    def record(statements, params):
        seen["scripts"].append("".join(statements))
        seen["params"].append(
            {p.name: getattr(p, "value", getattr(p, "values", None)) for p in params}
        )

    def publish():
        seen["published"] += 1
        return ["published"]

    monkeypatch.setattr(labels, "_record", record)
    monkeypatch.setattr(labels.scope, "_publish_candidates", publish)

    def go(read: LabelRead, found: Matched, store_id: str = "S012"):
        monkeypatch.setattr(labels, "read_label", lambda image, mime, vocab: read)
        monkeypatch.setattr(labels, "match", lambda r, rule: found)
        return labels.check(store_id, "aGVsbG8=", "image/jpeg"), seen

    return go, packs


def test_a_critical_finding_raises_a_candidate_in_the_same_write(stubbed) -> None:
    go, packs = stubbed
    result, seen = go(
        _exact(packs["dinosaur_battery_warning"]),
        Matched("matched", "P50211", "barcode"),
    )
    assert result["status"] == "findings" and result["max_severity"] == "critical"
    assert result["candidate_id"].startswith("label:P50211:")
    (script,) = seen["scripts"]
    assert (
        "INSERT INTO label_checks" in script and "MERGE incident_candidates" in script
    )
    assert seen["published"] == 1
    assert seen["params"][0]["photo_uri"].startswith("gs://photos/labels/lc-")


def test_the_same_defect_at_a_second_store_is_the_same_candidate(stubbed) -> None:
    go, packs = stubbed
    read = _exact(packs["dinosaur_battery_warning"])
    first, _ = go(read, Matched("matched", "P50211", "barcode"), "S012")
    second, _ = go(read, Matched("matched", "P50211", "barcode"), "S004")
    assert first["candidate_id"] == second["candidate_id"]
    assert first["check_id"] != second["check_id"]


def test_a_listing_only_finding_is_high_and_a_clean_pack_raises_nothing(
    stubbed,
) -> None:
    go, packs = stubbed
    muesli, _ = go(
        _exact(packs["muesli_almond"]), Matched("matched", "P31007", "barcode")
    )
    assert muesli["max_severity"] == "high" and muesli["candidate_id"]
    clean, seen = go(
        _exact(packs["yoghurt_clean"]), Matched("matched", "P48812", "barcode")
    )
    assert clean["status"] == "checked" and clean["candidate_id"] is None
    assert "MERGE incident_candidates" not in seen["scripts"][-1]


def test_an_unreadable_photo_asks_for_a_retake_and_keeps_only_the_photo(
    stubbed,
) -> None:
    go, packs = stubbed
    read = _exact(packs["dinosaur_battery_warning"]).model_copy(
        update={"legibility": 0.3}
    )
    result, seen = go(read, Matched("matched", "P50211", "barcode"))
    assert result["status"] == "retake" and result["findings"] == []
    stored = seen["params"][-1]
    assert (
        stored["label_read"] is None
        and stored["lot"] is None
        and stored["candidate_id"] is None
    )
    assert seen["published"] == 0


def test_no_match_offers_products_and_a_pick_completes_the_check(
    stubbed, monkeypatch
) -> None:
    go, packs = stubbed
    read = _exact(packs["kettle_rcm"])
    options = [
        {"product_id": "P62240", "label": "Hearthwell Rapid Kettle 1.7L"},
        {"product_id": "P9", "label": "x"},
    ]
    result, seen = go(read, Matched("needs_product", options=options))
    assert result["status"] == "needs_product" and result["options"] == options
    assert seen["params"][-1]["match_options"] == ["P62240", "P9"]
    stored = {
        "check_id": result["check_id"],
        "store_id": "S012",
        "status": "needs_product",
        "lot": "L2026-0442",
        "match_options": ["P62240", "P9"],
        "label_read": read.model_dump_json(),
    }
    monkeypatch.setattr(labels.bq, "rows", lambda sql, params=(): [stored])
    monkeypatch.setattr(labels, "allergen_names", lambda: [])
    with pytest.raises(labels.LabelError):
        labels.choose(result["check_id"], "P62240", "S004")
    done = labels.choose(result["check_id"], "P62240", "S012")
    assert done["status"] == "findings" and [f["rule"] for f in done["findings"]] == [
        "mark_missing_on_pack"
    ]
    assert "UPDATE label_checks" in seen["scripts"][-1]
    with pytest.raises(labels.LabelError):
        labels.choose(result["check_id"], "P00000", "S012")


def test_a_photo_must_be_an_image_of_a_sensible_size() -> None:
    with pytest.raises(labels.LabelError):
        labels.decode_photo("aGVsbG8=", "application/pdf")
    with pytest.raises(labels.LabelError):
        labels.decode_photo("not base64!", "image/jpeg")
    assert labels.decode_photo("aGVsbG8=", "image/png") == b"hello"


def test_an_unknown_store_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(labels, "stores", lambda: ({"store_id": "S012"},))
    with pytest.raises(labels.LabelError):
        labels.check("S999", "aGVsbG8=", "image/jpeg")


STORES = (
    {"store_id": "S012", "name": "CalmChaosRetail Twelve", "state": "NSW"},
    {"store_id": "S004", "name": "CalmChaosRetail Four", "state": "VIC"},
)
INCIDENTS = [
    {
        "incident_id": "inc-1",
        "title": "Toddlewick Light-Up Dinosaur lot L2026-0311",
        "severity": "critical",
        "kind": "label",
        "product_id": "P50211",
        "product_name": "Toddlewick Light-Up Dinosaur 1 unit",
        "card": "draft text no store should see",
        "customer_message": {"subject": "s", "body": "b"},
        "tasks": [
            {
                "task_id": "t-12",
                "store_id": "S012",
                "kind": "hold",
                "code": "L2026-0311",
                "status": "open",
            },
            {
                "task_id": "t-04",
                "store_id": "S004",
                "kind": "hold",
                "code": "L2026-0311",
                "status": "open",
            },
        ],
    }
]


@pytest.fixture
def remote(monkeypatch) -> TestClient:
    """A browser on another host, with the coordinator passcode and the store link salt configured."""
    monkeypatch.setenv("PSD_DESK_PASSCODE", "lark-2026")
    monkeypatch.setenv("PSD_STORE_TOKEN_SALT", "salt-for-tests")
    monkeypatch.setattr(labels, "stores", lambda: STORES)
    return TestClient(main.app, client=("203.0.113.9", 50000))


def _as(store_id: str) -> dict[str, str]:
    return {
        "X-Store-Id": store_id,
        "X-Store-Token": storelinks.token(store_id, "salt-for-tests"),
    }


@pytest.fixture
def agents_calls(monkeypatch) -> list:
    calls = []

    def fake(method, path, body=None, timeout=60):
        calls.append((method, path))
        return INCIDENTS if method == "GET" else {"status": "verifying"}

    monkeypatch.setattr(desk, "_agents", fake)
    return calls


def test_a_store_link_opens_only_its_own_store(remote) -> None:
    page = remote.get("/store")
    assert page.status_code == 200 and "Check a label" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert remote.get("/store/api/me").status_code == 401
    assert (
        remote.get(
            "/store/api/me", headers={"X-Desk-Passcode": "lark-2026"}
        ).status_code
        == 401
    )
    forged = {"X-Store-Id": "S004", "X-Store-Token": _as("S012")["X-Store-Token"]}
    assert remote.get("/store/api/me", headers=forged).status_code == 401
    assert remote.get("/store/api/me", headers=_as("S012")).json()["store_id"] == "S012"


def test_a_store_sees_only_its_tasks_and_none_of_the_draft(
    remote, agents_calls
) -> None:
    (task,) = remote.get("/store/api/tasks", headers=_as("S012")).json()
    assert task["task_id"] == "t-12" and task["incident"]["severity"] == "critical"
    assert "card" not in json.dumps(task) and "customer_message" not in json.dumps(task)


def test_a_shelf_photo_for_another_stores_task_is_refused(
    remote, agents_calls, monkeypatch
) -> None:
    checked = []

    def check(task, image, mime):
        checked.append(task["task_id"])
        return {"task_id": task["task_id"], "verdict": "verified_clear"}

    monkeypatch.setattr(shelves, "check", check)
    photo = {"image_base64": "aGVsbG8=", "mime_type": "image/jpeg"}
    other = remote.post("/store/api/tasks/t-04/photo", json=photo, headers=_as("S012"))
    assert other.status_code == 404 and checked == []
    own = remote.post("/store/api/tasks/t-12/photo", json=photo, headers=_as("S012"))
    assert own.status_code == 200 and checked == ["t-12"]
    assert own.json()["verdict"] == "verified_clear" and own.json()["tasks"]


def test_a_store_closes_a_task_only_with_a_photo(remote, agents_calls) -> None:
    r = remote.post(
        "/store/api/tasks/t-12/verdict",
        json={"verdict": "verified_clear"},
        headers=_as("S012"),
    )
    assert r.status_code in (404, 405)
    assert ("POST", "/desk/tasks/t-12/verdict") not in agents_calls


def test_a_shelf_check_refusal_reaches_the_store_with_its_reason(
    remote, agents_calls, monkeypatch
) -> None:
    def check(task, image, mime):
        raise shelves.ShelfError("not until the policy is reviewed", status=503)

    monkeypatch.setattr(shelves, "check", check)
    r = remote.post(
        "/store/api/tasks/t-12/photo",
        json={"image_base64": "aGVsbG8=", "mime_type": "image/jpeg"},
        headers=_as("S012"),
    )
    assert r.status_code == 503 and "reviewed" in r.json()["detail"]


def test_a_label_check_acts_for_the_links_store(remote, monkeypatch) -> None:
    seen = []

    def check(store_id, image, mime):
        seen.append(store_id)
        raise labels.LabelError("not a usable photo")

    monkeypatch.setattr(labels, "check", check)
    r = remote.post(
        "/store/api/labels", json={"image_base64": "aGVsbG8="}, headers=_as("S004")
    )
    assert r.status_code == 400 and "usable" in r.text and seen == ["S004"]


def test_only_the_coordinator_hands_out_store_links(remote, agents_calls) -> None:
    assert remote.get("/desk/api/store-link/S012").status_code == 401
    link = remote.get(
        "/desk/api/store-link/S012", headers={"X-Desk-Passcode": "lark-2026"}
    ).json()["url"]
    assert link == "/store?store=S012#token=" + _as("S012")["X-Store-Token"]
    incidents = remote.get(
        "/desk/api/incidents", headers={"X-Desk-Passcode": "lark-2026"}
    ).json()
    assert {t["store_link"] for t in incidents[0]["tasks"]} == {
        storelinks.link("S012"),
        storelinks.link("S004"),
    }


def test_without_a_salt_store_pages_serve_only_this_machine(monkeypatch) -> None:
    monkeypatch.delenv("PSD_STORE_TOKEN_SALT", raising=False)
    monkeypatch.setattr(labels, "stores", lambda: STORES)
    far = TestClient(main.app, client=("203.0.113.9", 1)).get(
        "/store/api/me", headers={"X-Store-Id": "S012"}
    )
    near = TestClient(main.app, client=("127.0.0.1", 1)).get(
        "/store/api/me", headers={"X-Store-Id": "S012"}
    )
    assert (far.status_code, near.status_code) == (403, 200)
    assert storelinks.link("S012") == "/store?store=S012"


def test_a_label_candidate_reads_its_checks_from_bigquery(monkeypatch, pol) -> None:
    monkeypatch.setenv("PSD_EVIDENCE_SOURCE", "bigquery")
    finding = pol.finding_for("warning_missing_on_pack", "warnings", "button battery")
    rows = [
        {
            "check_id": "lc-1",
            "store_id": "S012",
            "checked_at": "2026-10-17T10:00:00+00:00",
            "photo_uri": "gs://photos/labels/lc-1.jpg",
            "product_id": "P50211",
            "lot": "L2026-0311",
            "findings": json.dumps([finding.model_dump(mode="json")]),
            "product_label": "Toddlewick Light-Up Dinosaur 1 unit",
        }
    ]
    monkeypatch.setattr(evidence.bq, "rows", lambda sql, params=(): rows)
    stand = evidence._label_stand("label:P50211:abcdef", pol)
    assert (
        stand["hazard_type"] == "injury" and stand["checks"][0]["lot"] == "L2026-0311"
    )
    assert evidence.lineage_params(stand, pol)["codes"] == ["L2026-0311"]
    assert stand["title_hint"].startswith(
        "Toddlewick Light-Up Dinosaur 1 unit lot L2026-0311"
    )


def test_ean13_bars_encode_the_digits() -> None:
    bits = gen_labels.ean13_bits("2000000502113")
    assert (
        len(bits) == 95
        and bits.startswith("101")
        and bits.endswith("101")
        and bits[45:50] == "01010"
    )


def test_the_allergen_names_load_from_the_reviewed_bundle() -> None:
    names = labels.allergen_names()
    assert "milk" in names and "Brazil nut" in names and "gluten" not in names
