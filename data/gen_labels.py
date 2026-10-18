"""Renders pack labels as photos for the label check: the label fixtures in data/truth.yaml and eight clean packs.

    uv run python data/gen_labels.py [--out artifacts/labels]

Each label prints the product's latest supplier spec, less what the fixture's `pack` leaves off, in three takes: flat,
angled, and under glare. Every label says it is a fictional test label. manifest.json lists each image with the product,
lot and label rules the check should find.
"""

import argparse
import json
import random
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from data.catalogue_vocab import PRODUCT_TYPES
from data.gen_catalogue import build_catalogue, load_truth, rng

OUT = Path(__file__).resolve().parent.parent / "artifacts" / "labels"
WIDTH, MARGIN = 1100, 64
CLEAN_PACKS = {"food": 3, "household": 2, "electrical": 1, "toys": 1, "cosmetics": 1}
GLUTEN_CEREALS = ("wheat", "barley", "oats", "rye")
FONTS = {
    False: (
        "arial.ttf",
        "DejaVuSans.ttf",
        "LiberationSans-Regular.ttf",
        "Helvetica.ttc",
    ),
    True: (
        "arialbd.ttf",
        "DejaVuSans-Bold.ttf",
        "LiberationSans-Bold.ttf",
        "Helvetica.ttc",
    ),
}
FONT_DIRS = (
    Path("C:/Windows/Fonts"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/System/Library/Fonts"),
)


@dataclass
class Pack:
    """What one label prints."""

    product_id: str
    brand: str
    name: str
    size: str
    category: str
    barcode: str
    lot: str
    best_before: str | None
    allergens: list[str]
    warnings: list[str]
    marks: list[str]
    ingredients: str
    origin: str
    supplier: str
    expected_rules: list[str] = field(default_factory=list)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for directory in FONT_DIRS:
        for name in FONTS[bold]:
            path = directory / name
            if path.is_file():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


# EAN-13: the first digit picks the parity of the left six; L and G codes on the left, R codes on the right.
_L = (
    "0001101",
    "0011001",
    "0010011",
    "0111101",
    "0100011",
    "0110001",
    "0101111",
    "0111011",
    "0110111",
    "0001011",
)
_G = tuple("".join("1" if b == "0" else "0" for b in code)[::-1] for code in _L)
_R = tuple("".join("1" if b == "0" else "0" for b in code) for code in _L)
_PARITY = (
    "LLLLLL",
    "LLGLGG",
    "LLGGLG",
    "LLGGGL",
    "LGLLGG",
    "LGGLLG",
    "LGGGLL",
    "LGLGLG",
    "LGLGGL",
    "LGGLGL",
)


def ean13_bits(digits: str) -> str:
    left = "".join(
        (_L if p == "L" else _G)[int(d)]
        for p, d in zip(_PARITY[int(digits[0])], digits[1:7], strict=True)
    )
    right = "".join(_R[int(d)] for d in digits[7:])
    return "101" + left + "01010" + right + "101"


def draw_barcode(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    digits: str,
    module: int = 4,
    height: int = 150,
) -> int:
    bits = ean13_bits(digits)
    for i, bit in enumerate(bits):
        if bit == "1":
            draw.rectangle(
                (x + i * module, y, x + (i + 1) * module - 1, y + height), fill="black"
            )
    text = font(34)
    draw.text((x - 30, y + height + 6), digits[0], font=text, fill="black")
    draw.text(
        (x + 3 * module + 8, y + height + 6), digits[1:7], font=text, fill="black"
    )
    draw.text(
        (x + 50 * module + 8, y + height + 6), digits[7:], font=text, fill="black"
    )
    return y + height + 50


def _runs(text: str, bold_words: list[str]) -> list[tuple[str, bool]]:
    """The text as (word, bold) pairs, with every allergen word in bold as the Food Standards Code requires."""
    pattern = re.compile(
        r"^(" + "|".join(re.escape(w) for w in bold_words) + r")s?\b", re.IGNORECASE
    )
    return [
        (word, bool(bold_words) and bool(pattern.match(word))) for word in text.split()
    ]


def draw_runs(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    runs: list[tuple[str, bool]],
    size: int,
    width: int,
) -> int:
    regular, bold = font(size), font(size, bold=True)
    space = draw.textlength(" ", font=regular)
    cx, line = x, int(size * 1.35)
    for word, is_bold in runs:
        f = bold if is_bold else regular
        w = draw.textlength(word, font=f)
        if cx + w > x + width and cx > x:
            cx, y = x, y + line
        draw.text((cx, y), word, font=f, fill="black")
        cx += w + space
    return y + line


def _warning_text(warning: str) -> str:
    worded = {
        "button battery": "Contains a button battery. Swallowing can cause severe injury. Keep new and used batteries "
        "away from children.",
        "not suitable for children under 3 years": "Not suitable for children under 3 years. Small parts. Choking "
        "hazard.",
    }
    text = worded.get(warning, warning)
    return "WARNING: " + text[0].upper() + text[1:].rstrip(".") + "."


def render(pack: Pack) -> Image.Image:
    img = Image.new("RGB", (WIDTH, 1700), (252, 250, 244))
    draw = ImageDraw.Draw(img)
    inner = WIDTH - 2 * MARGIN
    y = MARGIN
    draw.rectangle(
        (MARGIN // 2, MARGIN // 2, WIDTH - MARGIN // 2, 1700 - MARGIN // 2),
        outline=(40, 40, 40),
        width=4,
    )
    draw.text((MARGIN, y), pack.brand, font=font(72, bold=True), fill=(20, 40, 90))
    y += 92
    draw.text((MARGIN, y), f"{pack.name}  {pack.size}", font=font(48), fill="black")
    y += 84
    is_food = pack.category == "food"
    y = draw_runs(
        draw,
        MARGIN,
        y,
        [
            ("Ingredients:" if is_food else "Materials:", True),
            *_runs(pack.ingredients, pack.allergens),
        ],
        34,
        inner,
    )
    if pack.allergens:
        declared = list(pack.allergens)
        if any(a in GLUTEN_CEREALS for a in declared):
            declared.insert(
                next(i for i, a in enumerate(declared) if a in GLUTEN_CEREALS) + 1,
                "gluten",
            )
        y = draw_runs(
            draw,
            MARGIN,
            y + 14,
            [("Contains:", True)] + [(w, True) for w in ", ".join(declared).split()],
            36,
            inner,
        )
    y += 24
    for warning in pack.warnings:
        top = y
        y = draw_runs(
            draw,
            MARGIN + 20,
            y + 14,
            [(w, i == 0) for i, w in enumerate(_warning_text(warning).split())],
            34,
            inner - 40,
        )
        draw.rectangle(
            (MARGIN, top, WIDTH - MARGIN, y + 6), outline=(170, 20, 20), width=3
        )
        y += 26
    if pack.marks:
        y += 6
        for mark in pack.marks:
            draw.ellipse((MARGIN, y, MARGIN + 90, y + 90), outline="black", width=5)
            draw.line(
                (MARGIN + 22, y + 48, MARGIN + 40, y + 66, MARGIN + 70, y + 26),
                fill="black",
                width=7,
            )
            draw.text(
                (MARGIN + 110, y + 18), mark, font=font(48, bold=True), fill="black"
            )
            y += 110
    y += 20
    marking = f"{'BATCH' if is_food else 'LOT'} {pack.lot}"
    if pack.best_before:
        marking += f"     BEST BEFORE {pack.best_before}"
    draw.text((MARGIN, y), marking, font=font(40, bold=True), fill="black")
    y += 70
    draw.text((MARGIN, y), pack.origin, font=font(36), fill="black")
    y += 54
    draw.text(
        (MARGIN, y), f"Distributed by {pack.supplier}", font=font(30), fill=(60, 60, 60)
    )
    y += 70
    y = draw_barcode(draw, MARGIN + 40, y, pack.barcode)
    draw.text(
        (MARGIN, y + 20),
        "FICTIONAL TEST LABEL · CalmChaosRetail · not a real product",
        font=font(28),
        fill=(120, 120, 120),
    )
    return img.crop((0, 0, WIDTH, min(1700, y + 100)))


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [[*row, b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c], strict=True)]
    return [m[i][n] / m[i][i] for i in range(n)]


def _perspective(
    src: list[tuple[float, float]], dst: list[tuple[float, float]]
) -> list[float]:
    """Coefficients mapping output points dst back to input points src, as Image.transform expects."""
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    return _solve(a, b)


def angled(img: Image.Image, r: random.Random) -> Image.Image:
    w, h = img.size
    canvas = (w + 300, h + 260)
    dx, dy = r.uniform(60, 110), r.uniform(40, 80)
    dst = [
        (150 + dx, 130),
        (150 + w - dx * 0.4, 130 + dy),
        (150 + w, 130 + h - dy * 0.3),
        (150, 130 + h),
    ]
    coeffs = _perspective([(0, 0), (w, 0), (w, h), (0, h)], dst)
    mask = Image.new("L", img.size, 255).transform(
        canvas, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC
    )
    warped = img.transform(
        canvas, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC
    )
    table = Image.new("RGB", canvas, (118, 104, 92))
    table.paste(warped, (0, 0), mask)
    return table.rotate(
        r.uniform(-4, 4), resample=Image.Resampling.BICUBIC, fillcolor=(118, 104, 92)
    ).filter(ImageFilter.GaussianBlur(0.8))


def glare(img: Image.Image, r: random.Random) -> Image.Image:
    w, h = img.size
    cx, cy = r.uniform(0.35, 0.65) * w, r.uniform(0.3, 0.55) * h
    spot = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(spot)
    for i in range(40, 0, -1):
        rx, ry = w * 0.42 * i / 40, h * 0.22 * i / 40
        d.ellipse(
            (cx - rx, cy - ry, cx + rx, cy + ry), fill=int(250 * (1 - i / 40) ** 0.6)
        )
    white = Image.new("RGB", img.size, (255, 255, 250))
    return Image.composite(white, img, spot.filter(ImageFilter.GaussianBlur(18)))


def packs(truth: dict[str, Any], anchor: datetime) -> dict[str, Pack]:
    """The label fixtures and the clean packs, by name, each with the label rules a check should find."""
    catalogue = build_catalogue(truth, anchor)
    products = {p["product_id"]: p for p in catalogue.products}
    latest = {s["product_id"]: s for s in catalogue.specs}
    suppliers = {s["supplier_id"]: s["name"] for s in catalogue.suppliers}

    def pack(
        pid: str, lot: str, omit: dict[str, list[str]], expected: list[str]
    ) -> Pack:
        p, s = products[pid], latest[pid]
        ptype = PRODUCT_TYPES[catalogue.types[pid]]
        best_before = (
            (anchor + timedelta(days=min(ptype.shelf_life_days, 60))).strftime(
                "%d/%m/%Y"
            )
            if ptype.shelf_life_days
            else None
        )
        return Pack(
            product_id=pid,
            brand=p["brand"],
            name=p["name"],
            size=p["size"],
            category=p["category"],
            barcode=p["barcode"],
            lot=lot,
            best_before=best_before,
            allergens=[
                a for a in s["allergens"] if a not in omit.get("omit_allergens", [])
            ],
            warnings=[
                w for w in s["warnings"] if w not in omit.get("omit_warnings", [])
            ],
            marks=[m for m in s["marks"] if m not in omit.get("omit_marks", [])],
            ingredients=s["ingredients_text"],
            origin=s["origin"],
            supplier=suppliers[s["supplier_id"]],
            expected_rules=expected,
        )

    out = {}
    for f in truth["label_fixtures"]:
        lot = f["batch"]["code"] if f.get("batch") else f["lot"]
        out[f["id"]] = pack(
            f["product_id"], lot, f.get("pack") or {}, list(f["expected_rules"])
        )
    planted = {p["product_id"] for p in truth["products"]}
    r = rng(truth["seed"], "labels")
    for category, count in CLEAN_PACKS.items():
        choices = sorted(
            pid
            for pid, p in products.items()
            if p["category"] == category
            and pid not in planted
            and (
                latest[pid]["allergens"]
                or latest[pid]["warnings"]
                or latest[pid]["marks"]
            )
        )
        for pid in r.sample(choices, count):
            out[f"clean_{pid}"] = pack(
                pid,
                f"{'B' if category == 'food' else 'L'}2026-{r.randint(100, 899)}",
                {},
                [],
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
    for name, p in packs(truth, anchor).items():
        r = rng(truth["seed"], "label-take", name)
        flat = render(p)
        for take, img in (
            ("flat", flat),
            ("angled", angled(flat, r)),
            ("glare", glare(flat, r)),
        ):
            file = f"{name}_{take}.jpg"
            img.convert("RGB").save(args.out / file, quality=88)
            manifest.append(
                {
                    "file": file,
                    "pack": name,
                    "take": take,
                    "product_id": p.product_id,
                    "lot": p.lot,
                    "allergens": p.allergens,
                    "warnings": p.warnings,
                    "marks": p.marks,
                    "expected_rules": p.expected_rules,
                }
            )
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"{len(manifest)} label images in {args.out}")


if __name__ == "__main__":
    main()
