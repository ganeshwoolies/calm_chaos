import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pytest

from api import feeds
from data import gen_notices
from data.gen_catalogue import load_truth

ANCHOR = datetime(2026, 10, 17, 3, 15, tzinfo=UTC)
TRUTH = load_truth()
SCENARIOS = [s["id"] for s in TRUTH["recall_scenarios"]]
FICTIONAL_BRANDS = {p["brand"] for p in TRUTH["products"]}


@pytest.fixture(scope="module")
def notices() -> list[gen_notices.Notice]:
    return gen_notices.render_all(SCENARIOS, ANCHOR, truth=TRUTH)


def test_every_scenario_has_a_notice_in_its_regulators_layout(notices) -> None:
    by_id = {s["id"]: s for s in TRUTH["recall_scenarios"]}
    assert [n.scenario for n in notices] == SCENARIOS
    for n in notices:
        assert n.notice_format == by_id[n.scenario]["format"]
        assert (
            n.guid == f"FICTIONAL-TEST:{n.notice_format}:{n.scenario}:20261017T031500Z"
        )
        assert n.title.startswith("FICTIONAL TEST: ")
        fsanz = 'class="field field-date-marking"' in n.description
        assert fsanz == (n.notice_format == "fsanz"), n.scenario


def test_every_notice_is_marked_fictional_and_names_only_fictional_brands(
    notices,
) -> None:
    for n in notices:
        assert gen_notices.BANNER in n.description and "TEST-" in n.description
        assert n.expected["brand"] in FICTIONAL_BRANDS
        assert "<img" not in n.description and "logo" not in n.description.lower()
        assert n.link.startswith(f"{gen_notices.NOTICE_HOST}/test/notices/")


def test_a_notice_prints_exactly_the_codes_its_scenario_names(notices) -> None:
    by_id = {s["id"]: s for s in TRUTH["recall_scenarios"]}
    for n in notices:
        s = by_id[n.scenario]
        codes = [s["batch"]["code"]] if s.get("batch") else list(s.get("codes") or [])
        assert n.expected["batch_codes"] == codes, n.scenario
        (item,) = feeds.parse("test", gen_notices.feed_xml([n]))
        assert all(c in item.text for c in codes)


def test_the_yoghurt_notice_carries_its_best_before_and_the_dinosaur_its_barcode(
    notices,
) -> None:
    yoghurt, dinosaur = notices[0], notices[1]
    assert yoghurt.expected["date_codes"] == [
        {"kind": "best_before", "from": "2026-10-30", "to": "2026-10-30"}
    ]
    assert "Best before 30/10/2026" in yoghurt.description
    assert dinosaur.expected["barcodes"] == ["2000000502113"]
    assert (
        notices[-1].expected["sizes"] == [] and notices[-1].expected["date_codes"] == []
    )


def test_copies_have_their_own_guid(notices) -> None:
    copies = gen_notices.render_all(["yoghurt_listeria"], ANCHOR, count=3, truth=TRUTH)
    assert len({c.guid for c in copies}) == 3


def test_publishing_puts_new_notices_first_and_keeps_the_feed_bounded(notices) -> None:
    first = gen_notices.feed_xml(notices[:2])
    second = gen_notices.feed_xml(notices[2:], existing=first)
    guids = [g.text for g in ET.fromstring(second).iter("guid")]
    assert guids == [n.guid for n in notices[2:] + notices[:2]]
    many = gen_notices.render_all(
        ["kettle_no_exposure"], ANCHOR, count=150, truth=TRUTH
    )
    assert (
        len(list(ET.fromstring(gen_notices.feed_xml(many)).iter("item")))
        == gen_notices.FEED_ITEMS
    )
