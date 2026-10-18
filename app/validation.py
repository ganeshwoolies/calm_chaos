"""Checks that drafted text cites only what the evidence and the proposed actions contain."""

import re

from app.schemas import EvidencePack, IncidentText, ProposedActions

_STORE_ID = re.compile(r"\bS\d{3}\b")
_CODE = re.compile(r"\b[BL]\d{4}-\d{3,4}\b")
_FIGURE = re.compile(
    r"\b(\d{1,5})\s+(stores?|online orders?|orders?|units?)\b", re.IGNORECASE
)


def _texts(draft: IncidentText) -> list[str]:
    texts = [
        draft.title,
        draft.narrative,
        draft.vendor_case_body,
        draft.qa_alert,
        *draft.evidence,
        *draft.considerations,
    ]
    if draft.supplier_notice:
        texts.append(draft.supplier_notice)
    if draft.customer_message:
        texts += [draft.customer_message.subject, draft.customer_message.body]
    return texts


def inconsistencies(
    draft: IncidentText,
    ev: EvidencePack,
    proposed: ProposedActions,
    shown_paths: list[str],
) -> list[str]:
    problems: list[str] = []
    text = "\n".join(_texts(draft))

    unshown = sorted(set(draft.sources_used) - set(shown_paths))
    if unshown:
        problems.append(
            f"sources_used lists sources you were not shown: {', '.join(unshown)}; "
            f"list only paths from the policy and verified knowledge blocks ({', '.join(shown_paths)})"
        )

    known_stores = {a.store_id for a in proposed.store_actions} | {
        c.store_id for c in ev.checks
    }
    if ev.lineage:
        known_stores |= {r.store_id for r in ev.lineage.rows}
    unknown_stores = sorted(set(_STORE_ID.findall(text)) - known_stores)
    if unknown_stores:
        problems.append(f"store ids not in the evidence: {', '.join(unknown_stores)}")

    known_codes = {a.code for a in proposed.store_actions} | {
        c.lot for c in ev.checks if c.lot
    }
    if ev.lineage:
        known_codes |= {r.code for r in ev.lineage.rows}
    if ev.notice:
        known_codes |= set(ev.notice.extract.batch_codes)
    unknown_codes = sorted(set(_CODE.findall(text)) - known_codes)
    if unknown_codes:
        problems.append(
            f"batch or lot codes not in the evidence: {', '.join(unknown_codes)}"
        )

    allowed = {
        "store": {
            len(proposed.store_actions),
            len(proposed.optional_store_actions),
            len({c.store_id for c in ev.checks}),
        },
        "order": {len(proposed.message_orders)},
        "unit": {
            sum(a.qty_on_hand for a in proposed.store_actions),
            sum(a.qty_on_hand for a in proposed.optional_store_actions),
        },
    }
    if ev.lineage:
        allowed["store"].add(len({r.store_id for r in ev.lineage.store_rows}))
        # A store's own stock or delivery is an attested figure too, not only the totals.
        allowed["unit"] |= {
            n
            for r in ev.lineage.store_rows
            for n in (r.on_hand, r.delivered)
            if n is not None
        }
    # A pack size such as "1 unit" is part of the product's name, not a figure.
    figure_text = text
    for size in {ev.product.size, *(ev.notice.extract.sizes if ev.notice else [])}:
        if size:
            figure_text = re.sub(
                rf"\b{re.escape(size)}\b", " ", figure_text, flags=re.IGNORECASE
            )
    for number, noun in _FIGURE.findall(figure_text):
        key = "order" if "order" in noun.lower() else noun.lower().rstrip("s")
        if int(number) not in allowed[key]:
            problems.append(
                f"'{number} {noun}' does not match the attested figures {sorted(allowed[key])}"
            )

    if proposed.message_orders and not draft.customer_message:
        problems.append(
            "the proposal messages online orders, but there is no customer message"
        )
    if not proposed.message_orders and draft.customer_message:
        problems.append(
            "there are no online orders to message, so leave customer_message empty"
        )
    if proposed.supplier_notice and not draft.supplier_notice:
        problems.append("the proposal includes a supplier notice, but none was drafted")
    return problems
