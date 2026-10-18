"""The recall poller: reads each feed, records the notices it has not seen, screens them and publishes them.

The guid is the dedupe key. A notice is recorded in recall_notices, status pending, before it is published, so no
notice is published twice; a publish that fails keeps its body in publish_failures. One poll runs at a time.

The poller is a polite client of the regulator: a feed that fails is polled less often and its Retry-After is honoured,
notice pages are fetched at most PAGE_FETCHES a poll and spaced out, a refusal ends page fetches for the poll, and a
feed that refuses REFUSALS times in a row is stopped until psd-api restarts.
"""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from google.cloud import bigquery

from api import armor, feeds
from api.publish import new_event_id, publish
from app import bq, store

logger = logging.getLogger(__name__)

TOPIC = "psd-events"
SOURCE = "recall"
POLL_INTERVAL = timedelta(minutes=15)
# A regulator's feed that keeps failing is polled less often, doubling from the poll interval up to this.
MAX_BACKOFF = timedelta(hours=6)
PAGE_FETCHES = 3
PAGE_SPACING_SECONDS = 2.0
# 403s in a row, from the feed or its pages, after which the feed is stopped rather than retried.
REFUSALS = 3

_SEEN_SQL = "SELECT guid FROM recall_notices WHERE guid IN UNNEST(@guids)"

_INSERT_SQL = """INSERT INTO recall_notices
  (guid, feed, title, url, attribution, published_at, first_seen, event_id, text, screen_flagged, screen_reason,
   match_status, updated_at)
SELECT guid, feed, title, url, attribution, published_at, CURRENT_TIMESTAMP(), event_id, text, screen_flagged,
  screen_reason, 'pending', CURRENT_TIMESTAMP()
FROM UNNEST(@notices)"""
# Recorded with the notice but not part of the event the transforms read.
_NOT_PUBLISHED = ("attribution", "screen_reason")

_lock = threading.Lock()
_fetcher = feeds.Fetcher()
_health: dict[str, dict[str, Any]] = {}

# With PSD_STORE=firestore each feed's health and the validators of its last fetch are kept in Firestore too, so an
# instance that scaled to zero starts where the last one stopped: still backing off a refusing feed, and asking an
# unchanged feed for a 304.
STATE_COLLECTION = "feed_state"
_state_loaded: list[bool] = []


def _state_collection() -> Any:
    return store.firestore_client().collection(
        store.firestore_prefix() + STATE_COLLECTION
    )


def _load_state() -> None:
    if _state_loaded or not store.firestore_enabled():
        return
    for doc in _state_collection().stream():
        state = doc.to_dict() or {}
        _health[doc.id] = state.get("health") or {}
        validators = dict(state.get("validators") or {})
        if url := validators.pop("url", None):
            _fetcher.validators[url] = validators
    _state_loaded.append(True)


def _save_state() -> None:
    if not store.firestore_enabled():
        return
    for feed in feeds.feeds():
        if feed.name not in _health:
            continue
        _state_collection().document(feed.name).set(
            {
                "health": _health[feed.name],
                "validators": {
                    **_fetcher.validators.get(feed.url, {}),
                    "url": feed.url,
                },
            }
        )


def health() -> list[dict[str, Any]]:
    return [dict(h) for h in _health.values()]


def _backoff(failures: int, retry_after: float | None, now: datetime) -> str:
    wait = min(POLL_INTERVAL * 2 ** (failures - 1), MAX_BACKOFF)
    if retry_after:
        wait = max(wait, timedelta(seconds=retry_after))
    return (now + wait).isoformat()


def _refused(feed: feeds.Feed, e: feeds.FeedError, now: datetime) -> None:
    """Backs a regulator's feed off after it refused a request, and stops it after REFUSALS 403s in a row."""
    h = _health[feed.name]
    if feed.url.startswith("http") and e.refused:
        h["next_poll_after"] = _backoff(max(h["failures"], 1), e.retry_after, now)
    if e.status == 403:
        h["refused_this_poll"] = True
        h["refusals"] = h.get("refusals", 0) + 1
        if h["refusals"] >= REFUSALS and not h.get("stopped"):
            h["stopped"] = True
            logger.error(
                "feed %s stopped after %d refusals in a row; it is polled again only after psd-api restarts",
                feed.name,
                h["refusals"],
            )


def _read(feed: feeds.Feed, now: datetime) -> list[feeds.Item]:
    """The feed's items, with its health updated; nothing when it is unchanged, backing off, stopped or unreadable."""
    h = _health.setdefault(feed.name, {"feed": feed.name, "items": 0, "failures": 0})
    if h.get("stopped"):
        return []
    if (after := h.get("next_poll_after")) and now < datetime.fromisoformat(after):
        return []
    h["last_poll"] = now.isoformat()
    try:
        body = _fetcher.fetch(feed)
        items = feeds.parse(feed.name, body) if body is not None else []
    except feeds.FeedError as e:
        failures = h["failures"] + 1
        # Backing off is politeness to someone else's server; the test feed is the project's own bucket.
        after = (
            _backoff(failures, e.retry_after, now)
            if feed.url.startswith("http")
            else None
        )
        h.update(ok=False, error=str(e), failures=failures, next_poll_after=after)
        logger.warning("feed %s unreadable (%d in a row): %s", feed.name, failures, e)
        if e.status == 403:
            _refused(feed, e, now)
        return []
    h.update(
        ok=True,
        error=None,
        failures=0,
        next_poll_after=None,
        changed=body is not None,
    )
    if body is not None:
        h["items"] = len(items)
    return items


