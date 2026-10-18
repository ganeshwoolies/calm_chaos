import json

import pytest

from api import scope
from api.scope import CatalogueMatch, Decision, decide
from app.knowledge import MatchRule
from app.schemas import Lineage, LineageRow

RULE = MatchRule(
    barcode_first=True,
    top_k=5,
    max_distance=0.25,
    ambiguity_gap=0.05,
    require_model_confirmation=True,
)


def _near(product_id: str, distance: float, same: bool | None = True) -> CatalogueMatch:
    return CatalogueMatch(product_id, 1, "embedding", distance, same)


def test_a_barcode_we_sell_matches_without_the_model() -> None:
    matches = [
        CatalogueMatch("P50211", 1, "barcode", None, True),
        _near("P11722", 0.23),
    ]
    assert decide(matches, RULE) == Decision("matched", "P50211", "barcode")


def test_one_confirmed_neighbour_is_a_match() -> None:
    matches = [_near("P48812", 0.03), _near("P10351", 0.078, same=False)]
    assert decide(matches, RULE) == Decision("matched", "P48812", "embedding", 0.03)


def test_two_confirmed_neighbours_inside_the_gap_are_ambiguous() -> None:
    matches = [
        _near("P31007", 0.074),
        _near("P31008", 0.10),
        _near("P10248", 0.13, False),
    ]
    assert decide(matches, RULE) == Decision("ambiguous", options=("P31007", "P31008"))


def test_a_second_confirmed_neighbour_outside_the_gap_leaves_the_nearest() -> None:
    assert decide([_near("P1", 0.03), _near("P2", 0.09)], RULE).product_id == "P1"


@pytest.mark.parametrize(
    "matches",
    [
        [],
        [_near("P48812", 0.066, same=False), _near("P10640", 0.10, same=False)],
        [_near("P48812", 0.03, same=None)],
        [_near("P48812", 0.30)],
    ],
    ids=["nothing near", "all rejected", "confirmation failed", "too far"],
)
def test_without_a_confirmed_neighbour_the_notice_is_not_in_range(matches) -> None:
    assert decide(matches, RULE) == Decision("not_in_range")


def test_without_required_confirmation_the_nearest_within_distance_matches() -> None:
    rule = RULE.model_copy(update={"require_model_confirmation": False})
    assert decide([_near("P1", 0.2, same=None)], rule).product_id == "P1"


def test_with_barcode_first_off_a_barcode_is_not_a_match_on_its_own() -> None:
    matches = [
        CatalogueMatch("P50211", 1, "barcode", None, True),
        _near("P50211", 0.04),
    ]
    rule = RULE.model_copy(update={"barcode_first": False})
    assert decide(matches, rule) == Decision("matched", "P50211", "embedding", 0.04)


def test_matching_passes_the_rule_to_the_sql(monkeypatch) -> None:
    sent = {}

    def rows(sql, parameters=()):
        sent.update({p.name: p.value for p in parameters if hasattr(p, "value")})
        return []

    monkeypatch.setattr(scope.bq, "client", lambda: _Client())
    monkeypatch.setattr(scope.bq, "job_config", lambda *a, **k: None)
    monkeypatch.setattr(scope.bq, "rows", rows)
    scope.match_notices(
        {"evt_1": {"brand": "Morrowdale"}},
        RULE.model_copy(update={"barcode_first": False}),
    )
    assert (sent["barcode_first"], sent["top_k"], sent["max_distance"]) == (
        False,
        5,
        0.25,
    )


class _Client:
    def query(self, *args, **kwargs):
        return self

    def result(self):
        return None


def test_the_candidate_id_is_stable_per_notice_and_product() -> None:
    cid = scope.candidate_id("7222 at https://www.foodstandards.gov.au", "P48812")
    assert cid == scope.candidate_id(
        "7222 at https://www.foodstandards.gov.au", "P48812"
    )
    prefix, digest, product = cid.split(":")
    assert (prefix, len(digest), product) == ("recall", 8, "P48812")
    assert cid != scope.candidate_id(
        "7223 at https://www.foodstandards.gov.au", "P48812"
    )


def test_a_best_before_that_is_not_an_iso_date_is_reported() -> None:
    extract = {
        "date_codes": [
            {"kind": "best_before", "from": "30/10/2026", "to": None},
            {"kind": "use_by", "from": "soon"},
        ]
    }
    assert scope._bad_dates(extract) == ["30/10/2026"]
    assert (
        scope._bad_dates(
            {"date_codes": [{"kind": "best_before", "from": "2026-10-30"}]}
        )
        == []
    )


def _landed(
    guid: str, extract: dict | None, tag_error: str | None = None, feed: str = "test"
) -> dict:
    return {
        "guid": guid,
        "event_id": f"evt_{guid}",
        "feed": feed,
        "recall_extract": json.dumps(extract) if extract is not None else "{}",
        "tag_error": tag_error,
    }


