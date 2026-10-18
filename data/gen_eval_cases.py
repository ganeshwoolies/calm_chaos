"""The drafting eval's 16 cases: 8 recall cases, one per hazard type, and 8 label cases, one per label rule.

    uv run python data/gen_eval_cases.py [--check]

Five cases already exist as fixtures or planted scenarios: yoghurt_listeria (microbial), dinosaur_choking (choking),
dinosaur_battery_warning, muesli_almond and kettle_rcm. The other eleven are regular products of the generated world,
picked the same way every time: the first product by id, in the right category, with a batch or lot on hand at three
to twenty stores at the fixture anchor. Each case gets a stand-in (data/fixtures/notices or label_checks) and a
candidate file; data/write_fixtures.py then writes its evidence pack, and this script writes the dataset
(tests/eval/datasets/basic-dataset.json) with a reference per case. A reference is built from the evidence pack and
the proposal policy computes for it, so it states the facts a correct draft must agree with, and nothing a model wrote.
--check writes nothing and exits 1 when any file would change.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app import actions
from app.knowledge import REPO_DIR, load_bundle
from app.policy import Policy, build
from app.schemas import EvidencePack
from data.gen_catalogue import Catalogue, anchor_from, build_catalogue, load_truth
from data.gen_supply import Supply, build_supply
from data.write_fixtures import lineage_rows

FIXTURES = REPO_DIR / "data" / "fixtures"
DATASET = REPO_DIR / "tests" / "eval" / "datasets" / "basic-dataset.json"

# One regular product per hazard type the planted scenarios do not cover: category, what the notice says, and what
# the customer is told to do.
RECALL_CASES = {
    "allergen": ("food", "Undeclared peanut", "peanut not declared on the label"),
    "foreign_matter": (
        "food",
        "Pieces of hard blue plastic",
        "small pieces of hard blue plastic in the product",
    ),
    "spoilage": (
        "food",
        "Faulty seal",
        "a faulty seal that may let the product spoil before its best-before date",
    ),
    "chemical": (
        "household",
        "Corrosive ingredient above the labelled level",
        "more of a corrosive ingredient than the label states",
    ),
    "electrical_fire": (
        "electrical",
        "Internal wiring fault",
        "an internal wiring fault that can overheat and start a fire",
    ),
    "injury": (
        "toys",
        "Sharp edge when broken",
        "a part that can snap and leave a sharp edge",
    ),
}
FOOD_ACTION = (
    "Do not eat. Return the product to the place of purchase for a full refund."
)
GOODS_ACTION = (
    "Stop using the product and return it to the place of purchase for a full refund."
)

# One regular product per label rule the planted fixtures do not cover: category, field, and how to pick the value
# from the product's latest supplier spec.
LABEL_CASES = {
    "allergen_undeclared_on_pack": ("food", "allergens"),
    "allergen_extra_in_listing": ("food", "allergens"),
    "warning_missing_in_listing": ("toys", "warnings"),
    "ingredients_differ": ("food", "ingredients"),
    "origin_differs": ("food", "origin"),
}
ALLERGEN_CANDIDATES = ["sesame", "peanut", "soy", "egg", "fish", "lupin"]


def _latest_specs(catalogue: Catalogue) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for spec in catalogue.specs:
        if (
            spec["product_id"] not in latest
            or spec["version"] > latest[spec["product_id"]]["version"]
        ):
            latest[spec["product_id"]] = spec
    return latest


def _exposed(
    supply: Supply, product_id: str, code: str, anchor: datetime, lookback: int
) -> list[dict[str, Any]]:
    rows = lineage_rows(supply, product_id, [code], None, None, anchor, lookback)
    return [r for r in rows if r["row_kind"] == "store" and (r["on_hand"] or 0) > 0]


def _pick(
    catalogue: Catalogue,
    supply: Supply,
    category: str,
    anchor: datetime,
    lookback: int,
    taken: set[str],
    planted: set[str],
    accept=lambda product: True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The first product by id in the category, not taken or planted, with a batch on hand at 3 to 20 stores."""
    batches: dict[str, list[dict[str, Any]]] = {}
    for b in supply.batches:
        batches.setdefault(b["product_id"], []).append(b)
    for product in sorted(catalogue.products, key=lambda p: p["product_id"]):
        pid = product["product_id"]
        if (
            product["category"] != category
            or pid in taken
            or pid in planted
            or not accept(product)
        ):
            continue
        for batch in sorted(
            batches.get(pid, []), key=lambda b: b["produced_on"], reverse=True
        ):
            if 3 <= len(_exposed(supply, pid, batch["code"], anchor, lookback)) <= 20:
                taken.add(pid)
                return product, batch
    raise SystemExit(f"no {category} product with a batch on hand at 3 to 20 stores")


