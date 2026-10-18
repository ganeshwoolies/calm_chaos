"""Operational metrics from BigQuery Agent Analytics (design section 18): draft latency and Memory Bank retrieval
timeouts over the last days, against their targets. Exits 1 when either misses its target.

    uv run python tools/ops_report.py [--days 7]

Reads PSD_ANALYTICS_DATASET.agent_events, which psd-agents writes when that variable is set (app/analytics.py).
Rows are deduplicated on event_id, since the plugin's retries can write one twice.
"""

import argparse
import os
import sys

from google.cloud import bigquery

from app import analytics, bq

DRAFT_P95_TARGET_MS = 20_000
RETRIEVAL_TIMEOUT_TARGET = 0.02

_EVENTS = """WITH events AS (
  SELECT * FROM `{table}`
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY timestamp) = 1
)"""

DRAFT_SQL = (
    _EVENTS
    + """
SELECT COUNT(*) AS drafts,
  APPROX_QUANTILES(CAST(JSON_VALUE(latency_ms, '$.total_ms') AS FLOAT64), 100)[OFFSET(50)] AS p50_ms,
  APPROX_QUANTILES(CAST(JSON_VALUE(latency_ms, '$.total_ms') AS FLOAT64), 100)[OFFSET(95)] AS p95_ms
FROM events
WHERE event_type = 'LLM_RESPONSE' AND agent IN ('recall_drafter', 'label_drafter')"""
)

RETRIEVAL_SQL = (
    _EVENTS
    + """
SELECT COUNT(*) AS retrievals,
  COUNTIF(JSON_VALUE(attributes, '$.state_delta.observations_timeout') = 'true') AS timeouts
FROM events
WHERE event_type = 'STATE_DELTA' AND JSON_QUERY(attributes, '$.state_delta.observations_timeout') IS NOT NULL"""
)


def report(days: int = 7) -> tuple[list[str], bool]:
    """Lines to print, and whether every metric met its target."""
    dataset = os.environ.get(analytics.DATASET_ENV)
    if not dataset:
        return [f"{analytics.DATASET_ENV} is not set: nothing to read"], False
    table = f"{bq.client().project}.{dataset}.{analytics.TABLE}"
    days_param = [bigquery.ScalarQueryParameter("days", "INT64", days)]
    (draft,) = bq.rows(DRAFT_SQL.format(table=table), days_param)
    (retrieval,) = bq.rows(RETRIEVAL_SQL.format(table=table), days_param)
    lines, ok = [], True
    if draft["drafts"]:
        met = draft["p95_ms"] <= DRAFT_P95_TARGET_MS
        ok &= met
        lines.append(
            f"draft latency over {draft['drafts']} drafts: p50 {draft['p50_ms'] / 1000:.1f} s, "
            f"p95 {draft['p95_ms'] / 1000:.1f} s (target under {DRAFT_P95_TARGET_MS / 1000:.0f} s): "
            + ("met" if met else "MISSED")
        )
    else:
        lines.append(f"no drafts in the last {days} days")
    if retrieval["retrievals"]:
        rate = retrieval["timeouts"] / retrieval["retrievals"]
        met = rate < RETRIEVAL_TIMEOUT_TARGET
        ok &= met
        lines.append(
            f"retrieval timeouts: {retrieval['timeouts']} of {retrieval['retrievals']} ({rate:.1%}, target under "
            f"{RETRIEVAL_TIMEOUT_TARGET:.0%}): " + ("met" if met else "MISSED")
        )
    else:
        lines.append(f"no Memory Bank retrievals in the last {days} days")
    return lines, ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    lines, ok = report(args.days)
    for line in lines:
        print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
