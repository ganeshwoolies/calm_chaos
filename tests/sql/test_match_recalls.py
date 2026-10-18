"""The matching layer of the evaluation on the loaded world: each fictional notice's extract reaches its expected status.

Calls AI.EMBED and AI.IF through BigQuery, and embeds any new or changed catalogue rows into psd.product_embeddings.
The extracts are the ones the notices print, so extraction quality does not enter this test.
"""

from datetime import UTC, datetime

import pytest

from api import scope
from app import actions, bq, policy
from app.knowledge import load_bundle
from data import gen_notices
from data.gen_catalogue import load_truth
from tests.sql.conftest import require_table


@pytest.fixture(autouse=True)
def _loaded(monkeypatch):
    monkeypatch.setenv("PSD_DATASET", "psd")
    require_table("psd", "product_embeddings")


@pytest.fixture(scope="module")
def outcomes(
    verified_bundle,
) -> dict[str, tuple[scope.Decision, list[scope.CatalogueMatch]]]:
    """Each scenario's decision and the catalogue products considered, from one matching run."""
    scenarios = [s["id"] for s in load_truth()["recall_scenarios"]]
    notices = gen_notices.render_all(scenarios, datetime.now(UTC))
    # Module scope runs before the per-test knowledge fixture, so the verified bundle is read directly.
    rule = policy.build(load_bundle(verified_bundle)).match
    found = scope.match_notices({n.scenario: n.expected for n in notices}, rule)
    return {
        s: (scope.decide(found.get(s, []), rule), found.get(s, [])) for s in scenarios
    }


def test_matching_reaches_the_truth_for_every_scenario(outcomes) -> None:
    truth = {
        s["scenario"]: s
        for s in bq.rows("SELECT * FROM truth_recalls ORDER BY scenario")
    }
    for scenario, (d, considered) in outcomes.items():
        t = truth[scenario]
        assert not any(m.method == "embedding_failed" for m in considered), scenario
        if t["expected_match_status"] == "ambiguous":
            assert d.status == "ambiguous", (scenario, d, considered)
            assert sorted(d.options) == t["options"], scenario
        elif t["expected_match_status"] == "not_in_range":
            assert d.status == "not_in_range", (scenario, d, considered)
        else:
            assert (d.status, d.product_id) == ("matched", t["product_id"]), (
                scenario,
                d,
                considered,
            )


def test_a_printed_barcode_matches_without_embedding(outcomes) -> None:
    d, considered = outcomes["dinosaur_choking"]
    assert d.method == "barcode"
    assert [m.method for m in considered] == ["barcode"]


def test_with_barcode_first_off_a_barcode_notice_is_embedded_too(
    verified_bundle,
) -> None:
    (notice,) = gen_notices.render_all(["dinosaur_choking"], datetime.now(UTC))
    rule = policy.build(load_bundle(verified_bundle)).match.model_copy(
        update={"barcode_first": False}
    )
    considered = scope.match_notices({notice.scenario: notice.expected}, rule)[
        notice.scenario
    ]
    assert {m.method for m in considered} == {"barcode", "embedding"}, considered
    d = scope.decide(considered, rule)
    assert (d.status, d.product_id, d.method) == ("matched", "P50211", "embedding"), (
        d,
        considered,
    )


def test_the_decoy_size_is_rejected_by_confirmation_not_by_distance(outcomes) -> None:
    _, considered = outcomes["yoghurt_500g_decoy"]
    same_line = [m for m in considered if m.product_id == "P48812"]
    assert same_line and same_line[0].distance is not None
    assert same_line[0].distance <= policy.current().match.max_distance
    assert same_line[0].same_product is False


def test_the_kettle_matches_but_its_lot_never_reached_a_store(outcomes) -> None:
    d, _ = outcomes["kettle_no_exposure"]
    pol = policy.current()
    lineage = scope._lineage(
        "test:accc:kettle_no_exposure",
        {"batch_codes": ["L2026-0999"]},
        d.product_id,
        pol,
    )
    assert actions.exposed_stores(lineage, pol) == [] and lineage.order_ids == []