def _finding_value(rule: str, spec: dict[str, Any]) -> str:
    """What the label check found, consistent with the product's latest spec."""
    if rule == "allergen_undeclared_on_pack":
        return spec["allergens"][0]
    if rule == "allergen_extra_in_listing":
        return next(a for a in ALLERGEN_CANDIDATES if a not in spec["allergens"])
    if rule == "warning_missing_in_listing":
        return spec["warnings"][0]
    if rule == "ingredients_differ":
        return "new ingredient: palm oil"
    return "New Zealand" if spec.get("origin") != "New Zealand" else "Australia"


def _label_id(product_id: str, rule: str, value: str) -> str:
    return (
        f"label:{product_id}:"
        + hashlib.sha1(f"{product_id}|{rule}|{value}".encode()).hexdigest()[:6]
    )


def _dump(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def stand_ins(pol: Policy) -> dict[Path, str]:
    """The stand-in and candidate files of the eleven new regular-product cases and the two planted ones."""
    truth = load_truth()
    anchor = anchor_from(truth)
    catalogue = build_catalogue(truth, anchor)
    supply = build_supply(truth, catalogue, anchor)
    lookback = pol.recall.order_lookback_days
    specs = _latest_specs(catalogue)
    planted = {p["product_id"] for p in truth["products"]}
    taken: set[str] = set()
    out: dict[Path, str] = {}
    published = (anchor - timedelta(days=1)).isoformat()

    def recall(
        name: str,
        product: dict,
        batch: dict,
        hazard: str,
        detail: str,
        summary: str,
        food: bool,
    ) -> None:
        stand = {
            "candidate_id": f"recall:{name}",
            "kind": "recall",
            "product_id": product["product_id"],
            "hazard_type": hazard,
            "title_hint": f"{product['brand']} {product['name']} {product['size']} batch {batch['code']} {detail} recall",
            "prior_incidents": [],
            "notice": {
                "guid": f"FICTIONAL-TEST:eval:{name}",
                "feed": "test",
                "title": f"FICTIONAL TEST: {product['brand']} {product['name']} {product['size']}",
                "url": f"https://example.test/notices/{name.replace('_', '-')}",
                "published_at": published,
                "extract": {
                    "product_name": product["name"],
                    "brand": product["brand"],
                    "sizes": [product["size"]],
                    "batch_codes": [batch["code"]],
                    "date_codes": (
                        [
                            {
                                "kind": "best_before",
                                "from": batch["best_before"],
                                "to": batch["best_before"],
                            }
                        ]
                        if batch.get("best_before")
                        else []
                    ),
                    "hazard_type": hazard,
                    "hazard_detail": detail,
                    "consumer_action": FOOD_ACTION if food else GOODS_ACTION,
                    "summary": f"Possible {summary} in one batch of {product['brand']} {product['name']} {product['size']}.",
                },
            },
            "match": {"method": "embedding", "distance": 0.1, "confirmed": True},
            "fixture_receipt_id": f"rcpt-fixture-{name.replace('_', '-')}",
        }
        out[FIXTURES / "notices" / f"{name}.json"] = _dump(stand)
        out[FIXTURES / "candidates" / f"{name}.json"] = _dump(
            {"candidate_id": stand["candidate_id"], "kind": "recall"}
        )

    for hazard, (category, detail, summary) in RECALL_CASES.items():
        accept = (
            (lambda p: "peanut" not in specs[p["product_id"]]["allergens"])
            if hazard == "allergen"
            else (lambda p: True)
        )
        product, batch = _pick(
            catalogue, supply, category, anchor, lookback, taken, planted, accept
        )
        recall(
            f"eval_{hazard}",
            product,
            batch,
            hazard,
            detail,
            summary,
            category == "food",
        )

    scenario = next(
        s for s in truth["recall_scenarios"] if s["id"] == "dinosaur_choking"
    )
    dinosaur = next(
        p for p in catalogue.products if p["product_id"] == scenario["product_id"]
    )
    dino_batch = next(
        b
        for b in supply.batches
        if b["product_id"] == dinosaur["product_id"]
        and b["code"] == scenario["batch"]["code"]
    )
    recall(
        "dinosaur_choking",
        dinosaur,
        dino_batch,
        "choking",
        "Detachable horn",
        "a detachable horn that is a choking hazard for young children",
        False,
    )

    def label(
        name: str,
        product: dict,
        rule: str,
        field: str,
        value: str,
        store_id: str,
        lot: str | None,
    ) -> None:
        finding = pol.finding_for(rule, field, value)
        candidate_id = _label_id(product["product_id"], rule, value)
        stand = {
            "candidate_id": candidate_id,
            "kind": "label",
            "product_id": product["product_id"],
            "hazard_type": finding.hazard_type,
            "title_hint": f"{product['brand']} {product['name']} {product['size']} {rule.replace('_', ' ')}: {value}",
            "prior_incidents": [],
            "checks": [
                {
                    "check_id": f"lc-{name.replace('_', '-')}",
                    "store_id": store_id,
                    "checked_at": (anchor - timedelta(hours=6)).isoformat(),
                    "photo_uri": f"gs://psd-fixtures/labels/{name}.jpg",
                    "lot": lot,
                    "findings": [finding.model_dump(mode="json")],
                }
            ],
            "fixture_receipt_id": f"rcpt-fixture-{name.replace('_', '-')}",
        }
        out[FIXTURES / "label_checks" / f"{name}.json"] = _dump(stand)
        out[FIXTURES / "candidates" / f"{name}.json"] = _dump(
            {"candidate_id": candidate_id, "kind": "label"}
        )

    for rule, (category, field) in LABEL_CASES.items():
        hold = "hold" in pol.label_rule(rule).actions

        def accept(p, rule=rule):
            spec = specs[p["product_id"]]
            if rule == "allergen_undeclared_on_pack":
                return bool(spec["allergens"])
            if rule == "allergen_extra_in_listing":
                return any(a not in spec["allergens"] for a in ALLERGEN_CANDIDATES)
            if rule == "warning_missing_in_listing":
                return bool(spec["warnings"])
            return True

        product, batch = _pick(
            catalogue, supply, category, anchor, lookback, taken, planted, accept
        )
        value = _finding_value(rule, specs[product["product_id"]])
        exposed = _exposed(
            supply, product["product_id"], batch["code"], anchor, lookback
        )
        label(
            f"eval_{rule}",
            product,
            rule,
            field,
            value,
            exposed[0]["store_id"],
            batch["code"] if hold else None,
        )

    fixture = next(f for f in truth["label_fixtures"] if f["id"] == "kettle_rcm")
    kettle = next(
        p for p in catalogue.products if p["product_id"] == fixture["product_id"]
    )
    label(
        "kettle_rcm",
        kettle,
        "mark_missing_on_pack",
        "marks",
        "RCM",
        fixture["reporting_store"],
        fixture["batch"]["code"],
    )
    return out


# The dataset.


def _pack(candidate_id: str) -> EvidencePack:
    for path in sorted((FIXTURES / "evidence").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["candidate_id"] == candidate_id:
            return EvidencePack.model_validate(data)
    raise SystemExit(
        f"no evidence pack for {candidate_id}: run uv run python data/write_fixtures.py"
    )


def reference(ev: EvidencePack, pol: Policy) -> str:
    """The facts a correct incident card states, from the evidence and the policy's proposal."""
    proposed = actions.propose(ev, pol)
    product = f"{ev.product.brand} {ev.product.name} {ev.product.size}"
    lines = []
    if ev.kind == "recall" and ev.notice:
        extract = ev.notice.extract
        codes = ", ".join(extract.batch_codes) or "every batch"
        lines.append(
            f"{product}, batch {codes}: {extract.hazard_detail} ({ev.hazard_type}, severity {proposed.severity})."
        )
    else:
        for check in ev.checks:
            for f in check.findings:
                lines.append(
                    f"{product}: label check at store {check.store_id}"
                    + (f", lot {check.lot}" if check.lot else "")
                    + f", finding {f.rule.replace('_', ' ')} ({f.value}), severity {f.severity}."
                )
    if proposed.store_actions:
        verb = proposed.store_actions[0].action
        units = sum(a.qty_on_hand for a in proposed.store_actions)
        lines.append(
            f"Proposed: {verb} at {len(proposed.store_actions)} stores holding {units} units."
        )
    if proposed.message_orders:
        lines.append(
            f"Message {len(proposed.message_orders)} online orders; the customer message names the product and batch, "
            "says what to do and offers a full refund."
        )
    if proposed.checkout_block:
        lines.append("A checkout block is requested.")
    for fix in proposed.listing_fixes:
        change = (
            f"set {fix.field} to {fix.set_to}"
            if fix.set_to
            else "; ".join(
                part
                for part in (
                    f"add {', '.join(fix.add)} to {fix.field}" if fix.add else "",
                    f"remove {', '.join(fix.remove)} from {fix.field}"
                    if fix.remove
                    else "",
                )
                if part
            )
        )
        lines.append(f"Listing fix: {change}.")
    if proposed.supplier_notice:
        lines.append("A supplier notice is sent.")
    if proposed.vendor_case:
        lines.append("A vendor case is opened.")
    if not proposed.message_orders:
        lines.append("There is no customer message.")
    return " ".join(lines)


CASE_ORDER = [
    ("recall_yoghurt_listeria", "recall:yoghurt_listeria", "recall"),
    *[(f"recall_{h}", f"recall:eval_{h}", "recall") for h in RECALL_CASES],
    ("recall_dinosaur_choking", "recall:dinosaur_choking", "recall"),
    ("label_dinosaur_battery_warning", "label:P50211:7a0d3f", "label"),
    ("label_muesli_almond_listing_fix", "label:P31007:4c19e2", "label"),
]


def dataset(pol: Policy) -> str:
    cases = list(CASE_ORDER)
    for path in sorted((FIXTURES / "label_checks").glob("*.json")):
        stand = json.loads(path.read_text(encoding="utf-8"))
        if path.stem.startswith("eval_") or path.stem == "kettle_rcm":
            cases.append(
                (
                    f"label_{path.stem.removeprefix('eval_')}",
                    stand["candidate_id"],
                    "label",
                )
            )
    eval_cases = []
    for case_id, candidate_id, kind in cases:
        prompt = json.dumps({"candidate_id": candidate_id, "kind": kind})
        eval_cases.append(
            {
                "eval_case_id": case_id,
                "prompt": {"role": "user", "parts": [{"text": prompt}]},
                "reference": {
                    "response": {
                        "role": "model",
                        "parts": [{"text": reference(_pack(candidate_id), pol)}],
                    }
                },
            }
        )
    return _dump({"eval_cases": eval_cases})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    pol = build(load_bundle(REPO_DIR / "knowledge"), require_usable=False)
    files = stand_ins(pol)
    drift = []
    for path, text in files.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            drift.append(path)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    if not args.check:
        from data import write_fixtures

        for path, text in write_fixtures.render_all().items():
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
    data = dataset(pol)
    if not DATASET.exists() or DATASET.read_text(encoding="utf-8") != data:
        drift.append(DATASET)
        if not args.check:
            DATASET.write_text(data, encoding="utf-8")
    for path in drift:
        print(
            ("out of date: " if args.check else "wrote ")
            + str(path.relative_to(REPO_DIR))
        )
    return 1 if args.check and drift else 0


if __name__ == "__main__":
    sys.exit(main())
