"""The label-reading eval: Gemini reads generated label photos, and code compares them with the listing and spec.

Each photo is one billed Gemini call, so the eval runs only when asked:
- PSD_LABEL_EVAL=fixtures reads the four label fixtures, flat: four calls.
- PSD_LABEL_EVAL=all reads every pack flat, angled and under glare: 36 calls.

Flat and angled photos must give every allergen, warning and mark, the lot and the planted findings exactly. Under
glare a retake is also right.
"""

import io
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv

from api import labels
from app import policy
from app.knowledge import load_bundle
from data import gen_labels
from data.gen_catalogue import build_catalogue, load_truth, rng
from tests.knowledge_copy import copy_bundle

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
SCOPE = os.environ.get("PSD_LABEL_EVAL", "")
pytestmark = pytest.mark.skipif(
    SCOPE not in ("fixtures", "all") or not os.environ.get("GOOGLE_CLOUD_PROJECT"),
    reason="calls Gemini once per photo: set PSD_LABEL_EVAL=fixtures (4 calls) or all (36 calls)",
)
ANCHOR = datetime(2026, 10, 17, tzinfo=UTC)


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory):
    bundle = copy_bundle(tmp_path_factory.mktemp("bundle") / "knowledge")
    os.environ["PSD_KNOWLEDGE_DIR"] = str(bundle)
    pol = policy.current()
    names = list(load_bundle(bundle).get(labels.ALLERGENS).meta["names"])
    truth = load_truth()
    catalogue = build_catalogue(truth, ANCHOR)
    warnings = sorted({w for s in catalogue.specs for w in s["warnings"]})
    marks = sorted({m for s in catalogue.specs for m in s["marks"]})
    vocab = labels.Vocabulary(names, warnings, marks)
    from tests.unit.test_labels import _facts

    fixtures = {f["id"] for f in truth["label_fixtures"]}
    jobs = []
    for name, pack in gen_labels.packs(truth, ANCHOR).items():
        if SCOPE == "fixtures" and name not in fixtures:
            continue
        r = rng(truth["seed"], "label-take", name)
        flat = gen_labels.render(pack)
        takes = [("flat", flat)]
        if SCOPE == "all":
            takes += [
                ("angled", gen_labels.angled(flat, r)),
                ("glare", gen_labels.glare(flat, r)),
            ]
        for take, img in takes:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=88)
            jobs.append((name, take, pack, buf.getvalue()))

    def run(job):
        name, take, pack, image = job
        read = labels.read_label(image, "image/jpeg", vocab)
        found = labels.diff_label(read, _facts(catalogue, pack.product_id), pol, names)
        return name, take, pack, read, sorted(f.rule for f in found)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, jobs))
    os.environ.pop("PSD_KNOWLEDGE_DIR", None)
    return pol, names, results


def _correct(pack, read, rules, names) -> list[str]:
    problems = []
    if set(labels.canonical_allergens(read.allergens, names)) != set(pack.allergens):
        problems.append(f"allergens {read.allergens}")
    if {w.casefold() for w in read.warnings} != {w.casefold() for w in pack.warnings}:
        problems.append(f"warnings {read.warnings}")
    if {m.casefold() for m in read.marks} != {m.casefold() for m in pack.marks}:
        problems.append(f"marks {read.marks}")
    if (read.lot or "").strip() != pack.lot:
        problems.append(f"lot {read.lot}")
    if rules != sorted(pack.expected_rules):
        problems.append(f"rules {rules}")
    return problems


def test_flat_and_angled_photos_read_correctly(outcomes) -> None:
    pol, names, results = outcomes
    wrong = {
        f"{name}/{take}": problems
        for name, take, pack, read, rules in results
        if take != "glare"
        and (
            problems := (
                ["retake asked"] if read.legibility < pol.labels.min_legibility else []
            )
            or _correct(pack, read, rules, names)
        )
    }
    assert wrong == {}


def test_under_glare_the_read_is_correct_or_a_retake_is_asked(outcomes) -> None:
    pol, names, results = outcomes
    wrong = {
        name: problems
        for name, take, pack, read, rules in results
        if take == "glare"
        and read.legibility >= pol.labels.min_legibility
        and (problems := _correct(pack, read, rules, names))
    }
    assert wrong == {}
