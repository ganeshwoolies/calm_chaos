from app import policy
from app.actions import propose
from app.schemas import CustomerMessage
from app.validation import inconsistencies


def test_consistent_draft_passes(yoghurt, recall_draft) -> None:
    assert (
        inconsistencies(recall_draft, yoghurt, propose(yoghurt, policy.current()), [])
        == []
    )


def test_invented_store_is_flagged(yoghurt, recall_draft) -> None:
    recall_draft.narrative += " Store S999 also reported it."
    assert any(
        "S999" in p
        for p in inconsistencies(
            recall_draft, yoghurt, propose(yoghurt, policy.current()), []
        )
    )


def test_invented_code_is_flagged(yoghurt, recall_draft) -> None:
    recall_draft.evidence.append("Batch B2026-092 may also be affected.")
    assert any(
        "B2026-092" in p
        for p in inconsistencies(
            recall_draft, yoghurt, propose(yoghurt, policy.current()), []
        )
    )


def test_wrong_figure_is_flagged(yoghurt, recall_draft) -> None:
    recall_draft.title = (
        "Yoghurt recall, 16 stores, 37 online orders"  # 14 exposed, 15 received it
    )
    assert any(
        "16 stores" in p
        for p in inconsistencies(
            recall_draft, yoghurt, propose(yoghurt, policy.current()), []
        )
    )


def test_a_pack_size_in_the_product_name_is_not_a_figure(yoghurt, recall_draft) -> None:
    proposed = propose(yoghurt, policy.current())
    yoghurt.product.size = "1 unit"
    recall_draft.title = f"{yoghurt.product.brand} {yoghurt.product.name} 1 unit recall"
    assert inconsistencies(recall_draft, yoghurt, proposed, []) == []
    recall_draft.narrative += " 9999 units were found on the shelf."
    assert any(
        "9999 units" in p for p in inconsistencies(recall_draft, yoghurt, proposed, [])
    )


def test_missing_customer_message_is_flagged(yoghurt, recall_draft) -> None:
    recall_draft.customer_message = None
    assert any(
        "customer message" in p
        for p in inconsistencies(
            recall_draft, yoghurt, propose(yoghurt, policy.current()), []
        )
    )


def test_customer_message_without_orders_is_flagged(muesli, recall_draft) -> None:
    draft = recall_draft.model_copy(
        update={
            "title": "Muesli listing misses almond",
            "narrative": "The pack declares almond.",
            "evidence": [],
            "supplier_notice": None,
            "vendor_case_body": "P31007 listing.",
            "qa_alert": "Listing fix.",
            "customer_message": CustomerMessage(subject="x", body="y"),
        }
    )
    assert any(
        "no online orders" in p
        for p in inconsistencies(draft, muesli, propose(muesli, policy.current()), [])
    )


def test_missing_supplier_notice_is_flagged(yoghurt, recall_draft) -> None:
    recall_draft.supplier_notice = None
    assert any(
        "supplier notice" in p
        for p in inconsistencies(
            recall_draft, yoghurt, propose(yoghurt, policy.current()), []
        )
    )


def test_sources_used_must_have_been_shown(yoghurt, recall_draft) -> None:
    shown = ["/playbooks/microbial.md", "/policy/recall-response.md"]
    proposed = propose(yoghurt, policy.current())
    recall_draft.sources_used = ["/playbooks/microbial.md"]
    assert inconsistencies(recall_draft, yoghurt, proposed, shown) == []
    recall_draft.sources_used = [
        "/playbooks/microbial.md",
        "/playbooks/listeria-myths.md",
    ]
    assert any(
        "/playbooks/listeria-myths.md" in p
        for p in inconsistencies(recall_draft, yoghurt, proposed, shown)
    )
