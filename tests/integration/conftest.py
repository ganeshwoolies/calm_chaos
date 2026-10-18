"""Integration tests that call Gemini run only when asked, because every call is billed.

PSD_GEMINI_TESTS=1 runs them: the drafting workflow (several drafts per run), the agent and server smoke tests, and the
recall trigger end to end. The label-reading and shelf-reading evals have their own switches, PSD_LABEL_EVAL and
PSD_SHELF_EVAL.
"""

import os

import pytest

CALLS_GEMINI = {
    "test_agent.py",
    "test_server_e2e.py",
    "test_workflow_hitl.py",
    "test_recall_trigger.py",
}


def pytest_collection_modifyitems(config, items) -> None:
    if os.environ.get("PSD_GEMINI_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="calls Gemini: set PSD_GEMINI_TESTS=1 to run")
    for item in items:
        if item.path.name in CALLS_GEMINI:
            item.add_marker(skip)
