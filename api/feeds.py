"""Recall feeds: fetching with conditional GET, parsing RSS items, and turning a notice's HTML into extraction text.

Only the notice fields extraction needs are kept. An FSANZ description also carries the publishing staff member's
email, the recalling business's contact block, product images and the recall PDF; none of them is read or stored, and
any email address or phone number left in the text is removed, whatever the page's layout.
"""

import email.utils
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx
import yaml
from google.cloud import storage

from app import bq
from app.knowledge import REPO_DIR

CONFIG = REPO_DIR / "config" / "feeds.yaml"
MAX_TEXT = 12_000
# A notice page is fetched only from here, redirects included.
PAGE_PREFIX = "https://www.foodstandards.gov.au/food-recalls/"
MAX_REDIRECTS = 3
FICTIONAL_LABEL = "FICTIONAL TEST"

# FSANZ description blocks, by CSS class. Kept blocks become extraction text; dropped blocks are skipped with
# everything nested inside them.
KEPT = (
    "field-recall-business",
    "field-bare",
    "field-location",
    "field-recall-type",
    "field-date-marking",
    "field-problem",
    "field-food-safety-hazard",
    "field-what-to-do",
)
DROPPED = (
    "field--name-uid",
    "field--name-created",
    "field--name-title",
    "field-further-information",
    "field-food-recall-image",
    "field-document",
    "field-field-media-file",
    "field-publish-date",
)
_LABELS = {"field-recall-business": "Business"}
# Older FSANZ notices keep contacts and links inside the summary block, after one of these headings.
_CONTACTS = re.compile(
    r"\n\s*(for further information|related links)\b.*", re.IGNORECASE | re.DOTALL
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Australian landline, mobile and 1300/1800 numbers. Barcodes, batch codes and dates do not start with 0 or 1300/1800.
_PHONE = re.compile(
    r"\(0\d\)\s?\d{4}\s?\d{4}|\+61(?:[ -]?\d){9}|\b0[2-478](?:[ -]?\d){8}\b|\b1[38]00(?:[ -]?\d){6}\b"
)
_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "tr",
    "section",
    "article",
}
_VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "col"}
# Never notice text, even on a page without the FSANZ fields.
_SKIPPED_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "head",
    "svg",
    "nav",
    "footer",
}


