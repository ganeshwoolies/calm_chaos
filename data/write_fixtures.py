"""Writes the offline evidence fixtures (data/fixtures/evidence) from the same generated world BigQuery holds.

    uv run python data/write_fixtures.py [--check]

Each fixture is a stand-in (notice or label checks) plus the generated product and the lineage the sanctioned SQL
returns at the fixture anchor, computed here over the generated rows. --check writes nothing and exits 1 on drift.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app import evidence
from app.knowledge import REPO_DIR, load_bundle
from app.policy import build
from app.schemas import Lineage, LineageRow, Product
from data.gen_catalogue import Catalogue, anchor_from, build_catalogue, iso, load_truth
from data.gen_supply import Supply, build_supply


def lineage_rows(
    supply: Supply,
    product_id: str,
    codes: list[str],
    best_before_from: str | None,
    best_before_to: str | None,
    as_of: datetime,
    order_lookback_days: int,
) -> list[dict[str, Any]]:
    """What recall_lineage.sql returns for these parameters, over the generated rows."""
    hits = {
        b["batch_id"]: b
        for b in supply.batches
        if b["product_id"] == product_id
        and (
            b["code"] in codes
            or (not codes and best_before_from is None)
            or (
                not codes
                and b["best_before"] is not None
                and best_before_from
                <= b["best_before"]
                <= (best_before_to or best_before_from)
            )
        )
    }
    stock = {
        (s["store_id"], s["batch_id"]): s
        for s in supply.store_stock
        if s["batch_id"] in hits
    }
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for d in supply.deliveries:
        if d["batch_id"] in hits and datetime.fromisoformat(d["delivered_at"]) <= as_of:
            g = grouped.setdefault(
                (d["batch_id"], d["store_id"]),
                {"delivered": 0, "last": d["delivered_at"]},
            )
            g["delivered"] += d["qty"]
            g["last"] = max(g["last"], d["delivered_at"], key=datetime.fromisoformat)
    store_rows = [
        {
            "row_kind": "store",
            "batch_id": batch_id,
            "code": hits[batch_id]["code"],
            "store_id": store_id,
            "delivered": g["delivered"],
            "last_delivered": g["last"],
            "on_hand": (stock.get((store_id, batch_id)) or {}).get("on_hand", 0),
            "aisle": (stock.get((store_id, batch_id)) or {}).get("aisle"),
            "order_id": None,
        }
        for (batch_id, store_id), g in grouped.items()
    ]
    since = as_of - timedelta(days=order_lookback_days)
    orders = {
        o["order_id"]: o
        for o in supply.online_orders
        if since <= datetime.fromisoformat(o["ordered_at"]) <= as_of
    }
    order_rows = [
        {
            "row_kind": "order",
            "batch_id": line["batch_id"],
            "code": hits[line["batch_id"]]["code"],
            "store_id": orders[line["order_id"]]["store_id"],
            "delivered": None,
            "last_delivered": None,
            "on_hand": None,
            "aisle": None,
            "order_id": line["order_id"],
        }
        for line in supply.order_lines
        if line["batch_id"] in hits and line["order_id"] in orders
    ]
    store_rows.sort(key=lambda r: (-int(r["on_hand"] or 0), str(r["store_id"])))
    order_rows.sort(key=lambda r: (r["store_id"], r["order_id"]))
    return store_rows + order_rows


def _product(catalogue: Catalogue, product_id: str) -> Product:
    row = next(p for p in catalogue.products if p["product_id"] == product_id)
    supplier = next(
        s for s in catalogue.suppliers if s["supplier_id"] == row["supplier_id"]
    )
    return Product.model_validate({**row, "supplier_name": supplier["name"]})


def render_all() -> dict[Path, str]:
    truth = load_truth()
    anchor = anchor_from(truth)
    catalogue = build_catalogue(truth, anchor)
    supply = build_supply(truth, catalogue, anchor)
    pol = build(load_bundle(REPO_DIR / "knowledge"), require_usable=False)
    out: dict[Path, str] = {}
    for folder in evidence.STAND_IN_FOLDERS:
        for path in sorted((evidence.fixtures_dir() / folder).glob("*.json")):
            stand = json.loads(path.read_text(encoding="utf-8"))
            lineage = None
            if params := evidence.lineage_params(stand, pol):
                rows = lineage_rows(
                    supply,
                    **params,
                    as_of=anchor,
                    order_lookback_days=pol.recall.order_lookback_days,
                )
                lineage = Lineage(
                    receipt_id=stand["fixture_receipt_id"],
                    as_of=iso(anchor),
                    rows=[LineageRow.model_validate(r) for r in rows],
                )
            pack = evidence.pack(
                stand, _product(catalogue, stand["product_id"]), lineage
            )
            text = (
                json.dumps(pack.model_dump(mode="json", exclude_none=True), indent=2)
                + "\n"
            )
            out[evidence.fixtures_dir() / "evidence" / path.name] = text
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if a fixture is out of date"
    )
    args = parser.parse_args()
    drift = []
    for path, text in render_all().items():
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            continue
        if args.check:
            drift.append(path.name)
            continue
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(REPO_DIR).as_posix()}")
    for name in drift:
        print(
            f"out of date: data/fixtures/evidence/{name} (run uv run python data/write_fixtures.py)"
        )
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
