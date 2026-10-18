import pytest

from app import policy
from app.evidence import from_fixture
from app.schemas import CustomerMessage, IncidentText
from app.store import store
from tests.knowledge_copy import copy_bundle

YOGHURT = "recall:yoghurt_listeria"
DINOSAUR = "label:P50211:7a0d3f"
MUESLI = "label:P31007:4c19e2"


@pytest.fixture(scope="session")
def verified_bundle(tmp_path_factory):
    """The repository's bundle as a reviewer would leave it, so logic tests do not depend on the review state."""
    return copy_bundle(tmp_path_factory.mktemp("bundle") / "knowledge")


@pytest.fixture(autouse=True)
def _knowledge(verified_bundle, monkeypatch):
    monkeypatch.setenv("PSD_KNOWLEDGE_DIR", str(verified_bundle))
    monkeypatch.setenv("PSD_EVIDENCE_SOURCE", "fixtures")


@pytest.fixture
def pol() -> policy.Policy:
    return policy.current()


@pytest.fixture(autouse=True)
def _clean_store():
    store.reset()
    yield
    store.reset()


@pytest.fixture
def yoghurt():
    return from_fixture(YOGHURT)


@pytest.fixture
def dinosaur():
    return from_fixture(DINOSAUR)


@pytest.fixture
def muesli():
    return from_fixture(MUESLI)


@pytest.fixture
def recall_draft() -> IncidentText:
    return IncidentText(
        title="Morrowdale Vanilla Yoghurt 1kg, batch B2026-091: possible Listeria, 14 stores, 37 online orders",
        narrative="The regulator recalled batch B2026-091. 14 stores hold 212 units.",
        evidence=[
            "14 stores hold the batch (receipt rcpt-fixture-yoghurt-0001)",
            "37 online orders contain it",
        ],
        considerations=[],
        customer_message=CustomerMessage(
            subject="Recall: Morrowdale Vanilla Yoghurt 1kg", body="Do not eat it."
        ),
        supplier_notice="Batch B2026-091 is recalled.",
        vendor_case_body="P48812, batch B2026-091, Listeria, 14 stores.",
        qa_alert="Critical recall of batch B2026-091.",
    )
