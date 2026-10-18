"""Builds the fictional CalmChaosRetail catalogue from data/truth.yaml and the vocabularies, with no model call.

The same seed always gives the same rows. Planted products keep their fixed ids and facts. No generated product shares a
planted product's brand, type and variant, so matching sees exactly the neighbours the truth expects.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from data.catalogue_vocab import (
    BRANDS,
    FOOD_ORIGINS,
    GOODS_ORIGINS,
    LINES,
    PRODUCT_TYPES,
    ProductType,
)

DATA_DIR = Path(__file__).resolve().parent
TRUTH = DATA_DIR / "truth.yaml"
CATEGORY_ORDER = ("food", "household", "electrical", "toys", "cosmetics")
FIRST_PRODUCT_NUMBER = 10001


def load_truth(path: Path = TRUTH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def rng(seed: Any, *parts: Any) -> random.Random:
    """A generator per entity, so changing one part of the world does not reshuffle the rest."""
    return random.Random(":".join(str(p) for p in (seed, *parts)))


def ean13(product_id: str) -> str:
    # 200 is a GS1 restricted-circulation prefix: no traded product carries it, so a generated barcode is never a real
    # product's number.
    body = "200" + f"{int(product_id[1:]):09d}"
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
    return body + str((10 - total % 10) % 10)


def anchor_from(truth: dict[str, Any], key: str = "fixture_anchor") -> datetime:
    value = truth[key]
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def iso(ts: datetime) -> str:
    return ts.replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Catalogue:
    products: list[dict[str, Any]]
    suppliers: list[dict[str, Any]]
    specs: list[dict[str, Any]]
    types: dict[str, str]  # product_id -> product type key


def _name(ptype: ProductType, line: str, variant: str) -> str:
    return f"{line} {ptype.name.format(variant=variant)}".strip()


def _facts(
    ptype: ProductType, variant: str
) -> tuple[list[str], list[str], list[str], str]:
    allergens = list(
        dict.fromkeys(ptype.allergens + ptype.variant_allergens.get(variant, ()))
    )
    warnings = list(
        dict.fromkeys(ptype.warnings + ptype.variant_warnings.get(variant, ()))
    )
    return (
        allergens,
        warnings,
        list(ptype.marks),
        ptype.ingredients.format(variant=variant.lower()),
    )


def _suppliers(truth: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    planted = {p["brand"]: p["supplier_id"] for p in truth["products"]}
    taken = set(planted.values())
    free = (f"SUP-{n:03d}" for n in range(1, 1000) if f"SUP-{n:03d}" not in taken)
    by_brand = {b: planted.get(b) or next(free) for b in BRANDS}
    rows = [
        {
            "supplier_id": sid,
            "name": truth["suppliers"].get(sid, brand),
            "contact_ref": f"contact-{sid.lower()}",
            "category": BRANDS[brand][0],
        }
        for brand, sid in by_brand.items()
    ]
    return sorted(rows, key=lambda r: r["supplier_id"]), by_brand


def build_catalogue(truth: dict[str, Any], anchor: datetime) -> Catalogue:
    seed = truth["seed"]
    suppliers, supplier_of = _suppliers(truth)
    planted = truth["products"]
    planted_ids = {p["product_id"] for p in planted}
    excluded = {(p["brand"], p["type"], p["variant"]) for p in planted}

    products: list[dict[str, Any]] = []
    specs: list[dict[str, Any]] = []
    types: dict[str, str] = {}

    def add(
        pid: str,
        brand: str,
        ptype: ProductType,
        line: str,
        line_factor: float,
        variant: str,
        size: str,
        r: random.Random,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        o = overrides or {}
        allergens, warnings, marks, ingredients = _facts(ptype, variant)
        allergens = list(o.get("allergens", allergens))
        warnings = list(o.get("warnings", warnings))
        marks = list(o.get("marks", marks))
        ingredients = o.get("ingredients_text", ingredients)
        origin = o.get("origin") or r.choice(
            FOOD_ORIGINS if ptype.category == "food" else GOODS_ORIGINS
        )
        name = _name(ptype, line, variant)
        low, high = ptype.price
        price = round(r.uniform(low, high) * line_factor * 20) / 20
        versions = int(o.get("spec_versions", 1))
        first_change = r.randint(120, 400)
        for v in range(1, versions + 1):
            latest = v == versions
            specs.append(
                {
                    "product_id": pid,
                    "version": f"v{v}",
                    # Older versions lack the last allergen or warning the latest added, which is how a listing goes stale.
                    "allergens": allergens
                    if latest or not allergens
                    else allergens[:-1],
                    "warnings": warnings if latest or not warnings else warnings[:-1],
                    "marks": marks,
                    "ingredients_text": ingredients,
                    "origin": origin,
                    "changed_at": iso(
                        anchor
                        - timedelta(days=first_change if v == 1 else max(5, 90 // v))
                    ),
                    "supplier_id": supplier_of[brand],
                }
            )
        products.append(
            {
                "product_id": pid,
                "name": name,
                "brand": brand,
                "size": size,
                "category": ptype.category,
                "subcategory": ptype.subcategory,
                "barcode": ean13(pid),
                "supplier_id": supplier_of[brand],
                "unit_price": f"{price:.2f}",
                "listing_text": f"{brand} {name} {size}. {ptype.description}".strip(),
                "listing_allergens": list(o.get("listing_allergens", allergens)),
                "listing_warnings": list(o.get("listing_warnings", warnings)),
                "listing_marks": list(o.get("listing_marks", marks)),
                "listing_origin": origin,
            }
        )
        types[pid] = ptype.key

    for p in planted:
        ptype = PRODUCT_TYPES[p["type"]]
        add(
            p["product_id"],
            p["brand"],
            ptype,
            "",
            1.0,
            p["variant"],
            p["size"],
            rng(seed, "planted", p["product_id"]),
            p,
        )

    numbers = (
        n for n in range(FIRST_PRODUCT_NUMBER, 100000) if f"P{n}" not in planted_ids
    )
    for category in CATEGORY_ORDER:
        combos = [
            (brand, key, line, factor, variant, size)
            for brand, (brand_category, keys) in BRANDS.items()
            if brand_category == category
            for key in keys
            for line, factor in LINES[category]
            for variant in PRODUCT_TYPES[key].variants
            if (brand, key, variant) not in excluded
            for size in PRODUCT_TYPES[key].sizes
        ]
        wanted = truth["catalogue"][category] - sum(
            1 for p in planted if PRODUCT_TYPES[p["type"]].category == category
        )
        if wanted > len(combos):
            raise ValueError(
                f"{category}: {wanted} products wanted, only {len(combos)} combinations in the vocabularies"
            )
        rng(seed, "catalogue", category).shuffle(combos)
        for brand, key, line, factor, variant, size in combos[:wanted]:
            pid = f"P{next(numbers)}"
            add(
                pid,
                brand,
                PRODUCT_TYPES[key],
                line,
                factor,
                variant,
                size,
                rng(seed, "product", pid),
            )

    return Catalogue(products=products, suppliers=suppliers, specs=specs, types=types)
