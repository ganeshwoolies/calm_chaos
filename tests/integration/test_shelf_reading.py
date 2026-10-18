"""The shelf-reading eval: Gemini reads generated shelf photos, and code decides each verdict by the shelf check policy.

Each photo is one billed Gemini call, so the eval runs only when asked:
- PSD_SHELF_EVAL=yoghurt reads the yoghurt shelf's four takes: four calls.
- PSD_SHELF_EVAL=all reads both shelves' four takes: eight calls.

present and note (units under a sign saying the shelf is clear) must be not_clear, clear must be verified_clear with
the product's shelf ticket and its brand's other lines still in view, and blurred must never be verified_clear. Each
photo's verdict and reading are written to artifacts/eval/shelf_reading.json.
"""

import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv

from api import labels, shelves
from app import policy
from data import gen_shelves
from data.gen_catalogue import load_truth
from tests.knowledge_copy import copy_bundle

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
SCOPE = os.environ.get("PSD_SHELF_EVAL", "")
pytestmark = pytest.mark.skipif(
    SCOPE not in ("yoghurt", "all") or not os.environ.get("GOOGLE_CLOUD_PROJECT"),
    reason="calls Gemini once per photo: set PSD_SHELF_EVAL=yoghurt (4 calls) or all (8 calls)",
)
ANCHOR = datetime(2026, 10, 17, tzinfo=UTC)
# What each photo was read as, so a run's readings can be looked at without paying for another.
REPORT = (
    Path(__file__).resolve().parents[2] / "artifacts" / "eval" / "shelf_reading.json"
)


def _facts(product: gen_shelves.Product) -> labels.Facts:
    return labels.Facts(
        product_id=product.product_id,
        brand=product.brand,
        name=product.name,
        size=product.size,
        listing_allergens=[],
        listing_warnings=[],
        listing_marks=[],
        listing_origin=None,
        spec_version="",
        spec_allergens=[],
        spec_warnings=[],
        spec_marks=[],
        spec_ingredients=None,
    )


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory):
    bundle = copy_bundle(tmp_path_factory.mktemp("bundle") / "knowledge")
    os.environ["PSD_KNOWLEDGE_DIR"] = str(bundle)
    rule = policy.shelf_rule()
    jobs = []
    for s in gen_shelves.shelves(load_truth(), ANCHOR):
        if SCOPE == "yoghurt" and s["scenario"] != "yoghurt_listeria":
            continue
        for take, expected in gen_shelves.EXPECTED.items():
            buffer = io.BytesIO()
            gen_shelves.shelf(s["target"], s["neighbours"], s["code"], take).save(
                buffer, format="JPEG", quality=88
            )
            jobs.append(
                (f"{s['scenario']}_{take}", take, expected, buffer.getvalue(), s)
            )

    def read(job):
        name, take, expected, image, s = job
        reading = shelves.read_shelf(image, "image/jpeg", _facts(s["target"]))
        return name, take, expected, reading, shelves.verdict_for(reading, rule)

    with ThreadPoolExecutor(max_workers=4) as pool:
        out = list(pool.map(read, jobs))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            [
                {
                    "photo": name,
                    "expected": expected,
                    "verdict": verdict,
                    "reading": reading.model_dump(mode="json"),
                }
                for name, _, expected, reading, verdict in out
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return out


def test_every_shelf_photo_gets_the_safe_verdict(outcomes) -> None:
    wrong = []
    for name, take, expected, reading, verdict in outcomes:
        right = (
            verdict != "verified_clear" if take == "blurred" else verdict == expected
        )
        if not right:
            wrong.append(f"{name}: {verdict}, expected {expected}; read {reading!r}")
    assert not wrong, "\n".join(wrong)


def test_the_recalled_units_code_is_read_when_they_are_in_view(outcomes) -> None:
    for name, take, _, reading, _ in outcomes:
        if take == "present":
            assert any(
                code in " ".join(reading.codes_seen)
                for code in ("B2026-091", "L2026-0310")
            ), f"{name}: {reading.codes_seen}"
