import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest

from api import armor, feeds, recalls
from data import gen_notices

ANCHOR = datetime(2026, 10, 17, tzinfo=UTC)


class World:
    """One fake feed, a BigQuery that remembers the guids it was given, and what was published."""

    def __init__(self) -> None:
        self.notices = gen_notices.render_all(
            ["yoghurt_listeria", "kettle_no_exposure"], ANCHOR
        )
        self.feed = feeds.Feed(
            "test",
            "gs://b/test/feed.xml",
            attribution=gen_notices.BANNER,
            match=True,
            fictional=True,
        )
        self.body: bytes | Exception = gen_notices.feed_xml(self.notices)
        self.seen: set[str] = set()
        self.inserted: list[dict[str, Any]] = []
        self.published: list[tuple[str, dict[str, Any], str, str]] = []

    def fetch(self, feed: feeds.Feed) -> bytes:
        if isinstance(self.body, Exception):
            raise self.body
        return self.body

    def insert(self, rows: list[dict[str, Any]]) -> None:
        self.inserted.extend(rows)
        self.seen.update(r["guid"] for r in rows)

    def publish(self, topic, body, event_id, source, **attrs) -> str:
        self.published.append((topic, body, event_id, source))
        return "m1"


@pytest.fixture
def poller(monkeypatch) -> World:
    world = World()
    monkeypatch.setattr(recalls, "_health", {})
    monkeypatch.setattr(recalls, "_fetcher", world)
    monkeypatch.setattr(recalls.feeds, "feeds", lambda: [world.feed])
    monkeypatch.setattr(recalls, "_seen", lambda guids: world.seen & set(guids))
    monkeypatch.setattr(recalls, "_insert", world.insert)
    monkeypatch.setattr(recalls, "publish", world.publish)
    monkeypatch.setattr(
        recalls.armor, "screen", lambda text: armor.Screen(flagged=False)
    )
    return world


def test_a_new_notice_is_recorded_pending_then_published_once(poller) -> None:
    result = recalls.poll()
    assert (result["new"], result["published"], result["failed"]) == (2, 2, 0)
    assert [r["guid"] for r in poller.inserted] == [n.guid for n in poller.notices]
    assert {r["attribution"] for r in poller.inserted} == {gen_notices.BANNER}
    topic, body, event_id, source = poller.published[0]
    assert (topic, source) == ("psd-events", "recall")
    assert body["event_id"] == event_id and event_id.startswith("evt_")
    assert body["guid"] == poller.notices[0].guid and body["feed"] == "test"
    assert body["screen"] == {"flagged": False, "filters": [], "reason": None}
    assert gen_notices.BANNER in body["text"]
    assert "screen_reason" not in body and "attribution" not in body
    again = recalls.poll()
    assert (again["new"], again["published"]) == (0, 0) and len(poller.published) == 2


def test_a_failed_publish_is_counted_and_the_notice_is_not_republished(
    poller, monkeypatch
) -> None:
    monkeypatch.setattr(recalls, "publish", lambda *a, **k: None)
    assert recalls.poll()["failed"] == 2
    assert recalls.poll()["new"] == 0


def test_a_flagged_notice_is_still_published_with_its_flag(poller, monkeypatch) -> None:
    monkeypatch.setattr(
        recalls.armor,
        "screen",
        lambda text: armor.Screen(flagged=True, filters=["pi_and_jailbreak"]),
    )
    recalls.poll()
    assert all(b["screen"]["flagged"] for _, b, _, _ in poller.published)
    assert poller.inserted[0]["screen_reason"] == "pi_and_jailbreak"


def test_an_unreadable_regulator_feed_backs_off_and_the_others_carry_on(
    poller, monkeypatch
) -> None:
    live = feeds.Feed("fsanz", "https://x.test/feed.xml")
    monkeypatch.setattr(recalls.feeds, "feeds", lambda: [live, poller.feed])

    class Fetcher:
        def fetch(self, f):
            if f is live:
                raise feeds.FeedError("fsanz: HTTP 429", retry_after=3600)
            return poller.body

    monkeypatch.setattr(recalls, "_fetcher", Fetcher())
    result = recalls.poll()
    health = {h["feed"]: h for h in result["feeds"]}
    assert result["new"] == 2 and health["test"]["ok"] is True
    assert health["fsanz"]["ok"] is False and health["fsanz"]["failures"] == 1
    after = datetime.fromisoformat(health["fsanz"]["next_poll_after"])
    assert (
        after - datetime.fromisoformat(health["fsanz"]["last_poll"])
    ).total_seconds() == 3600
    recalls.poll()
    assert {h["feed"]: h for h in recalls.health()}["fsanz"]["failures"] == 1


