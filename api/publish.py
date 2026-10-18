"""Publishing to the desk's topics, with every attempt in publish_log and every give-up in publish_failures.

Published versus landed is a scoreboard figure, so a publish that fails twice is recorded with its body rather than
dropped.
"""

import json
import logging
import secrets
import time
from datetime import UTC, datetime
from functools import cache
from typing import Any

from google.cloud import pubsub_v1

from app import bq

logger = logging.getLogger(__name__)

PUBLISHER = "psd-api"
ATTEMPTS = 2
TIMEOUT_SECONDS = 30


def new_event_id() -> str:
    """Time-ordered and unique: nanoseconds since the epoch, then random bits."""
    return f"evt_{time.time_ns():x}{secrets.token_hex(4)}"


@cache
def _publisher() -> pubsub_v1.PublisherClient:
    return pubsub_v1.PublisherClient()


def topic_path(topic: str) -> str:
    return _publisher().topic_path(bq.client().project, topic)


def _log(table: str, row: dict[str, Any]) -> None:
    """A row the scoreboard counts; failing to write it never fails the publish."""
    try:
        errors = bq.client().insert_rows_json(bq.table_ref(table), [row])
    except Exception as e:
        errors = [f"{type(e).__name__}: {e}"]
    if errors:
        logger.error(
            "could not write %s row for %s: %s", table, row.get("event_id"), errors
        )


def publish(
    topic: str,
    body: dict[str, Any] | bytes,
    event_id: str,
    source: str,
    keep_failure: bool = True,
    **attributes: str,
) -> str | None:
    """Publishes body (a dict as JSON, bytes as they are); returns the message id, or None when both attempts failed.

    keep_failure=False is for a caller that still holds the message, such as the relay, which nacks it so Pub/Sub
    redelivers; every other give-up is written to publish_failures.
    """
    data = (
        body
        if isinstance(body, bytes)
        else json.dumps(body, ensure_ascii=False).encode("utf-8")
    )
    attrs = {
        "source": source,
        "event_id": event_id,
        **{k: str(v) for k, v in attributes.items()},
    }
    error = None
    for attempt in range(1, ATTEMPTS + 1):
        now = datetime.now(UTC).isoformat()
        try:
            message_id = (
                _publisher()
                .publish(topic_path(topic), data, **attrs)
                .result(timeout=TIMEOUT_SECONDS)
            )
        except Exception as e:
            error = f"{type(e).__name__}: {e}"[:1000]
            _log(
                "publish_log",
                {
                    "event_id": event_id,
                    "source": source,
                    "topic": topic,
                    "message_id": None,
                    "published_at": now,
                    "publisher": PUBLISHER,
                    "attempt": attempt,
                    "ok": False,
                    "error": error,
                },
            )
            continue
        _log(
            "publish_log",
            {
                "event_id": event_id,
                "source": source,
                "topic": topic,
                "message_id": message_id,
                "published_at": now,
                "publisher": PUBLISHER,
                "attempt": attempt,
                "ok": True,
                "error": None,
            },
        )
        return message_id
    logger.error("publish to %s failed for %s: %s", topic, event_id, error)
    if keep_failure:
        _log(
            "publish_failures",
            {
                "event_id": event_id,
                "source": source,
                "topic": topic,
                "failed_at": datetime.now(UTC).isoformat(),
                "error": error,
                "body": data.decode("utf-8", errors="replace"),
            },
        )
    return None
