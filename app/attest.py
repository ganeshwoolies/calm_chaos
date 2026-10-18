"""Attested computations: run a sanctioned computation from the knowledge bundle and prove the run used it.

The caller supplies parameter values only; the SQL text comes from the pinned bundle and is bound by name, never
substituted. The bundle's own attester checks the receipt before any figure is used, and every run, passing or not,
is appended to the attestations table. A figure without a passing receipt is never shown.
"""

import importlib.util
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from google.cloud import bigquery

from app import bq
from app.knowledge import PolicyUnavailable, knowledge_version, load_bundle

_SCALAR = {
    "string": "STRING",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "integer": "INT64",
    "float": "FLOAT64",
    "boolean": "BOOL",
}
_ARRAY = re.compile(r"^array<(\w+)>$")


class AttestationFailed(RuntimeError):
    """The SQL BigQuery ran differs from the sanctioned file, or the receipt could not be recorded."""


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    concept: str
    knowledge_version: str
    params: dict[str, Any]
    job_id: str
    executed_sql: str
    result: list[dict[str, Any]]
    attested: bool
    reason: str | None
    used_by: str
    created_at: str


def _coerce(kind: str, value: Any) -> Any:
    if value is None:
        return None
    if kind == "date" and not isinstance(value, date):
        return date.fromisoformat(str(value))
    if kind == "timestamp" and not isinstance(value, datetime):
        return datetime.fromisoformat(str(value))
    if kind == "integer":
        return int(value)
    return value


def bind(declared: list[dict[str, Any]], params: dict[str, Any]) -> list[Any]:
    """Query parameters for the declared parameters, typed, with NULL for an absent optional one."""
    names = {p["name"] for p in declared}
    if unknown := sorted(set(params) - names):
        raise ValueError(f"parameters not declared by the computation: {unknown}")
    bound: list[Any] = []
    for p in declared:
        name, kind = p["name"], str(p["type"]).lower()
        value = params.get(name)
        if value is None and p.get("required"):
            raise ValueError(f"parameter {name} is required")
        if m := _ARRAY.match(kind):
            inner = m.group(1)
            bound.append(
                bigquery.ArrayQueryParameter(
                    name, _SCALAR[inner], [_coerce(inner, v) for v in value or []]
                )
            )
        else:
            bound.append(
                bigquery.ScalarQueryParameter(name, _SCALAR[kind], _coerce(kind, value))
            )
    return bound


def _attester(root: Path, resource: str) -> ModuleType:
    path = root / resource.lstrip("/")
    spec = importlib.util.spec_from_file_location(f"psd_attester_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise PolicyUnavailable(f"attester {resource} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _label(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.lower())[:63]


def run_attested(
    concept_path: str,
    params: dict[str, Any],
    used_by: str,
    client: bigquery.Client | None = None,
    now: datetime | None = None,
) -> Receipt:
    """Runs a sanctioned computation and returns its receipt; raises AttestationFailed when the check fails."""
    client = client or bq.client()
    bundle = load_bundle()
    concept = bundle.get(concept_path)
    if concept is None or concept.type != "Attested Computation":
        raise PolicyUnavailable(
            f"{concept_path} is not an Attested Computation in the bundle"
        )
    if reason := concept.unusable_reason(now):
        raise PolicyUnavailable(f"{concept_path} cannot be used: {reason}")
    if concept.meta.get("runtime") != "bigquery":
        raise PolicyUnavailable(f"{concept_path} does not run on bigquery")
    sanctioned = (bundle.root / str(concept.meta["computation"]).lstrip("/")).read_text(
        encoding="utf-8"
    )
    parameters = bind(concept.meta.get("parameters") or [], params)
    job = client.query(
        sanctioned,
        job_config=bq.job_config(
            parameters,
            labels={
                "psd_concept": _label(concept.id.rsplit("/", 1)[-1]),
                "psd_used_by": _label(used_by),
            },
            bq=client,
        ),
        location=bq.location(),
    )
    result = [bq.jsonable(dict(row)) for row in job.result()]
    ok, why = _attester(bundle.root, concept.meta["attester"]["resource"]).verify(
        sanctioned, job.query
    )
    receipt = Receipt(
        receipt_id=f"rcpt-{uuid.uuid4().hex[:12]}",
        concept=concept_path,
        knowledge_version=knowledge_version(bundle),
        params=bq.jsonable(params),
        job_id=job.job_id,
        executed_sql=job.query,
        result=result,
        attested=bool(ok),
        reason=why,
        used_by=used_by,
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
    )
    errors = client.insert_rows_json(
        bq.table_ref("attestations", client),
        [
            {
                **receipt.__dict__,
                "params": json.dumps(receipt.params),
                "result": json.dumps(receipt.result),
            }
        ],
    )
    if errors:
        raise AttestationFailed(
            f"receipt {receipt.receipt_id} could not be recorded: {errors}"
        )
    if not receipt.attested:
        raise AttestationFailed(f"{concept_path} failed attestation: {why}")
    return receipt


_RECEIPT_SQL = "SELECT * FROM attestations WHERE receipt_id = @receipt_id"


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def load_receipt(
    receipt_id: str, client: bigquery.Client | None = None
) -> Receipt | None:
    """A recorded receipt, or None when there is none or it did not attest: only a passing receipt's figures are used."""
    client = client or bq.client()
    job = client.query(
        _RECEIPT_SQL,
        job_config=bq.job_config(
            [bigquery.ScalarQueryParameter("receipt_id", "STRING", receipt_id)],
            bq=client,
        ),
        location=bq.location(),
    )
    rows = [bq.jsonable(dict(r)) for r in job.result()]
    if not rows or not rows[0]["attested"]:
        return None
    r = rows[0]
    return Receipt(
        receipt_id=r["receipt_id"],
        concept=r["concept"],
        knowledge_version=r["knowledge_version"],
        params=_json(r["params"]) or {},
        job_id=r["job_id"],
        executed_sql=r["executed_sql"],
        result=_json(r["result"]) or [],
        attested=True,
        reason=r["reason"],
        used_by=r["used_by"],
        created_at=r["created_at"],
    )
