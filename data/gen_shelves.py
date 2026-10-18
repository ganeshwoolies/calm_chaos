"""Renders shelf photos for the shelf check: the shelf of each recalled product that gets store tasks, in four takes.

    uv run python data/gen_shelves.py [--out artifacts/shelves]

Each photo shows the product's place on a shelf among products of the same kind, the same brand's other lines first.
present has units of the product on the shelf; clear has none, with its shelf ticket still in place; blurred is the
clear shelf out of focus, which must not verify clear; note is the present shelf under a sign saying it was checked
clear. Every photo says it is a fictional test image. manifest.json lists each image with the product and the verdict
the shelf check should give.
"""

import argparse
import colorsys
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from data.gen_catalogue import build_catalogue, load_truth, rng
from data.gen_labels import font

OUT = Path(__file__).resolve().parent.parent / "artifacts" / "shelves"
WIDTH, HEIGHT = 1280, 960
SHELF_TOPS = (70, 370, 670)
SHELF_HEIGHT = 260
FACING = 128
# Five places a shelf, three shelves, one of them the product's.
NEIGHBOURS = 14
EXPECTED = {
    "present": "not_clear",
    "clear": "verified_clear",
    "blurred": "retake",
    "note": "not_clear",
}


@dataclass(frozen=True)
class Product:
    product_id: str
    brand: str
    name: str
    size: str
    price: str


def _colour(brand: str) -> tuple[int, int, int]:
    hue = int(hashlib.sha1(brand.encode()).hexdigest()[:4], 16) / 0xFFFF
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.82)
    return int(r * 255), int(g * 255), int(b * 255)


def _wrap(draw: ImageDraw.ImageDraw, text: str, size: int, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=font(size)) <= width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


def _pack(
    draw: ImageDraw.ImageDraw, x: int, bottom: int, p: Product, code: str | None
) -> None:
    """One unit standing on the shelf: brand band, name, size and, for the recalled product, its code."""
    height = 210
    top = bottom - height
    colour = _colour(p.brand)
    draw.rounded_rectangle(
        (x, top, x + FACING - 10, bottom), 12, fill=colour, outline=(60, 60, 60)
    )
    draw.rectangle((x + 4, top + 8, x + FACING - 14, top + 46), fill=(255, 255, 255))
    size = 17
    while (
        size > 10 and draw.textlength(p.brand, font=font(size, bold=True)) > FACING - 30
    ):
        size -= 1
    draw.text(
        (x + 10, top + 16), p.brand, fill=(20, 20, 20), font=font(size, bold=True)
    )
    y = top + 58
    for line in _wrap(draw, p.name, 18, FACING - 26)[:4]:
        draw.text((x + 10, y), line, fill=(255, 255, 255), font=font(18, bold=True))
        y += 22
    draw.text(
        (x + 10, bottom - 58), p.size, fill=(255, 255, 255), font=font(24, bold=True)
    )
    if code:
        draw.text((x + 10, bottom - 26), code, fill=(250, 250, 250), font=font(13))


def _ticket(
    draw: ImageDraw.ImageDraw, x: int, edge: int, width: int, p: Product
) -> None:
    draw.rectangle((x, edge + 4, x + width - 12, edge + 44), fill=(255, 255, 240))
    label = f"{p.brand} {p.name} {p.size}"
    draw.text((x + 6, edge + 8), label[:38], fill=(30, 30, 30), font=font(12))
    draw.text((x + 6, edge + 24), p.price, fill=(170, 20, 20), font=font(16, bold=True))


def _sign(img: Image.Image, x: int, y: int) -> Image.Image:
    sign = Image.new("RGBA", (330, 150), (255, 255, 255, 255))
    d = ImageDraw.Draw(sign)
    d.rectangle((0, 0, 329, 149), outline=(40, 40, 40), width=3)
    d.text((18, 14), "SHELF CHECKED", fill=(20, 20, 20), font=font(30, bold=True))
    d.text((18, 56), "ALL CLEAR", fill=(10, 120, 40), font=font(38, bold=True))
    d.text(
        (18, 108),
        "no recalled stock here - store team",
        fill=(60, 60, 60),
        font=font(15),
    )
    sign = sign.rotate(-4, expand=True, fillcolor=(0, 0, 0, 0))
    img.paste(sign, (x, y), sign)
    return img


