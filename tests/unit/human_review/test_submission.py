"""Chat submission writes a real review application; no fake ids, no in-memory cache."""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.agent.orchestration.state import Flow, SessionState
from src.agent.tools.registry import ToolContext
from src.agent.tools.retrieval import StubPolicySearch
from src.agent.tools.stubs import StubData, build_stub_registry
from src.models.knowledge import Product
from src.services.human_review.models import ReviewStatus
from src.services.human_review.store import ReviewStore
from tests.unit.orchestrator.factories import make_verified_app

CONFIG = Path(__file__).resolve().parents[3] / "config" / "orchestrator"
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.fixture
def data():
    return StubData.load(CONFIG)


@pytest.fixture
def store(tmp_path):
    return ReviewStore(tmp_path / "applications.sqlite3")


def ctx_for(data):
    app = make_verified_app(data.requirements[Product.personal_loan])
    app.product_code = Product.personal_loan
    state = SessionState(session_id="session-1", customer_id="cust-001", created_at=NOW, updated_at=NOW,
                         active_flow=Flow.credit_application, application=app)
    return ToolContext(state, NOW)


def submit(registry, ctx, key="session-1:v1"):
    return registry.execute("submit_application", {"application_id": "DRAFT-1", "idempotency_key": key}, ctx, caller="code")


def test_submit_writes_real_application(data, store):
    registry = build_stub_registry(data, StubPolicySearch(CONFIG), review_store=store)
    ctx = ctx_for(data)
    outcome, output = submit(registry, ctx)
    assert outcome.ok and output.simulated is False
    saved = store.get(output.application_id)
    assert saved.customer_id == "cust-001" and saved.status == ReviewStatus.PENDING_HUMAN_REVIEW
    assert saved.snapshot["application"]["fields"]["monthly_net_income"]["value"] == "6200"
    assert saved.snapshot["profile"]["full_name"] == "Ana Popescu"
    assert {d.doc_type for d in saved.documents} == {"id_card", "payslip", "bank_statement"}


def test_repeated_idempotency_key_returns_same_application(data, store):
    registry = build_stub_registry(data, StubPolicySearch(CONFIG), review_store=store)
    ctx = ctx_for(data)
    first, second = submit(registry, ctx)[1], submit(registry, ctx)[1]
    assert first.application_id == second.application_id
    assert len(store.list()) == 1


def test_missing_store_fails_instead_of_inventing_an_id(data):
    registry = build_stub_registry(data, StubPolicySearch(CONFIG))
    outcome, output = submit(registry, ctx_for(data))
    assert not outcome.ok and outcome.error_code == "tool_unavailable" and output is None


def test_status_tool_reads_review_store(data, store):
    registry = build_stub_registry(data, StubPolicySearch(CONFIG), review_store=store)
    ctx = ctx_for(data)
    app_id = submit(registry, ctx)[1].application_id
    ctx.state.application.application_id = app_id
    store.transition(app_id, to=ReviewStatus.MORE_INFORMATION_REQUIRED, actor="reviewer", reason="Newer payslip",
                     expected_version=1, now=NOW, request_doc_type="payslip")
    outcome, output = registry.execute("get_application_status", {}, ctx, caller="model")
    assert outcome.ok and output.status == "MORE_INFORMATION_REQUIRED" and output.simulated is False
    assert [h.status for h in output.history] == ["PENDING_HUMAN_REVIEW", "MORE_INFORMATION_REQUIRED"]
