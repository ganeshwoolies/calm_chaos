"""Observations for a draft: Memory Bank retrieval by scope, scored, and rendered as an unverified block.

The supplier, product and store scopes are searched by similarity to the incident's title, top TOP_K each; the
playbook scope is read whole, up to PLAYBOOK_LIMIT. Every scope is asked at once within the budget (PSD_MEMORY_BUDGET_MS);
a scope that has not answered by then is left out and the run records observations_timeout. Scoring blends relevance
(the returned distance), recency (update time) and importance (how many incidents the memory is linked to). An
observation with an open promotion pull request is left out, so a fact is never shown both as an observation and as
pending knowledge.
"""

import concurrent.futures
import math
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app import learn
from app.store import LocalStore

TOP_K = 5
PLAYBOOK_LIMIT = 20
MIN_SCORE = 0.3
# Recency halves in about three weeks: 30 days is one e-fold.
RECENCY_DAYS = 30.0


@dataclass(frozen=True)
class Observation:
    name: str
    fact: str
    scope: dict[str, str]
    updated: datetime | None
    score: float


def budget_ms() -> int:
    # A warm similarity search from the service's own region answers inside this; it stays a small share of the
    # draft's 20 s target. The first call on a new instance also creates the client and connects, which warm() does at
    # startup instead.
    return int(os.environ.get("PSD_MEMORY_BUDGET_MS", "2000"))


def scopes_for(
    supplier_id: str, product_id: str, store_ids: list[str]
) -> list[dict[str, str]]:
    return [
        {"supplier_id": supplier_id},
        {"product_id": product_id},
        *({"store_id": s} for s in store_ids[:3]),
        {"playbook": "psd"},
    ]


def _ask(name: str, scope: dict[str, str], query: str) -> list[Any]:
    if "playbook" in scope:
        found = learn.memories().retrieve(
            name=name,
            scope=scope,
            simple_retrieval_params={"page_size": PLAYBOOK_LIMIT},
        )
        return list(found)[:PLAYBOOK_LIMIT]
    found = learn.memories().retrieve(
        name=name,
        scope=scope,
        similarity_search_params={"search_query": query, "top_k": TOP_K},
    )
    return list(found)[:TOP_K]


def warm() -> None:
    """Creates Memory Bank's client and opens its connection, so the first draft's retrieval fits the budget."""
    name = learn.engine_name()
    if name:
        _ask(name, {"playbook": "psd"}, "")


def _when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def retrieve(
    store: LocalStore,
    scopes: list[dict[str, str]],
    query: str,
    now: datetime | None = None,
) -> tuple[list[Observation], bool]:
    """The observations worth showing for these scopes, best first, and whether any scope ran out of time."""
    name = learn.engine_name()
    if not name:
        return [], False
    now = now or datetime.now(UTC)
    links = [
        link for link in store.memory_links.values() if link["status"] == "generated"
    ]
    pending = {
        m for link in links if link.get("promotion_pr") for m in link["memory_names"]
    }
    incidents = Counter(m for link in links for m in set(link["memory_names"]))
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(scopes)))
    futures = [pool.submit(_ask, name, scope, query) for scope in scopes]
    done, waiting = concurrent.futures.wait(futures, timeout=budget_ms() / 1000)
    pool.shutdown(wait=False, cancel_futures=True)
    seen: dict[str, Observation] = {}
    for future, scope in zip(futures, scopes, strict=True):
        if future not in done or future.exception():
            continue
        for found in future.result():
            memory = found.memory
            if (
                not memory
                or not memory.name
                or not memory.fact
                or memory.name in pending
            ):
                continue
            updated = _when(memory.update_time) or _when(memory.create_time)
            age_days = (
                (now - updated).total_seconds() / 86400 if updated else RECENCY_DAYS
            )
            relevance = (
                max(0.0, 1.0 - found.distance) if found.distance is not None else 0.5
            )
            score = (
                0.5 * relevance
                + 0.3 * math.exp(-max(0.0, age_days) / RECENCY_DAYS)
                + 0.2 * min(1.0, incidents[memory.name] / 3)
            )
            if score >= MIN_SCORE and (
                memory.name not in seen or seen[memory.name].score < score
            ):
                seen[memory.name] = Observation(
                    memory.name, memory.fact, scope, updated, score
                )
    return sorted(seen.values(), key=lambda o: o.score, reverse=True), bool(waiting)


def render(observations: list[Observation], now: datetime | None = None) -> str:
    if not observations:
        return "none yet"
    now = now or datetime.now(UTC)
    lines = []
    for o in observations:
        age = (
            f"{max(0, (now - o.updated).days)} days old" if o.updated else "age unknown"
        )
        lines.append(f"- [{o.name}] ({age}): {o.fact}")
    return "<OBSERVATIONS unverified>\n" + "\n".join(lines) + "\n</OBSERVATIONS>"
