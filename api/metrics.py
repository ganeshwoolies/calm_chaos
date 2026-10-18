"""The scoreboard: each tile is a Metric concept in the bundle, and its value is only what its attested computation returns.

GET /metrics is public. It lists the bundle's metrics in their order; a tile carries numbers only when its metric and its
computation are reviewed and the computation's run attests, and otherwise a dash and the reason. Viewers share one run
every CACHE_SECONDS, so a busy page costs no more BigQuery.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter

from app import attest
from app.knowledge import Concept, PolicyUnavailable, knowledge_version, load_bundle

CACHE_SECONDS = 60.0

router = APIRouter()
_cache: dict[str, Any] = {"at": 0.0, "board": None}
_lock = threading.Lock()


def _tile(metric: Concept) -> dict[str, Any]:
    meta = metric.meta
    tile = {
        "metric": metric.path,
        "title": metric.title,
        "description": meta.get("description"),
        "unit": meta.get("unit"),
        "headline": meta.get("headline"),
        "computation": meta.get("computation"),
    }
    if reason := metric.unusable_reason():
        return {**tile, "unavailable": f"awaiting review ({reason})"}
    try:
        receipt = attest.run_attested(
            str(meta.get("computation")),
            {},
            used_by=f"scoreboard:{metric.id.rsplit('/', 1)[-1]}",
        )
    except (PolicyUnavailable, attest.AttestationFailed) as e:
        return {**tile, "unavailable": str(e)}
    except Exception as e:
        return {**tile, "unavailable": f"{type(e).__name__}: {e}"[:300]}
    return {
        **tile,
        "rows": receipt.result,
        "receipt_id": receipt.receipt_id,
        "attested_at": receipt.created_at,
    }


def scoreboard() -> dict[str, Any]:
    with _lock:
        if (
            _cache["board"] is not None
            and time.monotonic() - _cache["at"] < CACHE_SECONDS
        ):
            return _cache["board"]
        bundle = load_bundle()
        metrics = sorted(
            (c for c in bundle.concepts.values() if c.type == "Metric"),
            key=lambda c: (c.meta.get("order", 999), c.path),
        )
        with ThreadPoolExecutor(max_workers=5) as pool:
            tiles = list(pool.map(_tile, metrics))
        board = {"knowledge_version": knowledge_version(bundle), "tiles": tiles}
        _cache.update(at=time.monotonic(), board=board)
        return board


@router.get("/metrics")
def metrics() -> dict[str, Any]:
    return scoreboard()
