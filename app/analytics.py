"""BigQuery Agent Analytics: every run's steps, model calls, approval pauses and errors as rows in
PSD_ANALYTICS_DATASET.agent_events, with a view per event type. Off unless the dataset is set.

The rows are the trajectory record behind the operational metrics (tools/ops_report.py) and an incident's history:
an incident's session id is its incident id, so one session_id filter returns its whole run. They are best-effort, not
the audit log: the plugin drops rows when its queue fills or its retries run out, and a retry can write a row twice
(dedupe on event_id). Decisions and executor writes are audited in the desk's own store.
"""

import os

from google.adk.plugins.base_plugin import BasePlugin

from app import bq

DATASET_ENV = "PSD_ANALYTICS_DATASET"
TABLE = "agent_events"


def plugins() -> list[BasePlugin]:
    dataset = os.environ.get(DATASET_ENV)
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not (dataset and project):
        return []
    from google.adk.plugins.bigquery_agent_analytics_plugin import (
        BigQueryAgentAnalyticsPlugin,
        BigQueryLoggerConfig,
    )

    return [
        BigQueryAgentAnalyticsPlugin(
            project_id=project,
            dataset_id=dataset,
            table_id=TABLE,
            location=bq.location(),
            config=BigQueryLoggerConfig(
                # psd-agents runs with CPU only during requests, so rows are written before a run returns rather than
                # left to a background writer that would wait for the next request.
                flush_on_run_end=True,
                event_denylist=[
                    "HITL_CREDENTIAL_REQUEST",
                    "HITL_CREDENTIAL_REQUEST_COMPLETED",
                ],
                max_content_length=50_000,
                log_multi_modal_content=False,
                custom_tags={"service": "psd-agents"},
            ),
        )
    ]
