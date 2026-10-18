"""The store for incidents, tasks, the outbox and the audit log.

LocalStore keeps them in memory, for tests and local development. FirestoreStore keeps the same records in Firestore
(PSD_STORE=firestore), so a restart or a redeploy loses none of them. Callers change a record only through the store's
methods, never by editing a dict they were handed, so every change can be written through.
"""

import contextlib
import hashlib
import os
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

# A run that has neither paused nor failed by then is dead (it matches the Cloud Run request timeout), so a redelivered
# candidate may draft the incident again.
DRAFTING_LEASE_SECONDS = 600

# Admission verdicts that start a drafting run; every other verdict stops before any work is done.
RUNNABLE = ("new", "retry", "reraise")


def now() -> str:
    return datetime.now(UTC).isoformat()


def incident_id_for(candidate_id: str) -> str:
    """Also the session id of the incident's run, so a redelivered candidate lands in the same session."""
    return "inc-" + hashlib.sha1(candidate_id.encode()).hexdigest()[:10]


class LocalStore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.incidents: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.outbox: dict[str, dict[str, Any]] = {}
        self.vendor_cases: dict[str, dict[str, Any]] = {}
        self.listing_changes: dict[str, dict[str, Any]] = {}
        self.pos_block_requests: dict[str, dict[str, Any]] = {}
        self.suppressed: dict[str, str] = {}
        self.memory_links: dict[str, dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []

    # incidents
    def find_incident_for_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        return self.incidents.get(incident_id_for(candidate_id))

    def create_incident(self, record: dict[str, Any]) -> dict[str, Any]:
        incident = self.incidents.setdefault(
            record["incident_id"], {**record, "created_at": now()}
        )
        return incident

    def get_incident(self, incident_id: str) -> dict[str, Any]:
        return self.incidents[incident_id]

    def update_incident(self, incident_id: str, **fields: Any) -> dict[str, Any]:
        self.incidents[incident_id].update(fields)
        return self.incidents[incident_id]

    def admission(self, candidate_id: str) -> str:
        """Whether a delivery of this candidate starts a drafting run: one of RUNNABLE, or the reason it does not."""
        incident = self.find_incident_for_candidate(candidate_id)
        if incident is None:
            return "new"
        status = incident["status"]
        if status == "failed":
            return "retry"
        if status == "drafting":
            since = datetime.fromisoformat(incident["drafting_since"])
            stale = datetime.now(UTC) - since > timedelta(
                seconds=DRAFTING_LEASE_SECONDS
            )
            return "retry" if stale else "in_progress"
        if status == "dismissed":
            return "suppressed" if self.is_suppressed(candidate_id) else "reraise"
        if status == "blocked":
            return "blocked"
        return "duplicate"

    def begin_drafting(self, record: dict[str, Any]) -> dict[str, Any]:
        """Opens the incident, or reopens a failed, dead or expired-dismissal one, keeping how earlier attempts ended."""
        ts = now()
        incident: dict[str, Any] | None = self.incidents.get(record["incident_id"])
        if incident is None:
            incident = self.incidents[record["incident_id"]] = {
                **record,
                "created_at": ts,
                "attempt": 0,
                "history": [],
            }
        else:
            incident["history"].append(
                {
                    k: incident.get(k)
                    for k in (
                        "attempt",
                        "status",
                        "failure",
                        "dismiss_reason",
                        "session_id",
                    )
                }
            )
            for k in (
                "failure",
                "draft",
                "proposed",
                "screening",
                "dismissed_by",
                "dismiss_reason",
                "dismissed_at",
            ):
                incident.pop(k, None)
            incident.update(record)
        incident.update(
            status="drafting", drafting_since=ts, attempt=incident["attempt"] + 1
        )
        return incident

    def mark_failed(self, incident_id: str, node: str, error: Any) -> None:
        """Records why a drafting run stopped; only a run that has not paused can fail this way."""
        incident = self.incidents.get(incident_id)
        if incident is not None and incident["status"] == "drafting":
            incident.update(
                status="failed",
                failure={"node": node, "error": error, "at": now()},
            )

    def mark_blocked(
        self, incident_id: str, screening: dict[str, Any], proposed: dict[str, Any]
    ) -> None:
        """Ends a drafting run whose prompt Model Armor blocked; a redelivery of the candidate does not draft it again."""
        incident = self.incidents.get(incident_id)
        if incident is not None and incident["status"] == "drafting":
            incident.update(
                status="blocked",
                screening=screening,
                proposed=proposed,
                blocked_at=now(),
            )

    # suppression after dismissal
    def suppress(self, candidate_id: str, until: str) -> None:
        self.suppressed[candidate_id] = until

    def is_suppressed(self, candidate_id: str) -> bool:
        until = self.suppressed.get(candidate_id)
        return until is not None and until > now()

    # tasks
    def upsert_task(self, task: dict[str, Any]) -> dict[str, Any]:
        return self.tasks.setdefault(task["task_id"], task)

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        self.tasks[task_id].update(fields)
        return self.tasks[task_id]

    def open_tasks(self, incident_id: str) -> list[dict[str, Any]]:
        return sorted(
            (
                t
                for t in self.tasks.values()
                if t["incident_id"] == incident_id and t["status"] == "open"
            ),
            key=lambda t: t["task_id"],
        )

    # outbound records, all idempotent on their ids
    def queue_message(self, message: dict[str, Any]) -> dict[str, Any]:
        return self.outbox.setdefault(
            message["message_id"],
            {**message, "status": "queued", "created_at": now(), "sent_at": None},
        )

    def mark_sent(self, message_id: str) -> dict[str, Any]:
        self.outbox[message_id].update(status="sent", sent_at=now())
        return self.outbox[message_id]

    def create_vendor_case(self, case: dict[str, Any]) -> dict[str, Any]:
        return self.vendor_cases.setdefault(case["case_id"], case)

    def apply_listing_change(self, change: dict[str, Any]) -> dict[str, Any]:
        return self.listing_changes.setdefault(change["change_id"], change)

    def create_pos_block_request(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.pos_block_requests.setdefault(request["request_id"], request)

    # memory links: which incident produced which Memory Bank observations
    def link_memory(self, link: dict[str, Any]) -> dict[str, Any]:
        self.memory_links[link["link_id"]] = link
        return link

    def update_link(self, link_id: str, **fields: Any) -> dict[str, Any]:
        self.memory_links[link_id].update(fields)
        return self.memory_links[link_id]

    # audit
    def append_audit(
        self,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        before: Any = None,
        after: Any = None,
    ) -> None:
        self.audit.append(
            {
                "ts": now(),
                "actor": actor,
                "action": action,
                "object_type": object_type,
                "object_id": object_id,
                "before": before,
                "after": after,
            }
        )

    @contextlib.contextmanager
    def batch(self) -> Iterator[None]:
        """The writes of one decision, together: FirestoreStore commits them in one batch."""
        yield


# Collections FirestoreStore loads at start; the audit log is written, never read back.
COLLECTIONS = (
    "incidents",
    "tasks",
    "outbox",
    "vendor_cases",
    "listing_changes",
    "pos_block_requests",
    "suppressed",
    "memory_links",
)
# A Firestore batch takes at most 500 writes.
BATCH_LIMIT = 500


class FirestoreStore(LocalStore):
    """LocalStore's records kept in Firestore: loaded once when the service starts, every change written through.

    Reads come from memory, so a coordinator page polling every few seconds costs no Firestore reads. That holds only
    while one instance serves at a time, which psd-agents' max-instances=1 guarantees. The writes of one batch() are
    committed together when it ends, and every version written is passed to mirror as well (app/records.py).
    """

    def __init__(
        self,
        client: Any,
        prefix: str = "psd_",
        mirror: Callable[[list[tuple[str, str, dict[str, Any]]]], None] | None = None,
    ) -> None:
        self._client = client
        self._prefix = prefix
        self._mirror = mirror or (lambda rows: None)
        self._pending: dict[tuple[str, str], None] | None = None
        self._pending_audit: list[dict[str, Any]] = []
        super().__init__()
        for name in COLLECTIONS:
            target = getattr(self, name)
            for doc in self._collection(name).stream():
                data = doc.to_dict()
                target[doc.id] = data["until"] if name == "suppressed" else data

    def _collection(self, name: str) -> Any:
        return self._client.collection(self._prefix + name)

    def _value(self, name: str, key: str) -> dict[str, Any]:
        value = getattr(self, name)[key]
        return {"until": value} if name == "suppressed" else value

    def _save(self, name: str, key: str) -> None:
        if self._pending is not None:
            self._pending[(name, key)] = None
            return
        self._collection(name).document(key).set(self._value(name, key))
        self._mirror([(name, key, self._value(name, key))])

    @contextlib.contextmanager
    def batch(self) -> Iterator[None]:
        if self._pending is not None:
            yield
            return
        self._pending = {}
        try:
            yield
        finally:
            # What memory holds is written even when the block fails part-way, so a restart reloads what this process
            # last served.
            keys, self._pending = list(self._pending), None
            audit, self._pending_audit = self._pending_audit, []
            writes = [
                (self._collection(n).document(k), self._value(n, k)) for n, k in keys
            ]
            writes += [(self._collection("audit").document(), a) for a in audit]
            for start in range(0, len(writes), BATCH_LIMIT):
                batch = self._client.batch()
                for ref, value in writes[start : start + BATCH_LIMIT]:
                    batch.set(ref, value)
                batch.commit()
            self._mirror(
                [(n, k, self._value(n, k)) for n, k in keys]
                + [("audit", uuid.uuid4().hex, a) for a in audit]
            )

    def create_incident(self, record: dict[str, Any]) -> dict[str, Any]:
        incident = super().create_incident(record)
        self._save("incidents", record["incident_id"])
        return incident

    def update_incident(self, incident_id: str, **fields: Any) -> dict[str, Any]:
        incident = super().update_incident(incident_id, **fields)
        self._save("incidents", incident_id)
        return incident

    def begin_drafting(self, record: dict[str, Any]) -> dict[str, Any]:
        incident = super().begin_drafting(record)
        self._save("incidents", record["incident_id"])
        return incident

    def mark_failed(self, incident_id: str, node: str, error: Any) -> None:
        super().mark_failed(incident_id, node, error)
        if incident_id in self.incidents:
            self._save("incidents", incident_id)

    def mark_blocked(
        self, incident_id: str, screening: dict[str, Any], proposed: dict[str, Any]
    ) -> None:
        super().mark_blocked(incident_id, screening, proposed)
        if incident_id in self.incidents:
            self._save("incidents", incident_id)

    def suppress(self, candidate_id: str, until: str) -> None:
        super().suppress(candidate_id, until)
        self._save("suppressed", candidate_id)

    def upsert_task(self, task: dict[str, Any]) -> dict[str, Any]:
        new = task["task_id"] not in self.tasks
        stored = super().upsert_task(task)
        if new:
            self._save("tasks", task["task_id"])
        return stored

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        task = super().update_task(task_id, **fields)
        self._save("tasks", task_id)
        return task

    def queue_message(self, message: dict[str, Any]) -> dict[str, Any]:
        new = message["message_id"] not in self.outbox
        stored = super().queue_message(message)
        if new:
            self._save("outbox", message["message_id"])
        return stored

    def mark_sent(self, message_id: str) -> dict[str, Any]:
        message = super().mark_sent(message_id)
        self._save("outbox", message_id)
        return message

    def create_vendor_case(self, case: dict[str, Any]) -> dict[str, Any]:
        new = case["case_id"] not in self.vendor_cases
        stored = super().create_vendor_case(case)
        if new:
            self._save("vendor_cases", case["case_id"])
        return stored

    def apply_listing_change(self, change: dict[str, Any]) -> dict[str, Any]:
        new = change["change_id"] not in self.listing_changes
        stored = super().apply_listing_change(change)
        if new:
            self._save("listing_changes", change["change_id"])
        return stored

    def create_pos_block_request(self, request: dict[str, Any]) -> dict[str, Any]:
        new = request["request_id"] not in self.pos_block_requests
        stored = super().create_pos_block_request(request)
        if new:
            self._save("pos_block_requests", request["request_id"])
        return stored

    def link_memory(self, link: dict[str, Any]) -> dict[str, Any]:
        stored = super().link_memory(link)
        self._save("memory_links", link["link_id"])
        return stored

    def update_link(self, link_id: str, **fields: Any) -> dict[str, Any]:
        link = super().update_link(link_id, **fields)
        self._save("memory_links", link_id)
        return link

    def append_audit(
        self,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        before: Any = None,
        after: Any = None,
    ) -> None:
        super().append_audit(actor, action, object_type, object_id, before, after)
        if self._pending is not None:
            self._pending_audit.append(self.audit[-1])
        else:
            self._collection("audit").document().set(self.audit[-1])
            self._mirror([("audit", uuid.uuid4().hex, self.audit[-1])])


def firestore_enabled() -> bool:
    return os.environ.get("PSD_STORE") == "firestore"


def firestore_prefix() -> str:
    return os.environ.get("PSD_FIRESTORE_PREFIX", "psd_")


_firestore: list[Any] = []


def firestore_client() -> Any:
    """One Firestore client per process, for PSD_FIRESTORE_DATABASE (the default database when unset)."""
    if not _firestore:
        from google.cloud import firestore

        _firestore.append(
            firestore.Client(
                project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None,
                database=os.environ.get("PSD_FIRESTORE_DATABASE") or "(default)",
            )
        )
    return _firestore[0]


def make_store() -> LocalStore:
    """FirestoreStore with PSD_STORE=firestore (PSD_FIRESTORE_DATABASE, PSD_FIRESTORE_PREFIX); LocalStore otherwise."""
    if not firestore_enabled():
        return LocalStore()
    from app import records

    return FirestoreStore(
        firestore_client(),
        prefix=firestore_prefix(),
        mirror=records.append if records.enabled() else None,
    )


store = make_store()
