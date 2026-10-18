"""Fictional recall notices for the test feed, one per recall scenario in data/truth.yaml, in the FSANZ or ACCC layout.

    uv run python data/gen_notices.py --out build/notices             # render every scenario locally
    uv run python data/gen_notices.py --publish yoghurt_listeria      # add one to the test feed
    uv run python data/gen_notices.py --publish all --count 10        # ten copies of each, for a burst

A notice follows its regulator's section headings and nothing else: no logo or Coat of Arms, a banner saying it is
fictional, FICTIONAL TEST in its title and guid, TEST- reference numbers and fictional brands only. Notices are hosted only in the project's private feeds
bucket, and every publish gets a new guid, so the poller treats it as a new notice.
"""

import argparse
import email.utils
import html
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from api.feeds import labelled
from data.gen_catalogue import anchor_from, build_catalogue, load_truth

BANNER = "Fictional test notice: not issued by FSANZ or the ACCC."
FEED_OBJECT = "test/feed.xml"
FEED_ITEMS = 100
# A reserved documentation domain: the notice pages live only in the private bucket, so links to them reveal nothing.
NOTICE_HOST = "https://fictional-notices.example"

# What each notice says beyond its scenario's facts in data/truth.yaml. A scenario with a product takes brand, name,
# size and supplier from the catalogue; one without names its own.
COPY: dict[str, dict[str, Any]] = {
    "yoghurt_listeria": {
        "hazard_type": "microbial",
        "states": ["NSW", "VIC", "QLD"],
        "sold": "{retailer} supermarkets and online",
        "reason": "Microbial contamination",
        "problem": "The recall is due to potential microbial (Listeria monocytogenes) contamination.",
        "hazard": "Listeria monocytogenes can cause serious illness. People who are pregnant, older people and "
        "people with weakened immune systems are at greatest risk.",
        "action": "Do not eat it. Take it back to where you bought it for a full refund, and see a doctor if you "
        "are worried about your health.",
    },
    "dinosaur_choking": {
        "hazard_type": "choking",
        "description": "Battery-operated toy dinosaur with light-up spines, for children aged 3 years and over.",
        "model": "LE-DINO-01",
        "print_barcode": True,
        "sold_days_ago": 40,
        "sold": "{retailer} supermarkets nationally and online",
        "reason": "The tail can detach from the body, exposing small parts.",
        "hazard": "A young child could choke on the loose parts, which can be fatal.",
        "action": "Take the toy away from children now and return it to where you bought it for a full refund.",
    },
    "yoghurt_500g_decoy": {
        "hazard_type": "foreign_matter",
        "brand": "Morrowdale",
        "name": "Vanilla Yoghurt",
        "size": "500g",
        "business": "Morrowdale Dairy Co",
        "best_before_days_ahead": 9,
        "states": ["VIC", "TAS"],
        "sold": "independent supermarkets",
        "reason": "Foreign matter",
        "problem": "The recall is due to the presence of foreign matter (pieces of hard plastic).",
        "hazard": "Pieces of hard plastic could cut or choke someone who eats the yoghurt.",
        "action": "Do not eat it. Take it back to where you bought it for a full refund.",
    },
    "kettle_no_exposure": {
        "hazard_type": "electrical_fire",
        "description": "Cordless electric kettle, 1.7 litre, with a 360 degree power base.",
        "model": "SRK-17",
        "sold_days_ago": 5,
        "sold": "{retailer} online",
        "reason": "The power base may overheat during use.",
        "hazard": "An overheating base can melt and catch fire, which could hurt someone or damage the home.",
        "action": "Unplug the base, stop using the kettle and return it to where you bought it for a full refund.",
    },
    "muesli_no_size": {
        "hazard_type": "allergen",
        "brand": "Nutty Fields",
        "name": "Toasted Muesli",
        "size": None,
        "business": "Nutty Fields Foods",
        "all_dates": True,
        "states": ["National"],
        "sold": "{retailer} supermarkets nationally and online",
        "reason": "Undeclared allergen",
        "problem": "The recall is due to the presence of an undeclared allergen (peanut).",
        "hazard": "The muesli contains peanut that its label does not declare, so people allergic to peanut could "
        "react to it.",
        "action": "If you are allergic to peanut, do not eat it. Take it back to where you bought it for a full "
        "refund.",
    },
}


@dataclass(frozen=True)
class Notice:
    scenario: str
    notice_format: str
    guid: str
    title: str
    link: str
    page_path: str
    published_at: datetime
    description: str
    expected: dict[str, Any]

    def page(self) -> str:
        return (
            '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f"<title>{html.escape(self.title)}</title></head>\n<body><main>\n{self.description}\n</main></body></html>\n"
        )


