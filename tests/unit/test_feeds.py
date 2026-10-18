import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from api import feeds
from data import gen_notices

# Four FSANZ feed items, two in each description layout, with staff identifiers, business contacts and image and
# document links replaced by example.invalid placeholders that must never reach the notice text.
FSANZ = Path(__file__).parent / "feeds" / "fsanz_feed.xml"
FIELDS = (
    "Distributed in",
    "Recall reason",
    "Problem",
    "Food safety hazard",
    "What to do",
)


@pytest.fixture
def fsanz() -> list[feeds.Item]:
    return feeds.parse("fsanz", FSANZ.read_bytes())


def test_fsanz_items_keep_guid_link_time_and_the_notice_fields(fsanz) -> None:
    assert len(fsanz) == 4
    first = fsanz[0]
    assert first.guid == "7222 at https://www.foodstandards.gov.au"
    assert first.url.startswith("https://www.foodstandards.gov.au/food-recalls/")
    assert first.published_at == "2026-10-12T08:18:03+00:00"
    assert first.text.startswith(first.title + "\n\n")
    for item in fsanz:
        assert all(f in item.text for f in FIELDS), item.guid
        assert len(item.text) <= feeds.MAX_TEXT


def test_both_fsanz_templates_read_their_date_marking(fsanz) -> None:
    structured = fsanz[0].text
    free_text = next(i for i in fsanz if "Date Marking:" in i.text).text
    assert (
        "Date marking(s)\n\nQuollbrook Reduced Fat Milk 1L\n\nUse By 21/10/2026"
        in structured
    )
    assert "best before 15/03/2029" in free_text


def test_staff_and_business_contacts_images_and_documents_are_dropped(fsanz) -> None:
    for item in fsanz:
        text = item.text.lower()
        assert "@" not in text and "example.invalid" not in text, item.guid
        assert not re.search(r"\(0\d\) \d{4} \d{4}", item.text), item.guid
        assert "further information" not in text and "related links" not in text
        assert ".pdf" not in text and "click to expand" not in text
        assert "recall published" not in text


def test_an_older_notice_is_cut_at_its_contact_heading() -> None:
    html = (
        '<div class="field-bare"><h2>Problem</h2><p>Undeclared peanut.</p>'
        "<h2>For further information please contact</h2><p>Example Foods 1800 160 401</p>"
        "<p>jo@example.com</p></div>"
    )
    assert feeds.description_text(html) == "Problem\n\nUndeclared peanut."


def test_html_without_fsanz_fields_is_read_whole_without_scripts_or_navigation() -> (
    None
):
    page = (
        "<html><head><title>t</title><style>p{}</style></head><body><nav>Home</nav>"
        "<h3>Brand</h3><p>Hearthwell</p><script>var x = 1;</script><footer>Copyright</footer></body></html>"
    )
    assert feeds.description_text(page) == "Brand\n\nHearthwell"


def test_an_item_without_a_description_is_its_title_alone() -> None:
    rss = (
        b"<rss><channel><item><title>A recall</title><link>https://x.test/a</link>"
        b"<guid>g1</guid></item></channel></rss>"
    )
    (item,) = feeds.parse("fsanz", rss)
    assert (item.text, item.described, item.published_at) == ("A recall", False, None)


def test_a_feed_that_is_not_rss_is_a_feed_error() -> None:
    with pytest.raises(feeds.FeedError, match="not RSS"):
        feeds.parse("fsanz", b"<html>")


def test_the_generated_accc_layout_reads_through_the_same_parser() -> None:
    (notice,) = gen_notices.render_all(
        ["dinosaur_choking"], datetime(2026, 10, 17, tzinfo=UTC)
    )
    (item,) = feeds.parse("test", gen_notices.feed_xml([notice]))
    assert item.guid == notice.guid and item.described
    assert gen_notices.BANNER in item.text
    for heading in ("PRA number", "Identifying numbers", "Where the product was sold"):
        assert f"\n{heading}\n" in item.text
    assert "Lot number: L2026-0310" in item.text


