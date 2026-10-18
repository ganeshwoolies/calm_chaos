import hashlib
import json
from collections import Counter

import pytest

from app.knowledge import load_bundle
from data.gen_catalogue import anchor_from, build_catalogue, load_truth
from data.gen_supply import build_supply
from tests.knowledge_copy import REPO_BUNDLE

# Major product brands sold in Australia. No generated brand may match one.
REAL_BRANDS = {
    "arnott's",
    "kellogg's",
    "sanitarium",
    "uncle tobys",
    "cadbury",
    "nestle",
    "bega",
    "devondale",
    "pauls",
    "dairy farmers",
    "a2",
    "chobani",
    "jalna",
    "vaalia",
    "yoplait",
    "bulla",
    "streets",
    "peters",
    "smith's",
    "doritos",
    "kettle",
    "red rock deli",
    "coca-cola",
    "pepsi",
    "schweppes",
    "bundaberg",
    "golden circle",
    "spc",
    "heinz",
    "masterfoods",
    "leggo's",
    "dolmio",
    "san remo",
    "barilla",
    "sunrice",
    "tip top",
    "helga's",
    "wonder",
    "vegemite",
    "kraft",
    "cottee's",
    "ixl",
    "nescafe",
    "moccona",
    "lipton",
    "bushells",
    "twinings",
    "birds eye",
    "mccain",
    "john west",
    "sirena",
    "ajax",
    "morning fresh",
    "dettol",
    "domestos",
    "harpic",
    "finish",
    "omo",
    "cold power",
    "sorbent",
    "kleenex",
    "quilton",
    "glad",
    "breville",
    "sunbeam",
    "kambrook",
    "philips",
    "russell hobbs",
    "dyson",
    "panasonic",
    "fisher-price",
    "lego",
    "mattel",
    "hasbro",
    "vtech",
    "melissa & doug",
    "pantene",
    "head & shoulders",
    "dove",
    "nivea",
    "garnier",
    "l'oreal",
    "neutrogena",
    "cancer council",
    "banana boat",
    "colgate",
    "oral-b",
    "sensodyne",
    "rexona",
    "lynx",
    "palmolive",
    "qv",
    "cetaphil",
    "carman's",
    "freedom foods",
    "macro",
    "lurpak",
    "western star",
    "mainland",
    "natvia",
    "uncle ben's",
    "patak's",
    "old el paso",
    "continental",
    "maggi",
    "praise",
    "s&w",
    "ardmona",
}


@pytest.fixture(scope="module")
def truth():
    return load_truth()


@pytest.fixture(scope="module")
def world(truth):
    anchor = anchor_from(truth)
    catalogue = build_catalogue(truth, anchor)
    return catalogue, build_supply(truth, catalogue, anchor)


def _digest(*parts) -> str:
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, default=str).encode()
    ).hexdigest()


def test_the_same_seed_builds_the_same_world(truth, world) -> None:
    anchor = anchor_from(truth)
    catalogue = build_catalogue(truth, anchor)
    supply = build_supply(truth, catalogue, anchor)
    before, after = world, (catalogue, supply)
    assert _digest(before[0].products, before[1].deliveries[:5000]) == _digest(
        after[0].products, after[1].deliveries[:5000]
    )


def test_catalogue_counts_and_names(truth, world) -> None:
    catalogue, _ = world
    assert Counter(p["category"] for p in catalogue.products) == truth["catalogue"]
    names = [(p["brand"], p["name"], p["size"]) for p in catalogue.products]
    assert len(set(names)) == len(names)
    assert not {p["brand"].lower() for p in catalogue.products} & REAL_BRANDS


def test_allergens_are_required_names(world) -> None:
    catalogue, _ = world
    names = set(load_bundle(REPO_BUNDLE).get("/references/allergens.md").meta["names"])
    used = {a for s in catalogue.specs for a in s["allergens"]} | {
        a for p in catalogue.products for a in p["listing_allergens"]
    }
    assert used <= names, used - names


def test_listings_follow_the_latest_spec_except_planted_defects(world) -> None:
    catalogue, _ = world
    latest = {}
    for s in catalogue.specs:
        if s["version"] > latest.get(s["product_id"], {}).get("version", ""):
            latest[s["product_id"]] = s
    differing = {
        p["product_id"]
        for p in catalogue.products
        if (p["listing_allergens"], p["listing_warnings"], p["listing_marks"])
        != (
            latest[p["product_id"]]["allergens"],
            latest[p["product_id"]]["warnings"],
            latest[p["product_id"]]["marks"],
        )
    }
    assert differing == {"P31007"}


def test_planted_scenarios_match_the_truth(truth, world) -> None:
    _, supply = world
    planted = {
        s["id"]: s
        for s in truth["recall_scenarios"] + truth["label_fixtures"]
        if s.get("batch")
    }
    batch_of = {
        b["code"]: b["batch_id"]
        for b in supply.batches
        if b["batch_id"] in supply.planted_batch_ids
    }
    for sid, s in planted.items():
        batch_id = batch_of[s["batch"]["code"]]
        delivered_to = {
            d["store_id"] for d in supply.deliveries if d["batch_id"] == batch_id
        }
        assert delivered_to == set(s.get("stores_on_hand") or {}) | set(
            s.get("stale_stores") or {}
        ), sid
        stock = {
            r["store_id"]: r["on_hand"]
            for r in supply.store_stock
            if r["batch_id"] == batch_id and r["on_hand"]
        }
        assert stock == (s.get("stores_on_hand") or {}), sid
        orders = {
            line["order_id"]
            for line in supply.order_lines
            if line["batch_id"] == batch_id
        }
        assert len(orders) == s.get("online_orders", 0), sid


def test_no_background_row_touches_a_planted_batch(truth, world) -> None:
    _, supply = world
    planted_orders = {o for r in supply.truth_recalls for o in r["online_orders"]}
    assert not [
        line
        for line in supply.order_lines
        if line["batch_id"] in supply.planted_batch_ids
        and line["order_id"] not in planted_orders
    ]
    planted_stores = {
        sid
        for s in truth["recall_scenarios"] + truth["label_fixtures"]
        for sid in list(s.get("stores_on_hand") or {})
        + list(s.get("stale_stores") or {})
    }
    assert all(
        d["store_id"] in planted_stores
        for d in supply.deliveries
        if d["batch_id"] in supply.planted_batch_ids
    )


def test_truth_tables(world) -> None:
    _, supply = world
    recalls = {r["scenario"]: r for r in supply.truth_recalls}
    assert (
        len(recalls["yoghurt_listeria"]["stores_on_hand"]),
        recalls["yoghurt_listeria"]["units_on_hand"],
    ) == (14, 212)
    assert len(recalls["yoghurt_listeria"]["online_orders"]) == 37
    assert (
        recalls["kettle_no_exposure"]["stores_on_hand"] == []
        and recalls["yoghurt_500g_decoy"]["product_id"] is None
    )
    labels = {r["fixture"]: r for r in supply.truth_labels}
    assert (
        len(labels["dinosaur_battery_warning"]["hold_stores"]),
        labels["dinosaur_battery_warning"]["units_on_hand"],
    ) == (11, 59)