def shelf(
    target: Product, neighbours: list[Product], code: str, take: str
) -> Image.Image:
    """The shelf photo for one take; the target's place is the middle of the middle shelf."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (214, 210, 202))
    draw = ImageDraw.Draw(img)
    per_shelf = WIDTH // (FACING * 2)
    queue = list(neighbours)
    for row, top in enumerate(SHELF_TOPS):
        edge = top + SHELF_HEIGHT
        draw.rectangle((0, top, WIDTH, edge), fill=(196, 191, 182))
        slots: list[Product | None] = [
            queue.pop(0) if queue else None for _ in range(per_shelf)
        ]
        if row == 1:
            slots[per_shelf // 2] = target
        for i, p in enumerate(slots):
            if p is None:
                continue
            x = 20 + i * FACING * 2
            if p is not target or take in ("present", "note"):
                for f in range(2):
                    _pack(
                        draw, x + f * FACING, edge - 4, p, code if p is target else None
                    )
        draw.rectangle((0, edge, WIDTH, edge + 50), fill=(70, 70, 76))
        for i, p in enumerate(slots):
            if p is not None:
                _ticket(draw, 20 + i * FACING * 2, edge, FACING * 2, p)
    draw.rectangle((0, HEIGHT - 34, WIDTH, HEIGHT), fill=(30, 30, 30))
    draw.text(
        (16, HEIGHT - 28),
        "FICTIONAL TEST IMAGE · CalmChaosRetail · not a real shelf or a real product",
        fill=(240, 240, 240),
        font=font(16),
    )
    if take == "note":
        # Above the units, so they stay in full view under a sign that says otherwise.
        img = _sign(img, 20 + (per_shelf // 2) * FACING * 2 - 60, SHELF_TOPS[1] - 175)
    if take == "blurred":
        img = img.filter(ImageFilter.GaussianBlur(9))
    return img


def shelves(truth: dict[str, Any], anchor: datetime) -> list[dict[str, Any]]:
    """Each recalled product that gets store tasks, with its neighbours and the code printed on its units."""
    catalogue = build_catalogue(truth, anchor)
    products = {p["product_id"]: p for p in catalogue.products}
    r = rng(truth["seed"], "shelves")
    out = []
    for scenario in truth["recall_scenarios"]:
        pid = scenario.get("product_id")
        if not pid or not scenario.get("stores_on_hand"):
            continue
        p = products[pid]
        kind = catalogue.types[pid]
        same_brand = sorted(
            q
            for q, v in products.items()
            if q != pid and v["brand"] == p["brand"] and catalogue.types[q] == kind
        )
        same_kind = sorted(
            q
            for q, v in products.items()
            if q != pid and v["brand"] != p["brand"] and catalogue.types[q] == kind
        )
        picked = r.sample(same_brand, min(4, len(same_brand)))
        picked += r.sample(same_kind, min(NEIGHBOURS - len(picked), len(same_kind)))
        same_category = sorted(
            q
            for q, v in products.items()
            if q != pid
            and q not in picked
            and v["category"] == p["category"]
            and catalogue.types[q] != kind
        )
        picked += r.sample(same_category, NEIGHBOURS - len(picked))

        def product(q: str) -> Product:
            v = products[q]
            return Product(
                q,
                v["brand"],
                v["name"],
                v["size"],
                f"${r.randint(2, 39)}.{r.choice(['00', '50', '99'])}",
            )

        out.append(
            {
                "scenario": scenario["id"],
                "target": product(pid),
                "neighbours": [product(q) for q in picked],
                "code": scenario["batch"]["code"],
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    truth = load_truth()
    anchor = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for s in shelves(truth, anchor):
        target = s["target"]
        for take, verdict in EXPECTED.items():
            file = f"{s['scenario']}_{take}.jpg"
            shelf(target, s["neighbours"], s["code"], take).save(
                args.out / file, quality=88
            )
            manifest.append(
                {
                    "file": file,
                    "scenario": s["scenario"],
                    "take": take,
                    "product_id": target.product_id,
                    "product": f"{target.brand} {target.name} {target.size}",
                    "code": s["code"],
                    "expected_verdict": verdict,
                }
            )
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"{len(manifest)} shelf images in {args.out}")


if __name__ == "__main__":
    main()