def _lineage(on_hand: int, orders: int = 0) -> Lineage:
    rows = [
        LineageRow(
            row_kind="store",
            batch_id="BAT-1",
            code="B1",
            store_id="S004",
            delivered=10,
            on_hand=on_hand,
            last_delivered="2026-08-01T00:00:00+00:00",
        )
    ]
    rows += [
        LineageRow(
            row_kind="order",
            batch_id="BAT-1",
            code="B1",
            store_id="S004",
            order_id=f"O-{i}",
        )
        for i in range(orders)
    ]
    return Lineage(receipt_id="rcpt-1", as_of="2026-10-17T00:00:00+00:00", rows=rows)


@pytest.fixture
def run(monkeypatch):
    """scope._run over stubbed BigQuery, matching and lineage; returns what it would write and publish."""

    def go(landed, matches, lineage=None):
        written = {"matched": []}

        def match_notices(extracts, rule):
            written["matched"].extend(extracts)
            return matches

        monkeypatch.setattr(scope.bq, "rows", lambda sql, parameters=(): landed)
        monkeypatch.setattr(scope, "match_notices", match_notices)
        monkeypatch.setattr(scope, "_lineage", lambda guid, extract, pid, pol: lineage)
        monkeypatch.setattr(
            scope,
            "_write",
            lambda o, m, c: written.update(outcomes=o, matches=m, candidates=c),
        )
        monkeypatch.setattr(scope, "_publish_candidates", lambda: [])
        result = scope._run()
        return result, written

    return go


EXTRACT = {
    "brand": "Morrowdale",
    "product_name": "Vanilla Yoghurt",
    "batch_codes": ["B1"],
}


def test_each_notice_reaches_its_status_and_only_an_exposed_match_raises(run) -> None:
    landed = [
        _landed("failed", None, tag_error="SyntaxError"),
        _landed("decoy", EXTRACT),
        _landed("muesli", EXTRACT),
        _landed("yoghurt", EXTRACT),
    ]
    matches = {
        "evt_decoy": [_near("P48812", 0.066, same=False)],
        "evt_muesli": [_near("P31007", 0.074), _near("P31008", 0.10)],
        "evt_yoghurt": [_near("P48812", 0.03)],
    }
    result, written = run(landed, matches, lineage=_lineage(on_hand=18, orders=2))
    status = {o["guid"]: o["match_status"] for o in written["outcomes"]}
    assert status == {
        "failed": "extraction_failed",
        "decoy": "not_in_range",
        "muesli": "ambiguous",
        "yoghurt": "matched",
    }
    by_guid = {o["guid"]: o for o in written["outcomes"]}
    assert by_guid["muesli"]["match_options"] == ["P31007", "P31008"]
    yoghurt = by_guid["yoghurt"]
    (candidate,) = written["candidates"]
    assert (
        yoghurt["candidate_id"]
        == candidate["candidate_id"]
        == scope.candidate_id("yoghurt", "P48812")
    )
    assert (yoghurt["receipt_id"], yoghurt["matched_by"]) == ("rcpt-1", "scope")
    assert candidate["stores"] == ["S004"] and candidate["online_orders"] == 2
    assert candidate["receipt_ids"] == ["rcpt-1"] and candidate["event_ids"] == [
        "evt_yoghurt"
    ]
    assert {m["event_id"] for m in written["matches"]} == {
        "evt_decoy",
        "evt_muesli",
        "evt_yoghurt",
    }
    assert result["outcomes"]["matched"] == 1


def test_a_match_whose_batches_reached_no_store_or_order_has_no_exposure(run) -> None:
    landed = [_landed("kettle", EXTRACT)]
    _, written = run(
        landed, {"evt_kettle": [_near("P62240", 0.03)]}, lineage=_lineage(on_hand=0)
    )
    (outcome,) = written["outcomes"]
    assert outcome["match_status"] == "matched_no_exposure"
    assert outcome["receipt_id"] == "rcpt-1" and outcome["candidate_id"] is None
    assert written["candidates"] == []


def test_a_notice_whose_embedding_failed_stays_pending(run) -> None:
    landed = [_landed("retry", EXTRACT)]
    failed = [CatalogueMatch(None, None, "embedding_failed", None, None)]
    _, written = run(landed, {"evt_retry": failed})
    assert written["outcomes"] == [] and written["matches"] == []


def test_a_date_lineage_cannot_read_is_an_extraction_failure(run) -> None:
    extract = {
        **EXTRACT,
        "batch_codes": [],
        "date_codes": [{"kind": "best_before", "from": "30/10/2026"}],
    }
    _, written = run([_landed("dates", extract)], {})
    assert [o["match_status"] for o in written["outcomes"]] == ["extraction_failed"]


def test_a_live_notice_is_never_matched_whatever_the_model_would_say(run) -> None:
    landed = [
        _landed("live", EXTRACT, feed="fsanz"),
        _landed("unknown", EXTRACT, feed="gone"),
    ]
    matches = {
        "evt_live": [_near("P48812", 0.01)],
        "evt_unknown": [_near("P48812", 0.01)],
    }
    _, written = run(landed, matches)
    assert [o["match_status"] for o in written["outcomes"]] == ["not_in_range"] * 2
    assert written["matched"] == [] and written["candidates"] == []
