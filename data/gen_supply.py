"""Builds stores, batches, deliveries, stock and online orders around the catalogue, and the truth tables.

Planted batches go to exactly the stores and orders data/truth.yaml names, and no background row touches a planted
batch, so a scenario's lineage is its planted rows and nothing else.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from data.catalogue_vocab import PRODUCT_TYPES, STATE_CENTRES, SUBURBS
from data.gen_catalogue import Catalogue, iso, rng

# Share of stores ranging a product, by category.
RANGING = {
    "food": (0.5, 0.85),
    "household": (0.4, 0.7),
    "electrical": (0.15, 0.4),
    "toys": (0.15, 0.4),
    "cosmetics": (0.3, 0.6),
}
NON_FOOD_CADENCE_DAYS = 30


@dataclass(frozen=True)
class Supply:
    stores: list[dict[str, Any]]
    batches: list[dict[str, Any]]
    deliveries: list[dict[str, Any]]
    store_stock: list[dict[str, Any]]
    online_orders: list[dict[str, Any]]
    order_lines: list[dict[str, Any]]
    truth_recalls: list[dict[str, Any]]
    truth_labels: list[dict[str, Any]]
    planted_batch_ids: frozenset[str]

    def tables(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "stores": self.stores,
            "batches": self.batches,
            "deliveries": self.deliveries,
            "store_stock": self.store_stock,
            "online_orders": self.online_orders,
            "order_lines": self.order_lines,
            "truth_recalls": self.truth_recalls,
            "truth_labels": self.truth_labels,
        }


def _cadence(type_key: str) -> int:
    shelf = PRODUCT_TYPES[type_key].shelf_life_days
    if shelf is None:
        return NON_FOOD_CADENCE_DAYS
    return 7 if shelf <= 14 else 14 if shelf <= 60 else 28


def _batch_id(product_id: str, code: str, kind: str) -> str:
    return f"{'BAT' if kind == 'batch' else 'LOT'}-{product_id}-{code.split('-', 1)[1]}"


def _stores(truth: dict[str, Any]) -> list[dict[str, Any]]:
    dc_of = {state: dc for dc, states in truth["dcs"].items() for state in states}
    rows = []
    for state, suburbs in SUBURBS.items():
        lat, lng = STATE_CENTRES[state]
        for suburb in suburbs:
            sid = f"S{len(rows) + 1:03d}"
            r = rng(truth["seed"], "store", sid)
            rows.append(
                {
                    "store_id": sid,
                    "name": f"{truth['retailer']} {suburb}",
                    "state": state,
                    "dc_id": dc_of[state],
                    "lat": round(lat + r.uniform(-0.6, 0.6), 4),
                    "lng": round(lng + r.uniform(-0.6, 0.6), 4),
                }
            )
    return rows


def build_supply(
    truth: dict[str, Any], catalogue: Catalogue, anchor: datetime
) -> Supply:
    seed = truth["seed"]
    history = truth["history_days"]
    stores = _stores(truth)
    store_ids = [s["store_id"] for s in stores]
    dc_of = {s["store_id"]: s["dc_id"] for s in stores}
    products = {p["product_id"]: p for p in catalogue.products}

    def at(days_ago: float) -> datetime:
        return anchor - timedelta(days=days_ago)

    planted_scenarios = [
        s for s in truth["recall_scenarios"] + truth["label_fixtures"] if s.get("batch")
    ]
    planted_codes: dict[str, set[str]] = {}
    for s in planted_scenarios:
        planted_codes.setdefault(s["product_id"], set()).add(s["batch"]["code"])

    batches: list[dict[str, Any]] = []
    deliveries: list[dict[str, Any]] = []
    store_stock: list[dict[str, Any]] = []
    # product -> [(produced_days_ago, batch_id)], newest first, for picking the batch an online order line carries
    regular_batches: dict[str, list[tuple[float, str]]] = {}
    ranged_at: dict[str, list[str]] = {s: [] for s in store_ids}
    aisles: dict[tuple[str, str], str] = {}

    def aisle(store_id: str, subcategory: str) -> str:
        key = (store_id, subcategory)
        if key not in aisles:
            aisles[key] = str(rng(seed, "aisle", store_id, subcategory).randint(1, 24))
        return aisles[key]

    def add_batch(
        pid: str,
        code: str,
        produced_days_ago: float,
        best_before_days_ahead: float | None = None,
    ) -> dict:
        ptype = PRODUCT_TYPES[catalogue.types[pid]]
        kind = "batch" if ptype.category == "food" else "lot"
        produced = at(produced_days_ago)
        if ptype.shelf_life_days is None:
            best_before = None
        elif best_before_days_ahead is not None:
            best_before = (
                (anchor + timedelta(days=best_before_days_ahead)).date().isoformat()
            )
        else:
            best_before = (
                (produced + timedelta(days=ptype.shelf_life_days)).date().isoformat()
            )
        row = {
            "batch_id": _batch_id(pid, code, kind),
            "product_id": pid,
            "kind": kind,
            "code": code,
            "produced_on": produced.date().isoformat(),
            "best_before": best_before,
            "supplier_id": products[pid]["supplier_id"],
        }
        batches.append(row)
        return row

    def deliver(batch: dict, store_id: str, days_ago: float, qty: int) -> None:
        deliveries.append(
            {
                "delivery_id": f"D{len(deliveries) + 1:07d}",
                "batch_id": batch["batch_id"],
                "dc_id": dc_of[store_id],
                "store_id": store_id,
                "delivered_at": iso(at(days_ago)),
                "qty": qty,
            }
        )

    # Background: every product ranged at a share of stores, a batch every cadence, one delivery per batch and store.
    fixed_codes = truth.get("regular_codes") or {}
    for pid, product in products.items():
        key = catalogue.types[pid]
        ptype = PRODUCT_TYPES[key]
        r = rng(seed, "supply", pid)
        low, high = RANGING[ptype.category]
        ranged = sorted(
            r.sample(store_ids, round(len(store_ids) * r.uniform(low, high)))
        )
        for sid in ranged:
            ranged_at[sid].append(pid)
        cadence = _cadence(key)
        offsets = []
        d = r.uniform(0.5, cadence)
        while d <= history:
            offsets.append(d)
            d += cadence
        offsets.sort(reverse=True)  # oldest first
        food = ptype.category == "food"
        if pid in fixed_codes:
            codes = list(fixed_codes[pid])[-len(offsets) :]
            offsets = offsets[-len(codes) :]
        else:
            number = r.randint(100, 800) if food else r.randint(1000, 8000)
            codes = []
            for _ in offsets:
                while (
                    code := f"B2026-{number:03d}" if food else f"L2026-{number:04d}"
                ) in planted_codes.get(pid, ()):
                    number += 1
                codes.append(code)
                number += 1
        newest_per_store: dict[str, tuple[float, int, dict]] = {}
        for days_ago, code in zip(offsets, codes, strict=True):
            batch = add_batch(pid, code, days_ago)
            regular_batches.setdefault(pid, []).append((days_ago, batch["batch_id"]))
            for sid in ranged:
                delivered_days_ago = days_ago - r.uniform(1, 4)
                if delivered_days_ago < 0.05:
                    continue
                qty = r.randint(*ptype.qty)
                deliver(batch, sid, delivered_days_ago, qty)
                newest_per_store[sid] = (delivered_days_ago, qty, batch)
        regular_batches.get(pid, []).sort()
        for sid, (_, qty, batch) in sorted(newest_per_store.items()):
            store_stock.append(
                {
                    "store_id": sid,
                    "product_id": pid,
                    "batch_id": batch["batch_id"],
                    "on_hand": r.randint(0, qty),
                    "aisle": aisle(sid, product["subcategory"]),
                    "as_of": iso(anchor),
                }
            )

    # Planted scenario batches: exactly the deliveries, stock and orders the truth names.
    planted_ids: set[str] = set()
    planted_orders: dict[str, list[str]] = {}
    online_orders: list[dict[str, Any]] = []
    order_lines: list[dict[str, Any]] = []
    order_number = 900000
    for s in planted_scenarios:
        pid = s["product_id"]
        spec = s["batch"]
        batch = add_batch(
            pid,
            spec["code"],
            spec["produced_days_ago"],
            spec.get("best_before_days_ahead"),
        )
        planted_ids.add(batch["batch_id"])
        on_hand = s.get("stores_on_hand") or {}
        days = s.get("delivered_days_ago") or [0]
        for i, (sid, units) in enumerate(on_hand.items()):
            deliver(batch, sid, days[i % len(days)], s["delivered_qty"])
            store_stock.append(
                {
                    "store_id": sid,
                    "product_id": pid,
                    "batch_id": batch["batch_id"],
                    "on_hand": units,
                    "aisle": aisle(sid, products[pid]["subcategory"]),
                    "as_of": iso(anchor),
                }
            )
        for sid, stale in (s.get("stale_stores") or {}).items():
            deliver(batch, sid, stale["delivered_days_ago"], stale["delivered_qty"])
            store_stock.append(
                {
                    "store_id": sid,
                    "product_id": pid,
                    "batch_id": batch["batch_id"],
                    "on_hand": 0,
                    "aisle": aisle(sid, products[pid]["subcategory"]),
                    "as_of": iso(anchor),
                }
            )
        pickup = list(on_hand) or store_ids
        ordered_days = s.get("ordered_days_ago") or [1]
        r = rng(seed, "planted-orders", s["id"])
        for i in range(s.get("online_orders", 0)):
            order_number += 1
            oid = f"O-{order_number}"
            online_orders.append(
                {
                    "order_id": oid,
                    "customer_ref": f"cust-{r.getrandbits(32):08x}",
                    "store_id": pickup[i % len(pickup)],
                    "ordered_at": iso(
                        at(ordered_days[i % len(ordered_days)] + r.uniform(0, 0.5))
                    ),
                    "status": r.choice(("collected", "delivered")),
                    "channel_pref": r.choice(("email", "sms", "app")),
                }
            )
            order_lines.append(
                {
                    "order_id": oid,
                    "product_id": pid,
                    "batch_id": batch["batch_id"],
                    "qty": 1,
                }
            )
            planted_orders.setdefault(s["id"], []).append(oid)

    # Background online orders over the history, each line carrying the newest batch produced a day before the order.
    r = rng(seed, "orders")
    number = 0
    for day in range(history):
        for _ in range(truth["online_orders_per_day"]):
            sid = r.choice(store_ids)
            ordered_days_ago = day + r.random()
            lines = []
            for pid in r.sample(
                ranged_at[sid], min(len(ranged_at[sid]), r.randint(1, 5))
            ):
                batch_id = next(
                    (
                        b
                        for d, b in regular_batches.get(pid, [])
                        if d >= ordered_days_ago + 1
                    ),
                    None,
                )
                if batch_id:
                    lines.append(
                        {
                            "product_id": pid,
                            "batch_id": batch_id,
                            "qty": r.randint(1, 3),
                        }
                    )
            if not lines:
                continue
            number += 1
            oid = f"O-{number:06d}"
            online_orders.append(
                {
                    "order_id": oid,
                    "customer_ref": f"cust-{r.getrandbits(32):08x}",
                    "store_id": sid,
                    "ordered_at": iso(at(ordered_days_ago)),
                    "status": r.choice(("collected", "delivered")),
                    "channel_pref": r.choice(("email", "sms", "app")),
                }
            )
            order_lines.extend({"order_id": oid, **line} for line in lines)

    truth_recalls = []
    for s in truth["recall_scenarios"]:
        on_hand = s.get("stores_on_hand") or {}
        truth_recalls.append(
            {
                "scenario": s["id"],
                "feed": s["feed"],
                "notice_format": s["format"],
                "product_id": s.get("product_id"),
                "options": list(s.get("options") or []),
                "codes": [s["batch"]["code"]]
                if s.get("batch")
                else list(s.get("codes") or []),
                "expected_match_status": s["expected_match_status"],
                "stores_on_hand": sorted(
                    sid for sid, units in on_hand.items() if units > 0
                ),
                "units_on_hand": sum(on_hand.values()),
                "online_orders": sorted(planted_orders.get(s["id"], [])),
            }
        )
    truth_labels = []
    for s in truth["label_fixtures"]:
        on_hand = s.get("stores_on_hand") or {}
        truth_labels.append(
            {
                "fixture": s["id"],
                "product_id": s["product_id"],
                "lot": s["batch"]["code"] if s.get("batch") else s.get("lot"),
                "reporting_store": s.get("reporting_store"),
                "expected_rules": list(s.get("expected_rules") or []),
                "expected_severity": s.get("expected_severity"),
                "hold_stores": sorted(
                    sid for sid, units in on_hand.items() if units > 0
                ),
                "units_on_hand": sum(on_hand.values()),
            }
        )

    return Supply(
        stores=stores,
        batches=batches,
        deliveries=deliveries,
        store_stock=store_stock,
        online_orders=online_orders,
        order_lines=order_lines,
        truth_recalls=truth_recalls,
        truth_labels=truth_labels,
        planted_batch_ids=frozenset(planted_ids),
    )