def _seen(guids: list[str]) -> set[str]:
    rows = bq.rows(_SEEN_SQL, [bigquery.ArrayQueryParameter("guids", "STRING", guids)])
    return {r["guid"] for r in rows}


class _Pages:
    """The notice pages one poll may still fetch: PAGE_FETCHES at most, spaced out, none after a refusal."""

    def __init__(self) -> None:
        self.left = PAGE_FETCHES
        self.last = 0.0

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        wait = self.last + PAGE_SPACING_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        return True

    def stop(self) -> None:
        self.left = 0


def _text(item: feeds.Item, feed: feeds.Feed, pages: _Pages, now: datetime) -> str:
    if item.described or not item.url.startswith(feeds.PAGE_PREFIX):
        return item.text
    if not pages.take():
        logger.info(
            "no page fetches left this poll; %s is extracted from its title", item.url
        )
        return item.text
    try:
        return f"{item.title}\n\n{feeds.page_text(item.url)}"[: feeds.MAX_TEXT]
    except feeds.FeedError as e:
        logger.warning(
            "notice page %s unreadable, extracting the title alone: %s", item.url, e
        )
        if e.refused:
            pages.stop()
            _refused(feed, e, now)
        return item.text


def _timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _insert(notices: list[dict[str, Any]]) -> None:
    def struct(n: dict[str, Any]) -> bigquery.StructQueryParameter:
        return bigquery.StructQueryParameter(
            None,
            bigquery.ScalarQueryParameter("guid", "STRING", n["guid"]),
            bigquery.ScalarQueryParameter("feed", "STRING", n["feed"]),
            bigquery.ScalarQueryParameter("title", "STRING", n["title"]),
            bigquery.ScalarQueryParameter("url", "STRING", n["url"]),
            bigquery.ScalarQueryParameter("attribution", "STRING", n["attribution"]),
            bigquery.ScalarQueryParameter(
                "published_at", "TIMESTAMP", _timestamp(n["published_at"])
            ),
            bigquery.ScalarQueryParameter("event_id", "STRING", n["event_id"]),
            bigquery.ScalarQueryParameter("text", "STRING", n["text"]),
            bigquery.ScalarQueryParameter(
                "screen_flagged", "BOOL", n["screen"]["flagged"]
            ),
            bigquery.ScalarQueryParameter(
                "screen_reason", "STRING", n["screen_reason"]
            ),
        )

    client = bq.client()
    job = client.query(
        _INSERT_SQL,
        job_config=bq.job_config(
            [
                bigquery.ArrayQueryParameter(
                    "notices", "STRUCT", [struct(n) for n in notices]
                )
            ]
        ),
        location=bq.location(),
    )
    job.result()


def _notice(
    item: feeds.Item, feed: feeds.Feed, pages: _Pages, now: datetime
) -> dict[str, Any]:
    text = _text(item, feed, pages, now)
    title = item.title
    if feed.fictional:
        title = feeds.labelled(item.title)
        text = title + text[len(item.title) :] if text.startswith(item.title) else text
    screen = armor.screen(text)
    return {
        "event_id": new_event_id(),
        "source": SOURCE,
        "feed": item.feed,
        "guid": item.guid,
        "title": title,
        "url": item.url,
        "attribution": feed.attribution,
        "published_at": item.published_at,
        "text": text,
        "screen": screen.as_dict(),
        "screen_reason": screen.reason or (", ".join(screen.filters) or None),
    }


def _poll(now: datetime) -> dict[str, Any]:
    _load_state()
    found: dict[str, tuple[feeds.Item, feeds.Feed]] = {}
    for feed in feeds.feeds():
        for item in _read(feed, now):
            found.setdefault(item.guid, (item, feed))
    seen = _seen(list(found)) if found else set()
    pages = _Pages()
    notices = [_notice(*found[guid], pages, now) for guid in found if guid not in seen]
    if notices:
        _insert(notices)
    published = failed = 0
    for n in notices:
        body = {k: v for k, v in n.items() if k not in _NOT_PUBLISHED}
        if publish(TOPIC, body, n["event_id"], SOURCE):
            published += 1
        else:
            failed += 1
    for h in _health.values():
        h["new"] = sum(1 for n in notices if n["feed"] == h["feed"])
        # Refusals count in a row across polls: only a poll the server answered without one clears them.
        if h.get("ok") and not h.pop("refused_this_poll", False):
            h["refusals"] = 0
    _save_state()
    logger.info(
        "poll: %d items, %d new, %d published, %d failed",
        len(found),
        len(notices),
        published,
        failed,
    )
    return {
        "items": len(found),
        "new": len(notices),
        "published": published,
        "failed": failed,
        "feeds": health(),
    }


def poll() -> dict[str, Any]:
    """Polls every feed once; skipped while another poll is running."""
    if not _lock.acquire(blocking=False):
        return {"skipped": "running"}
    try:
        return _poll(datetime.now(UTC))
    finally:
        _lock.release()
