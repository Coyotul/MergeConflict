"""Integration tests verifying the ANAF eligibility check wiring in the Orchestrator."""

from datetime import datetime, UTC
from decimal import Decimal
from typing import Any

import pytest

from src.agent.orchestration.state import ApplicationState, FieldValue, FieldSource, SessionState, Flow
from src.agent.tools.registry import ToolContext
from src.agent.tools.stubs import StubData, build_stub_registry
from src.agent.tools.retrieval import build_policy_search
from src.core.settings import OrchestratorSettings
from src.models.credit import EligibilityStatus, Product


@pytest.fixture
def stub_data():
    settings = OrchestratorSettings()
    return StubData.load(settings.config_dir)


@pytest.fixture
def policy_search():
    settings = OrchestratorSettings()
    return build_policy_search(settings)


@pytest.fixture
def registry(stub_data, policy_search):
    return build_stub_registry(stub_data, policy_search)


def make_context(customer_id: str, fields: dict[str, Any], stub_data: StubData) -> ToolContext:
    app_fields = {}
    now = datetime.now(UTC)
    for name, val in fields.items():
        if isinstance(val, Decimal):
            kind = "money"
        elif isinstance(val, int) and not isinstance(val, bool):
            kind = "integer"
        elif isinstance(val, bool):
            kind = "boolean"
        else:
            kind = "text"
        app_fields[name] = FieldValue(kind=kind, value=val, source=FieldSource.customer, confirmed=True, updated_at=now)

    state = SessionState(
        session_id=f"test-session-{customer_id}",
        customer_id=customer_id,
        active_flow=Flow.credit_application,
        created_at=now,
        updated_at=now,
        application=ApplicationState(
            product_code=Product.personal_loan,
            requirements=stub_data.requirements[Product.personal_loan],
            fields=app_fields,
        ),
    )
    return ToolContext(state=state, now=now)


def test_cust_001_queries_real_anaf_and_passes(registry, stub_data):
    ctx = make_context("cust-001", {
        "full_name": "Ana Popescu",
        "age": 34,
        "employment_type": "employed",
        "employment_months": 48,
        "employer_name": "TechCorp SRL",
        "monthly_net_income": Decimal("7000.00"),
        "existing_monthly_obligations": Decimal("400.00"),
        "amount": Decimal("30000.00"),
        "term_months": 60,
    }, stub_data)

    outcome, output = registry.execute("run_eligibility_check", {}, ctx, caller="model")
    assert outcome.ok is True
    assert output.status == EligibilityStatus.satisfied
    assert ctx.state.used_stubs is False

    # Verifies income was retrieved from SQLite ANAF database (5000.33 RON)
    reasons_text = " ".join(r.message for r in output.reasons)
    assert "5000.33" in reasons_text
    assert "ANAF" in reasons_text
    assert "DTI" in reasons_text


def test_cust_002_low_income_returns_not_satisfied(registry, stub_data):
    ctx = make_context("cust-002", {
        "full_name": "Mihai Ionescu",
        "age": 41,
        "employment_type": "employed",
        "employment_months": 24,
        "employer_name": "AutoService SA",
        "monthly_net_income": Decimal("2100.00"),
        "existing_monthly_obligations": Decimal("400.00"),
        "amount": Decimal("30000.00"),
        "term_months": 60,
    }, stub_data)

    outcome, output = registry.execute("run_eligibility_check", {}, ctx, caller="model")
    assert outcome.ok is True
    assert output.status == EligibilityStatus.not_satisfied
    assert ctx.state.used_stubs is False

    reasons_text = " ".join(r.message for r in output.reasons)
    assert "2100" in reasons_text
    assert "2700" in reasons_text


def test_cust_003_pfa_returns_manual_review(registry, stub_data):
    ctx = make_context("cust-003", {
        "full_name": "Elena Dumitru",
        "age": 29,
        "employment_type": "self_employed",
        "employment_months": 36,
        "employer_name": "Dumitru Consulting PFA",
        "monthly_net_income": Decimal("8000.00"),
        "existing_monthly_obligations": Decimal("1000.00"),
        "amount": Decimal("30000.00"),
        "term_months": 60,
    }, stub_data)

    outcome, output = registry.execute("run_eligibility_check", {}, ctx, caller="model")
    assert outcome.ok is True
    assert output.status == EligibilityStatus.manual_review
    assert ctx.state.used_stubs is False

    reasons_text = " ".join(r.message for r in output.reasons)
    assert "manual review" in reasons_text.lower()
    assert "ANAF" in reasons_text or "pfa" in reasons_text.lower()