class FeedError(RuntimeError):
    """A feed could not be read; the poller records it and carries on with the other feeds."""

    def __init__(
        self, message: str, retry_after: float | None = None, status: int | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.status = status

    @property
    def refused(self) -> bool:
        """The server asked us to stop or slow down, or is failing: no more requests to it this poll."""
        return self.status in (403, 429) or (self.status or 0) >= 500


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    attribution: str = ""
    # False for a live feed: its notices name real brands and are never matched to the fictional catalogue.
    match: bool = False
    # True for the test feed: every notice is labelled FICTIONAL TEST by this flag, never by the feed's own text.
    fictional: bool = False


@dataclass(frozen=True)
class Item:
    feed: str
    guid: str
    title: str
    url: str
    published_at: str | None
    text: str
    # False when the item had no description, so text is the title alone.
    described: bool = True


def config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def feeds_bucket() -> str:
    return os.environ.get("PSD_FEEDS_BUCKET") or f"{bq.client().project}-psd-feeds"


def feeds() -> list[Feed]:
    return [
        Feed(
            name=f["name"],
            url=f["url"].replace("{feeds_bucket}", feeds_bucket()),
            attribution=f["attribution"],
            match=f.get("match") is True,
            fictional=f.get("fictional") is True,
        )
        for f in config()["feeds"]
    ]


def labelled(title: str) -> str:
    return title if title.startswith(FICTIONAL_LABEL) else f"{FICTIONAL_LABEL}: {title}"


def matched_feeds() -> set[str]:
    """Feeds whose notices may be matched to the catalogue; a feed missing from the config is not one of them."""
    return {f["name"] for f in config()["feeds"] if f.get("match") is True}


class _Text(HTMLParser):
    """Text of the kept blocks, or of the whole document when keep_all is set."""

    def __init__(self, keep_all: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.keep_all = keep_all
        self.stack: list[tuple[str, str | None]] = []
        self.parts: dict[str, list[str]] = {}

    def _active(self) -> str | None:
        for _, key in reversed(self.stack):
            if key:
                return key
        return "document" if self.keep_all else None

    def _add(self, text: str) -> None:
        key = self._active()
        if key in KEPT or key == "document":
            self.parts.setdefault(key, []).append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self._add("\n")
        if tag in _VOID_TAGS:
            return
        classes = (dict(attrs).get("class") or "").split()
        key = (
            "skip"
            if tag in _SKIPPED_TAGS
            else next((c for c in classes if c in KEPT or c in DROPPED), None)
        )
        self.stack.append((tag, key))
        if key in KEPT:
            self.parts.setdefault(key, [])

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in _BLOCK_TAGS:
            self._add("\n")

    def handle_data(self, data: str) -> None:
        self._add(data)


def _tidy(text: str) -> str:
    lines = [" ".join(line.replace("\xa0", " ").split()) for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _scrub(text: str) -> str:
    """Text up to any contact heading, with email addresses and phone numbers removed."""
    text = _CONTACTS.sub("", "\n" + text).strip()
    return _PHONE.sub("[phone removed]", _EMAIL.sub("[email removed]", text))


def description_text(description_html: str) -> str:
    """The notice fields of an FSANZ description; any other notice HTML as plain text. Contacts never survive."""
    parser = _Text()
    parser.feed(description_html)
    if not parser.parts:
        parser = _Text(keep_all=True)
        parser.feed(description_html)
        return _scrub(_tidy("".join(parser.parts.get("document", []))))
    blocks = []
    for key, chunks in parser.parts.items():
        text = _scrub(_tidy("".join(chunks)))
        if text:
            blocks.append(f"{_LABELS[key]}: {text}" if key in _LABELS else text)
    return "\n\n".join(blocks)


def _published(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return (
            email.utils.parsedate_to_datetime(value.strip()).astimezone(UTC).isoformat()
        )
    except (TypeError, ValueError):
        return None


def parse(feed: str, xml_bytes: bytes) -> list[Item]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise FeedError(f"{feed}: not RSS: {e}") from e
    items = []
    for node in root.iter("item"):
        title = " ".join((node.findtext("title") or "").split())
        link = (node.findtext("link") or "").strip()
        guid = (node.findtext("guid") or link).strip()
        if not guid:
            continue
        body = description_text(node.findtext("description") or "")
        items.append(
            Item(
                feed=feed,
                guid=guid,
                title=title,
                url=link,
                published_at=_published(node.findtext("pubDate")),
                text=f"{title}\n\n{body}"[:MAX_TEXT] if body else title,
                described=bool(body),
            )
        )
    return items


def _retry_after(response: httpx.Response) -> float | None:
    value = (response.headers.get("retry-after") or "").strip()
    if value.isdigit():
        return float(value)
    try:
        return max(
            0.0,
            (
                email.utils.parsedate_to_datetime(value) - datetime.now(UTC)
            ).total_seconds(),
        )
    except (TypeError, ValueError):
        return None


def _get(url: str, headers: dict[str, str]) -> httpx.Response:
    """One request, never following a redirect: the caller decides whether the new location may be fetched."""
    cfg = config()
    try:
        return httpx.get(
            url,
            headers={"User-Agent": cfg["user_agent"], **headers},
            timeout=cfg["timeout_seconds"],
            follow_redirects=False,
        )
    except httpx.HTTPError as e:
        raise FeedError(f"{url}: {type(e).__name__}: {e}") from e


def _error(name: str, response: httpx.Response) -> FeedError:
    moved = response.headers.get("location") if response.is_redirect else None
    return FeedError(
        f"{name}: HTTP {response.status_code}" + (f" to {moved}" if moved else ""),
        retry_after=_retry_after(response),
        status=response.status_code,
    )


class Fetcher:
    """Fetches feeds, sending back each feed's validators so an unchanged feed costs a 304 and nothing else."""

    def __init__(self) -> None:
        self.validators: dict[str, dict[str, str]] = {}

    def fetch(self, feed: Feed) -> bytes | None:
        """The feed body, or None when it has not changed since the last fetch."""
        if feed.url.startswith("gs://"):
            return self._fetch_gcs(feed)
        headers = {}
        cached = self.validators.get(feed.url, {})
        if etag := cached.get("etag"):
            headers["If-None-Match"] = etag
        if modified := cached.get("last_modified"):
            headers["If-Modified-Since"] = modified
        response = _get(feed.url, headers)
        if response.status_code == 304:
            return None
        if response.status_code != 200:
            raise _error(feed.name, response)
        self.validators[feed.url] = {
            k: v
            for k, v in (
                ("etag", response.headers.get("etag")),
                ("last_modified", response.headers.get("last-modified")),
            )
            if v
        }
        return response.content

    def _fetch_gcs(self, feed: Feed) -> bytes | None:
        bucket, _, name = feed.url.removeprefix("gs://").partition("/")
        blob = storage.Client(project=bq.client().project).bucket(bucket).get_blob(name)
        if blob is None:
            raise FeedError(f"{feed.name}: {feed.url} does not exist")
        generation = str(blob.generation)
        if self.validators.get(feed.url, {}).get("generation") == generation:
            return None
        self.validators[feed.url] = {"generation": generation}
        return blob.download_as_bytes()


def page_text(url: str) -> str:
    """The text of a notice page, read only for an item that came without a description, and only under PAGE_PREFIX."""
    for _ in range(MAX_REDIRECTS + 1):
        if not url.startswith(PAGE_PREFIX):
            raise FeedError(f"{url}: not under {PAGE_PREFIX}, so not fetched")
        response = _get(url, {})
        if response.is_redirect and response.headers.get("location"):
            url = urljoin(url, response.headers["location"])
            continue
        if response.status_code != 200:
            raise _error(url, response)
        return description_text(response.text)[:MAX_TEXT]
    raise FeedError(f"{url}: more than {MAX_REDIRECTS} redirects")
