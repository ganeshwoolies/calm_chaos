"""SQL tests run against live BigQuery: psd_test for the computation's cases, psd for the loaded world's truth.

A test whose dataset does not exist is skipped with the command that creates it. Tests whose SQL calls Gemini through
AI.EMBED or AI.IF are billed per call, so they run only with PSD_GEMINI_TESTS=1.
"""

import os

import pytest
from google.api_core.exceptions import NotFound

from app import bq
from tests.knowledge_copy import copy_bundle


@pytest.fixture(scope="session")
def verified_bundle(tmp_path_factory):
    return copy_bundle(tmp_path_factory.mktemp("bundle") / "knowledge")


@pytest.fixture(autouse=True)
def _knowledge(verified_bundle, monkeypatch):
    monkeypatch.setenv("PSD_KNOWLEDGE_DIR", str(verified_bundle))


def require_table(dataset: str, table: str | None = None) -> None:
    client = bq.client()
    try:
        client.get_dataset(f"{client.project}.{dataset}")
        if table:
            client.get_table(f"{client.project}.{dataset}.{table}")
    except NotFound:
        pytest.skip(
            f"{dataset}{'.' + table if table else ''} does not exist: "
            f"bq --location=us-central1 mk --dataset {client.project}:{dataset}"
            + (", then uv run python data/load_truth.py --dataset psd" if table else "")
        )


CALLS_GEMINI = {"test_match_recalls.py", "test_trigger_sql.py", "test_label_sql.py"}


def pytest_collection_modifyitems(config, items) -> None:
    if os.environ.get("PSD_GEMINI_TESTS") == "1":
        return
    skip = pytest.mark.skip(
        reason="calls Gemini through AI.EMBED or AI.IF: set PSD_GEMINI_TESTS=1 to run"
    )
    for item in items:
        if item.path.name in CALLS_GEMINI:
            item.add_marker(skip)
