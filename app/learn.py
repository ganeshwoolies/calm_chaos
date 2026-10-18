"""Observations: what closed and dismissed incidents teach the desk, kept in Memory Bank on the Agent Engine instance.

Only executor-assembled facts are sent (executor.observation_facts at close, the dismissal facts at dismissal): never
notice text, pack text or model output. Memory Bank consolidates them by scope (supplier, product, store, playbook)
into third-person observations that expire after 90 days. Every memory a generation creates or updates is linked to
its incident in the store's memory links, which retrieval counts for corroboration and promotion takes its sources
from. A generation that fails or runs out of time is logged and never stops an incident closing; its link keeps the
facts, so retry() can generate it again.

When an incident is dismissed after observations were generated from it, revoke() deletes the memories its links name
and regenerates each scope from the facts of the other incidents linked to it.
"""

import concurrent.futures
import hashlib
import json
import logging
import os
from typing import Any

from app.store import LocalStore, now

logger = logging.getLogger(__name__)

# One scope's generation, consolidation included; the close waits no longer than this for it.
GENERATE_TIMEOUT_SECONDS = 60


def engine_name() -> str | None:
    """The Agent Engine instance's resource name, or None where none is configured (tests, local runs)."""
    engine_id = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not (engine_id and project):
        return None
    location = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION") or "us-central1"
    return f"projects/{project}/locations/{location}/reasoningEngines/{engine_id}"


_memories: list[Any] = []


def memories() -> Any:
    """Memory Bank's memories client for the instance's project and region, one per process."""
    if not _memories:
        import agentplatform

        name = engine_name()
        assert name, "GOOGLE_CLOUD_AGENT_ENGINE_ID is not set"
        parts = name.split("/")
        _memories.append(
            agentplatform.Client(
                project=parts[1], location=parts[3]
            ).memory_banks.memories
        )
    return _memories[0]


def _scope_key(scope: dict[str, str]) -> str:
    return json.dumps(scope, sort_keys=True)


def _generate(
    name: str,
    scope: dict[str, str],
    facts: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> list[str]:
    """One scope's facts to Memory Bank; returns the names of the memories it created or updated."""
    operation = memories().generate(
        name=name,
        direct_memories_source={
            "direct_memories": [
                {
                    "fact": f["fact"],
                    "topics": [{"custom_memory_topic_label": f["topic"]}],
                }
                for f in facts
            ]
        },
        scope=scope,
        config={
            "wait_for_completion": True,
            "metadata": metadata,
            "metadata_merge_strategy": "MERGE",
        },
    )
    generated = (
        operation.response.generated_memories if operation.response else None
    ) or []
    return [
        g.memory.name
        for g in generated
        if g.memory
        and g.memory.name
        and getattr(g.action, "value", g.action) != "DELETED"
    ]


def _run(
    jobs: dict[str, tuple[dict[str, str], list[dict[str, Any]]]],
    metadata: dict[str, Any],
) -> dict[str, tuple[list[str], str | None]]:
    """Each scope's generation at once, each within GENERATE_TIMEOUT_SECONDS: names, or the error."""
    name = engine_name()
    assert name
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(jobs)))
    futures = {
        key: pool.submit(_generate, name, scope, facts, metadata)
        for key, (scope, facts) in jobs.items()
    }
    out: dict[str, tuple[list[str], str | None]] = {}
    for key, future in futures.items():
        try:
            out[key] = (future.result(timeout=GENERATE_TIMEOUT_SECONDS), None)
        except Exception as e:
            out[key] = ([], f"{type(e).__name__}: {e}"[:300])
            logger.warning("memory generation for %s failed: %s", key, out[key][1])
    pool.shutdown(wait=False, cancel_futures=True)
    return out


def _metadata(incident: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "incident_id": {"string_value": incident["incident_id"]},
        "source": {"string_value": source},
        "tier": {"string_value": "observation"},
        "hazard_type": {"string_value": incident.get("hazard_type") or ""},
    }


def link_id(incident_id: str, scope: dict[str, str]) -> str:
    return f"{incident_id}:{hashlib.sha1(_scope_key(scope).encode()).hexdigest()[:10]}"


def remember(
    store: LocalStore,
    incident: dict[str, Any],
    facts: list[dict[str, Any]],
    source: str,
) -> list[dict[str, Any]]:
    """Generates observations from one incident's facts, scope by scope, and links each memory to the incident."""
    if not facts or not engine_name():
        return []
    jobs: dict[str, tuple[dict[str, str], list[dict[str, Any]]]] = {}
    for f in facts:
        jobs.setdefault(_scope_key(f["scope"]), (f["scope"], []))[1].append(f)
    results = _run(jobs, _metadata(incident, source))
    links = []
    for key, (scope, group) in jobs.items():
        names, error = results[key]
        links.append(
            store.link_memory(
                {
                    "link_id": link_id(incident["incident_id"], scope),
                    "incident_id": incident["incident_id"],
                    "scope": scope,
                    "topics": sorted({f["topic"] for f in group}),
                    "facts": [{"fact": f["fact"], "topic": f["topic"]} for f in group],
                    "source": source,
                    "memory_names": names,
                    "status": "failed" if error else "generated",
                    "error": error,
                    "created_at": now(),
                    "promotion_pr": None,
                }
            )
        )
    return links


def retry(store: LocalStore, limit: int | None = None) -> list[dict[str, Any]]:
    """Generates failed links again from the facts each one kept, oldest first, and updates them in place."""
    failed = sorted(
        (link for link in store.memory_links.values() if link["status"] == "failed"),
        key=lambda link: link.get("created_at") or "",
    )[:limit]
    if not failed or not engine_name():
        return []
    # One generation round per incident and source, since _run gives every scope in a round the same metadata.
    rounds: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for link in failed:
        rounds.setdefault((link["incident_id"], link["source"]), []).append(link)
    retried = []
    for (incident_id, source), links in rounds.items():
        incident = store.incidents.get(incident_id, {"incident_id": incident_id})
        results = _run(
            {
                _scope_key(link["scope"]): (link["scope"], link["facts"])
                for link in links
            },
            _metadata(incident, source),
        )
        for link in links:
            names, error = results[_scope_key(link["scope"])]
            retried.append(
                store.update_link(
                    link["link_id"],
                    memory_names=names,
                    status="failed" if error else "generated",
                    error=error,
                )
            )
    return retried


def revoke(store: LocalStore, incident: dict[str, Any]) -> list[str]:
    """Deletes the memories an incident produced, then regenerates each of their scopes from the other incidents."""
    mine = [
        link
        for link in store.memory_links.values()
        if link["incident_id"] == incident["incident_id"]
        and link["status"] == "generated"
    ]
    if not mine or not engine_name():
        return []
    deleted = []
    for link in mine:
        for memory_name in link["memory_names"]:
            try:
                memories().delete(name=memory_name)
                deleted.append(memory_name)
            except Exception as e:
                logger.warning("could not delete memory %s: %s", memory_name, e)
        store.update_link(link["link_id"], status="revoked", revoked_at=now())
    for link in mine:
        others = [
            other
            for other in store.memory_links.values()
            if other["status"] == "generated" and other["scope"] == link["scope"]
        ]
        for other in others:
            source_incident = store.incidents.get(
                other["incident_id"], {"incident_id": other["incident_id"]}
            )
            key = _scope_key(other["scope"])
            result = _run(
                {key: (other["scope"], other["facts"])},
                _metadata(source_incident, other["source"]),
            )
            names, error = result[key]
            store.update_link(
                other["link_id"],
                memory_names=names,
                status="failed" if error else "generated",
            )
    return deleted
