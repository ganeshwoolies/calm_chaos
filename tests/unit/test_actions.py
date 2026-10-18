from app.actions import propose


def test_recall_proposal(yoghurt, pol) -> None:
    p = propose(yoghurt, pol)
    assert p.severity == "critical"
    assert len(p.store_actions) == 14
    assert all(a.action == "pull" for a in p.store_actions)
    assert sum(a.qty_on_hand for a in p.store_actions) == 212
    assert len(p.message_orders) == 37
    assert p.checkout_block is True
    assert (p.targets.message_minutes, p.targets.shelf_minutes) == (30, 60)
    assert p.supplier_notice and p.vendor_case
    assert p.receipts == ["rcpt-fixture-yoghurt-0001"]


def test_recall_excludes_store_outside_exposure(yoghurt, pol) -> None:
    # S080 holds none and was last delivered more than 30 days before the lineage was computed.
    assert "S080" not in {a.store_id for a in propose(yoghurt, pol).store_actions}


def test_recall_without_batch_codes_adds_consideration(yoghurt, pol) -> None:
    yoghurt.notice.extract.batch_codes = []
    yoghurt.notice.extract.date_codes = []
    assert any("names no batch" in c for c in propose(yoghurt, pol).considerations)


def test_several_best_before_dates_say_the_range_is_covered(yoghurt, pol) -> None:
    yoghurt.notice.extract.batch_codes = []
    yoghurt.notice.extract.date_codes = [
        {"kind": "best_before", "from": "2026-11-05"},
        {"kind": "best_before", "from": "2026-11-19", "to": "2026-11-19"},
    ]
    assert any("2 best-before dates" in c for c in propose(yoghurt, pol).considerations)


def test_label_hold_proposal(dinosaur, pol) -> None:
    p = propose(dinosaur, pol)
    assert p.severity == "critical"
    assert len(p.store_actions) == 11
    assert all(a.action == "hold" and a.code == "L2026-0311" for a in p.store_actions)
    assert p.supplier_notice and p.vendor_case
    assert p.checkout_block is False and p.message_orders == []
    assert p.targets.shelf_minutes == 60


def test_label_unreadable_lot_holds_reporting_store_only(dinosaur, pol) -> None:
    dinosaur.lineage = None
    dinosaur.checks[0].lot = None
    p = propose(dinosaur, pol)
    assert [a.store_id for a in p.store_actions] == ["S012"]
    assert any("could not be read" in c for c in p.considerations)


def test_label_listing_fix_only(muesli, pol) -> None:
    p = propose(muesli, pol)
    assert p.severity == "high"
    assert p.store_actions == []
    assert [(f.field, f.add) for f in p.listing_fixes] == [("allergens", ["almond"])]
    assert p.supplier_notice is False and p.vendor_case is False
    assert p.targets.listing_minutes == 120


def test_low_severity_recall_proposes_no_store_action(yoghurt, pol) -> None:
    yoghurt.hazard_type = "quality_only"
    p = propose(yoghurt, pol)
    assert p.severity == "low"
    assert p.store_actions == []
    assert len(p.optional_store_actions) == 14
    assert (p.targets.message_minutes, p.targets.shelf_minutes) == (None, None)
    assert any("proposes no store action" in c for c in p.considerations)
