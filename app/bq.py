"""BigQuery access for the desk: one client, the dataset the desk reads and writes, and the region it runs in.

The project and dataset come from the environment (GOOGLE_CLOUD_PROJECT, PSD_DATASET), never from SQL text: queries name
tables without a dataset and run with the desk's dataset as their default.
"""

import os
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from functools import cache
from typing import Any

from google.cloud import bigquery

# BigQuery refuses a query that would bill more than this, before running it. It bills at least 10 MB for every table a
# query reads, so recall lineage's five tables bill 50 MB however little they scan: the cap cannot go below that.
MAX_BYTES_BILLED = 100 * 1024 * 1024


def dataset() -> str:
    return os.environ.get("PSD_DATASET", "psd")


def location() -> str:
    return os.environ.get("PSD_REGION", "us-central1")


@cache
def client() -> bigquery.Client:
    return bigquery.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)


def table_ref(name: str, bq: bigquery.Client | None = None) -> str:
    return f"{(bq or client()).project}.{dataset()}.{name}"


def job_config(
    parameters: Iterable[Any] = (),
    labels: dict[str, str] | None = None,
    bq: bigquery.Client | None = None,
) -> bigquery.QueryJobConfig:
    return bigquery.QueryJobConfig(
        default_dataset=f"{(bq or client()).project}.{dataset()}",
        query_parameters=list(parameters),
        maximum_bytes_billed=MAX_BYTES_BILLED,
        labels=labels or {},
    )


def jsonable(value: Any) -> Any:
    """Row values as JSON types: timestamps and dates as ISO strings, NUMERIC as a string."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return value


def rows(sql: str, parameters: Iterable[Any] = ()) -> list[dict[str, Any]]:
    job = client().query(sql, job_config=job_config(parameters), location=location())
    return [jsonable(dict(r)) for r in job.result()]