def _long(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


def _facts(
    truth: dict[str, Any],
    scenario: dict[str, Any],
    products: dict[str, dict],
    anchor: datetime,
) -> dict:
    copy = COPY[scenario["id"]]
    facts: dict[str, Any] = {
        **copy,
        "barcode": None,
        "sold": copy["sold"].format(retailer=truth["retailer"]),
    }
    if pid := scenario.get("product_id"):
        p = products[pid]
        facts.update(
            brand=p["brand"],
            name=p["name"],
            size=p["size"],
            business=truth["suppliers"][p["supplier_id"]],
            barcode=p["barcode"] if copy.get("print_barcode") else None,
        )
    batch = scenario.get("batch") or {}
    facts["codes"] = [batch["code"]] if batch else list(scenario.get("codes") or [])
    days_ahead = batch.get("best_before_days_ahead", copy.get("best_before_days_ahead"))
    facts["best_before"] = (
        (anchor + timedelta(days=days_ahead)).date() if days_ahead is not None else None
    )
    return facts


def _title(f: dict[str, Any]) -> str:
    return " ".join(p for p in (f["brand"], f["name"], f["size"]) if p)


def _fsanz(f: dict[str, Any], reference: str) -> str:
    marking = [_title(f), *(f"Batch {c}" for c in f["codes"])]
    if f["best_before"]:
        marking.append(f"Best before {f['best_before']:%d/%m/%Y}")
    if f.get("all_dates"):
        marking.append("All best before dates")

    def block(cls: str, label: str | None, inner: str) -> str:
        heading = f'<h3 class="field-label">{label}</h3>' if label else ""
        return f'<div class="field {cls}">{heading}<div class="field-item">{inner}</div></div>'

    e = html.escape
    where = "" if f["states"] == ["National"] else f" in {', '.join(f['states'])}"
    return "\n".join(
        [
            block("field-recall-business", None, e(f["business"])),
            f'<div class="field-bare"><p><strong>{BANNER}</strong> Reference {reference}.</p>'
            f"<p>{e(f['business'])} is conducting a recall of {e(_title(f))}. The product has been available for "
            f"sale at {e(f['sold'])}{where}.</p></div>",
            block("field-location", "Distributed in", ", ".join(f["states"])),
            block("field-recall-type", "Recall reason", e(f["reason"])),
            block(
                "field-date-marking",
                "Date marking(s)",
                "<br>".join(e(m) for m in marking),
            ),
            block("field-problem", "Problem", f"<p>{e(f['problem'])}</p>"),
            block(
                "field-food-safety-hazard",
                "Food safety hazard",
                f"<p>{e(f['hazard'])}</p>",
            ),
            block("field-what-to-do", "What to do", f"<p>{e(f['action'])}</p>"),
        ]
    )


def _accc(f: dict[str, Any], reference: str, anchor: datetime) -> str:
    numbers = [f"Barcode: {f['barcode']}"] if f["barcode"] else []
    numbers += [f"Lot number: {c}" for c in f["codes"]]
    sold_from = (anchor - timedelta(days=f["sold_days_ago"])).date()
    sections = [
        ("Recall published", _long(anchor.date())),
        ("PRA number", reference),
        ("Product description", f"{_title(f)}. {f['description']}"),
        ("Brand", f["brand"]),
        ("Model", f["model"]),
        ("Reason the product is recalled", f["reason"]),
        ("The hazards to consumers", f["hazard"]),
        ("What consumers should do", f["action"]),
        ("Identifying numbers", "; ".join(numbers)),
        ("Dates available for sale", f"{_long(sold_from)} to {_long(anchor.date())}"),
        ("Where the product was sold", f["sold"]),
    ]
    body = "\n".join(
        f"<h3>{label}</h3>\n<p>{html.escape(value)}</p>" for label, value in sections
    )
    return f"<p><strong>{BANNER}</strong></p>\n{body}"


def _expected(f: dict[str, Any]) -> dict[str, Any]:
    """The extract the notice supports, for the extraction evaluation: codes and dates exactly as printed."""
    bb = f["best_before"]
    return {
        "brand": f["brand"],
        "product_name": f["name"],
        "sizes": [f["size"]] if f["size"] else [],
        "barcodes": [f["barcode"]] if f["barcode"] else [],
        "batch_codes": f["codes"],
        "date_codes": [
            {"kind": "best_before", "from": bb.isoformat(), "to": bb.isoformat()}
        ]
        if bb
        else [],
        "hazard_type": f["hazard_type"],
    }


def render_all(
    scenarios: list[str],
    anchor: datetime,
    count: int = 1,
    truth: dict[str, Any] | None = None,
) -> list[Notice]:
    truth = truth or load_truth()
    products = {
        p["product_id"]: p for p in build_catalogue(truth, anchor_from(truth)).products
    }
    order = [s["id"] for s in truth["recall_scenarios"]]
    notices = []
    for scenario_id in scenarios:
        scenario = truth["recall_scenarios"][order.index(scenario_id)]
        f = _facts(truth, scenario, products, anchor)
        number = order.index(scenario_id) + 1
        for copy in range(count):
            stamp = f"{anchor:%Y%m%dT%H%M%SZ}" + (f"-{copy}" if copy else "")
            if scenario["format"] == "fsanz":
                description = _fsanz(f, f"TEST-FSANZ-{anchor:%Y}{number:04d}")
            else:
                description = _accc(f, f"TEST-{anchor:%Y}/{number:05d}", anchor)
            page_path = f"test/notices/{scenario_id}-{stamp.lower()}.html"
            notices.append(
                Notice(
                    scenario=scenario_id,
                    notice_format=scenario["format"],
                    guid=f"FICTIONAL-TEST:{scenario['format']}:{scenario_id}:{stamp}",
                    title=labelled(_title(f)),
                    link=f"{NOTICE_HOST}/{page_path}",
                    page_path=page_path,
                    published_at=anchor,
                    description=description,
                    expected=_expected(f),
                )
            )
    return notices


def _item(n: Notice) -> ET.Element:
    item = ET.Element("item")
    ET.SubElement(item, "title").text = n.title
    ET.SubElement(item, "link").text = n.link
    ET.SubElement(item, "description").text = n.description
    ET.SubElement(item, "pubDate").text = email.utils.format_datetime(
        n.published_at.astimezone(UTC), usegmt=True
    )
    ET.SubElement(item, "guid", isPermaLink="false").text = n.guid
    return item


def feed_xml(notices: list[Notice], existing: bytes | None = None) -> bytes:
    """The test feed: these notices first, then the items already in it, at most FEED_ITEMS."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Product Safety Desk test feed"
    ET.SubElement(channel, "link").text = f"{NOTICE_HOST}/{FEED_OBJECT}"
    ET.SubElement(
        channel, "description"
    ).text = f"{BANNER} Fictional brands, for testing the recall trigger."
    items = [_item(n) for n in notices]
    if existing:
        items += list(ET.fromstring(existing).iter("item"))
    channel.extend(items[:FEED_ITEMS])
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def main() -> int:
    truth = load_truth()
    ids = [s["id"] for s in truth["recall_scenarios"]]
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--out",
        type=Path,
        help="write every scenario's page and a feed.xml to this folder",
    )
    action.add_argument(
        "--publish",
        choices=[*ids, "all"],
        help="add the scenario's notice to the test feed",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="copies of each notice, each with its own guid",
    )
    parser.add_argument(
        "--anchor", help="ISO time the notices are published at (default: now)"
    )
    args = parser.parse_args()

    anchor = (
        datetime.fromisoformat(args.anchor)
        if args.anchor
        else datetime.now(UTC).replace(microsecond=0)
    )
    if args.out:
        notices = render_all(ids, anchor, args.count, truth)
        for n in notices:
            page = args.out / n.page_path
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(n.page(), encoding="utf-8")
        (args.out / FEED_OBJECT).write_bytes(feed_xml(notices))
        print(f"wrote {len(notices)} notices and {FEED_OBJECT} under {args.out}")
        return 0

    from api.feeds import feeds_bucket

    bucket_name = feeds_bucket()
    notices = render_all(
        ids if args.publish == "all" else [args.publish],
        anchor,
        args.count,
        truth,
    )
    publish(notices, bucket_name)
    for n in notices:
        print(f"published {n.guid}")
    print(
        f"gs://{bucket_name}/{FEED_OBJECT} updated; the next poll picks the notices up"
    )
    return 0


def publish(notices: list[Notice], bucket_name: str) -> None:
    """Uploads each notice's page, then puts the notices at the top of the test feed."""
    from google.cloud import storage

    from app import bq

    bucket = storage.Client(project=bq.client().project).bucket(bucket_name)
    for n in notices:
        bucket.blob(n.page_path).upload_from_string(
            n.page(), content_type="text/html; charset=utf-8"
        )
    existing = bucket.get_blob(FEED_OBJECT)
    bucket.blob(FEED_OBJECT).upload_from_string(
        feed_xml(notices, existing.download_as_bytes() if existing else None),
        content_type="application/rss+xml",
    )


if __name__ == "__main__":
    sys.exit(main())
