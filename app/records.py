"""The desk's records in BigQuery: each version FirestoreStore writes is appended to desk_records.

Firestore holds what the pages show now; BigQuery keeps every version, and the scoreboard's attested computations read
it through the v_desk_* views. An append that fails is logged and the desk goes on: Firestore already has the change.
Set PSD_DESK_RECORDS=off to write Firestore only.
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from app import bq

logger = logging.getLogger(__name__)

TABLE = "desk_records"


def enabled() -> bool:
    return os.environ.get("PSD_DESK_RECORDS", "bigquery") == "bigquery"


def append(rows: list[tuple[str, str, dict[str, Any]]]) -> None:
    """Appends (collection, record id, record) for each version written together."""
    if not rows:
        return
    written_at = datetime.now(UTC).isoformat()
    payload = [
        {
            "collection": collection,
            "record_id": record_id,
            "written_at": written_at,
            "record": json.dumps(record, default=str),
        }
        for collection, record_id, record in rows
    ]
    try:
        errors = bq.client().insert_rows_json(bq.table_ref(TABLE), payload)
    except Exception as e:
        logger.warning("%d desk records not appended to BigQuery: %s", len(rows), e)
        return
    if errors:
        logger.warning("desk records not appended to BigQuery: %s", errors[:3])