class _Responses:
    """Stands in for httpx.get: answers in order and records the headers each call sent."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.headers: list[dict[str, str]] = []

    def __call__(self, url, headers, timeout, follow_redirects):
        self.headers.append(headers)
        return self.responses.pop(0)


def test_an_unchanged_feed_costs_one_conditional_get(monkeypatch) -> None:
    get = _Responses(
        httpx.Response(200, content=b"<rss/>", headers={"ETag": '"v1"'}),
        httpx.Response(304),
    )
    monkeypatch.setattr(feeds.httpx, "get", get)
    fetcher, feed = feeds.Fetcher(), feeds.Feed("fsanz", "https://x.test/feed.xml")
    assert fetcher.fetch(feed) == b"<rss/>"
    assert fetcher.fetch(feed) is None
    assert "If-None-Match" not in get.headers[0]
    assert get.headers[1]["If-None-Match"] == '"v1"'
    assert get.headers[1]["User-Agent"].startswith("ProductSafetyDesk/")


def test_a_refusal_is_a_feed_error_carrying_the_servers_retry_after(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        feeds.httpx,
        "get",
        _Responses(httpx.Response(429, headers={"Retry-After": "120"})),
    )
    with pytest.raises(feeds.FeedError) as raised:
        feeds.Fetcher().fetch(feeds.Feed("fsanz", "https://x.test/feed.xml"))
    assert "HTTP 429" in str(raised.value) and raised.value.retry_after == 120


def test_the_test_feed_is_read_again_only_when_its_object_changes(monkeypatch) -> None:
    blob = SimpleNamespace(generation=1, download_as_bytes=lambda: b"<rss/>")
    bucket = SimpleNamespace(get_blob=lambda name: blob)
    monkeypatch.setattr(
        feeds.storage,
        "Client",
        lambda project: SimpleNamespace(bucket=lambda name: bucket),
    )
    monkeypatch.setattr(feeds.bq, "client", lambda: SimpleNamespace(project="p"))
    fetcher, feed = feeds.Fetcher(), feeds.Feed("test", "gs://b/test/feed.xml")
    assert fetcher.fetch(feed) == b"<rss/>"
    assert fetcher.fetch(feed) is None
    blob.generation = 2
    assert fetcher.fetch(feed) == b"<rss/>"


def test_every_feed_names_its_source_and_only_the_fictional_feed_is_matched() -> None:
    by_name = {f.name: f for f in feeds.feeds()}
    fsanz = by_name["fsanz"].attribution
    assert fsanz.startswith("© Food Standards Australia New Zealand")
    assert "https://www.foodstandards.gov.au/legal-policies/copyright" in fsanz
    assert "not endorsed by FSANZ" in fsanz and "4.0" not in fsanz
    assert "https://creativecommons.org/licenses/by/3.0/au/" in fsanz
    assert by_name["test"].fictional and not by_name["fsanz"].fictional
    assert by_name["test"].attribution == gen_notices.BANNER.rstrip(".")
    assert feeds.matched_feeds() == {"test"}
    assert all(f.attribution for f in by_name.values())
    assert (
        "accc" not in by_name
        and "productsafety.gov.au" not in feeds.CONFIG.read_text(encoding="utf-8")
    )


def test_contacts_are_removed_on_every_path_even_without_the_fsanz_fields() -> None:
    page = (
        "<h3>What to do</h3><p>Return it for a refund.</p>"
        "<p>Call 1800 160 401, (02) 5550 1234 or 0491 570 156, or write to recalls@example.com.</p>"
        "<p>Barcode 2000000502113, batch B2026-091, best before 30/10/2026.</p>"
    )
    text = feeds.description_text(page)
    assert "@" not in text and "1800" not in text and "5550" not in text
    assert (
        "0491" not in text and "[phone removed]" in text and "[email removed]" in text
    )
    assert "2000000502113" in text and "B2026-091" in text and "30/10/2026" in text


def test_a_notice_page_outside_the_fsanz_recalls_pages_is_never_requested(
    monkeypatch,
) -> None:
    def get(*args, **kwargs):
        raise AssertionError("no request may be made")

    monkeypatch.setattr(feeds.httpx, "get", get)
    with pytest.raises(feeds.FeedError, match="not under"):
        feeds.page_text("https://example.com/food-recalls/x")


def test_a_redirect_is_followed_only_inside_the_allowed_pages(monkeypatch) -> None:
    inside = "https://www.foodstandards.gov.au/food-recalls/recall-alert/new"
    get = _Responses(
        httpx.Response(301, headers={"Location": inside}),
        httpx.Response(200, text="<p>Recalled.</p>"),
    )
    monkeypatch.setattr(feeds.httpx, "get", get)
    assert feeds.page_text(feeds.PAGE_PREFIX + "recall-alert/old") == "Recalled."
    monkeypatch.setattr(
        feeds.httpx,
        "get",
        _Responses(
            httpx.Response(302, headers={"Location": "https://elsewhere.test/x"})
        ),
    )
    with pytest.raises(feeds.FeedError, match="not under"):
        feeds.page_text(feeds.PAGE_PREFIX + "recall-alert/old")


@pytest.mark.parametrize(
    ("status", "refused"), [(403, True), (429, True), (503, True), (404, False)]
)
def test_refusals_and_server_errors_end_requests_to_the_server(status, refused) -> None:
    assert feeds.FeedError("x", status=status).refused is refused


def test_a_fictional_title_is_labelled_once() -> None:
    assert feeds.labelled("Morrowdale Vanilla Yoghurt 1kg") == (
        "FICTIONAL TEST: Morrowdale Vanilla Yoghurt 1kg"
    )
    assert feeds.labelled("FICTIONAL TEST: x") == "FICTIONAL TEST: x"