def test_backoff_doubles_from_the_poll_interval_up_to_its_cap() -> None:
    now = datetime(2026, 10, 17, tzinfo=UTC)
    waits = [
        (datetime.fromisoformat(recalls._backoff(n, None, now)) - now).total_seconds()
        / 60
        for n in (1, 2, 3, 10)
    ]
    assert waits == [15, 30, 60, recalls.MAX_BACKOFF.total_seconds() / 60]


def test_the_test_feed_does_not_back_off(poller) -> None:
    poller.body = feeds.FeedError("test: gs://b/test/feed.xml does not exist")
    recalls.poll()
    assert recalls.health()[0]["next_poll_after"] is None


def test_a_second_poll_while_one_runs_is_skipped(poller) -> None:
    assert recalls._lock.acquire(blocking=False)
    try:
        assert recalls.poll() == {"skipped": "running"}
    finally:
        recalls._lock.release()


def test_the_fictional_feed_labels_a_title_its_item_did_not(poller) -> None:
    unlabelled = dataclasses.replace(
        poller.notices[0], title="Morrowdale Vanilla Yoghurt 1kg"
    )
    poller.body = gen_notices.feed_xml([unlabelled])
    recalls.poll()
    (row,) = poller.inserted
    assert row["title"] == "FICTIONAL TEST: Morrowdale Vanilla Yoghurt 1kg"
    assert row["text"].startswith("FICTIONAL TEST: Morrowdale Vanilla Yoghurt 1kg\n")


def _bare_items(n: int) -> bytes:
    """A live-style feed whose items have no description, so the poller reads their pages."""
    items = "".join(
        f"<item><title>Notice {i}</title><link>{feeds.PAGE_PREFIX}recall-alert/n{i}</link>"
        f"<guid>{i} at https://www.foodstandards.gov.au</guid></item>"
        for i in range(n)
    )
    return f"<rss><channel>{items}</channel></rss>".encode()


@pytest.fixture
def live(poller, monkeypatch):
    feed = feeds.Feed("fsanz", "https://www.foodstandards.gov.au/food-recalls-rss.xml")
    monkeypatch.setattr(recalls.feeds, "feeds", lambda: [feed])
    monkeypatch.setattr(recalls, "PAGE_SPACING_SECONDS", 0)
    poller.body = _bare_items(5)
    return poller


def test_page_fetches_are_capped_per_poll(live, monkeypatch) -> None:
    fetched = []
    monkeypatch.setattr(
        recalls.feeds, "page_text", lambda url: fetched.append(url) or "Page text."
    )
    recalls.poll()
    assert len(fetched) == recalls.PAGE_FETCHES
    texts = sorted(r["text"] for r in live.inserted)
    assert sum(t.endswith("Page text.") for t in texts) == recalls.PAGE_FETCHES
    assert len(live.inserted) == 5


def test_a_refused_page_ends_page_fetches_and_honours_retry_after(
    live, monkeypatch
) -> None:
    fetched = []

    def page_text(url):
        fetched.append(url)
        raise feeds.FeedError("HTTP 429", retry_after=7200, status=429)

    monkeypatch.setattr(recalls.feeds, "page_text", page_text)
    result = recalls.poll()
    assert len(fetched) == 1 and result["new"] == 5
    (h,) = result["feeds"]
    after = datetime.fromisoformat(h["next_poll_after"])
    assert (after - datetime.fromisoformat(h["last_poll"])).total_seconds() == 7200


def test_a_feed_that_keeps_refusing_is_stopped(live, monkeypatch) -> None:
    class Refusing:
        def fetch(self, feed):
            raise feeds.FeedError("fsanz: HTTP 403", status=403)

    monkeypatch.setattr(recalls, "_fetcher", Refusing())
    for _ in range(recalls.REFUSALS):
        recalls._health["fsanz"] = {
            **recalls._health.get(
                "fsanz", {"feed": "fsanz", "items": 0, "failures": 0}
            ),
            "next_poll_after": None,
        }
        recalls.poll()
    (h,) = recalls.health()
    assert h["stopped"] is True and h["refusals"] == recalls.REFUSALS
    monkeypatch.setattr(recalls, "_fetcher", live)
    recalls._health["fsanz"]["next_poll_after"] = None
    assert recalls.poll()["new"] == 0
