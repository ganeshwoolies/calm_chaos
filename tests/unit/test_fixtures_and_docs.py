import re

from app.evidence import from_fixture
from app.knowledge import load_bundle
from data.write_fixtures import render_all
from tests.knowledge_copy import REPO_BUNDLE

DDL_DIR = REPO_BUNDLE.parent / "sql" / "ddl"


def test_evidence_fixtures_are_written_from_the_generated_world() -> None:
    stale = [
        p.name
        for p, text in render_all().items()
        if not p.is_file() or p.read_text(encoding="utf-8") != text
    ]
    assert stale == [], "run: uv run python data/write_fixtures.py"


def test_fixture_figures_are_the_truth() -> None:
    yoghurt = from_fixture("recall:yoghurt_listeria")
    on_hand = [r for r in yoghurt.lineage.store_rows if r.on_hand]
    assert (
        len(on_hand),
        sum(r.on_hand or 0 for r in on_hand),
        len(yoghurt.lineage.order_ids),
    ) == (14, 212, 37)
    dinosaur = from_fixture("label:P50211:7a0d3f")
    assert sum(r.on_hand or 0 for r in dinosaur.lineage.store_rows) == 59


def test_every_table_has_a_concept_whose_schema_matches_its_ddl() -> None:
    bundle = load_bundle(REPO_BUNDLE)
    for ddl in sorted(DDL_DIR.glob("*.sql")):
        concept = bundle.get(f"/tables/{ddl.stem}.md")
        assert concept is not None, f"/tables/{ddl.stem}.md is missing"
        assert concept.meta["resource"] == f"psd.{ddl.stem}"
        columns = re.findall(
            r"^\s+(\w+)\s+([A-Z][A-Z0-9<>]*)",
            ddl.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        documented = re.findall(
            r"^\| (\w+) \| ([A-Z][A-Z0-9<>]*) \|", concept.body, re.MULTILINE
        )
        assert documented == columns, ddl.stem
