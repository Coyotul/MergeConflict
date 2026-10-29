"""The nine demo customers through the real eligibility and profile tools over a fresh SQLite DB."""
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from scripts.credit_sources.setup import create_database
from src.agent.orchestration.state import FieldSource, FieldValue, Flow, SessionState
from src.agent.tools.registry import ToolContext
from src.agent.tools.retrieval import StubPolicySearch
from src.agent.tools.stubs import StubData
from src.core.composition import build_registry
from src.core.settings import OrchestratorSettings
from src.models.credit import EligibilityStatus
from src.models.knowledge import Product
from tests.unit.orchestrator.factories import make_app

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config" / "orchestrator"
REQUIREMENTS = StubData.load(CONFIG_DIR).requirements[Product.personal_loan]
CUSTOMERS = yaml.safe_load((CONFIG_DIR / "customers.yaml").read_text(encoding="utf-8"))["customers"]
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

EXPECTED = {
    "cust-alex-morgan": EligibilityStatus.satisfied,
    "cust-elena-popa": EligibilityStatus.satisfied,
    "cust-radu-mihai": EligibilityStatus.satisfied,
    "cust-dan-ionescu": EligibilityStatus.not_satisfied,
    "cust-andrei-stan": EligibilityStatus.not_satisfied,
    "cust-ioana-marin": EligibilityStatus.not_satisfied,
    "cust-victor-dobre": EligibilityStatus.not_satisfied,
    "cust-maria-stoica": EligibilityStatus.manual_review,
    "cust-mihai-ilie": EligibilityStatus.manual_review,
}


@pytest.fixture(scope="session")
def credit_db():
    """Worktree-local temp dir (the system pytest temp root is not writable here)."""
    path = Path(__file__).parent / ".test_tmp_credit" / uuid4().hex
    path.mkdir(parents=True)
    yield create_database(path / "credit_sources.db")
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="session")
def registry(credit_db):
    settings = OrchestratorSettings(model="fake", config_dir=CONFIG_DIR, credit_sources_db=credit_db,
                                    customer_bindings_path=CONFIG_DIR / "customer_bindings.yaml")
    return build_registry(settings, StubData.load(CONFIG_DIR), StubPolicySearch(CONFIG_DIR))


def field(kind, value, source=FieldSource.document):
    return FieldValue(kind=kind, value=value, source=source, confirmed=True, updated_at=NOW)


def make_state(customer_id: str, with_fields: bool = True) -> SessionState:
    cust = CUSTOMERS.get(customer_id)
    fields = {}
    if with_fields:
        docs, stated = cust["documents"], cust["stated"]
        fields = {
            "full_name": field("text", docs["id_card"]["full_name"]),
            "age": field("integer", docs["id_card"]["age"]),
            "employment_type": field("text", stated["employment_type"], FieldSource.customer),
            "employment_months": field("integer", stated["employment_months"], FieldSource.customer),
            "monthly_net_income": field("money", Decimal(str(docs["payslip"]["monthly_net_income"]))),
            "employer_name": field("text", docs["payslip"]["employer_name"]),
            "existing_monthly_obligations": field(
                "money", Decimal(str(docs["bank_statement"]["existing_monthly_obligations"]))),
            "amount": field("money", Decimal("30000"), FieldSource.customer),
            "term_months": field("integer", 60, FieldSource.customer),
        }
    app = make_app(product_code=Product.personal_loan, requirements=REQUIREMENTS, fields=fields)
    return SessionState(session_id="s", customer_id=customer_id, created_at=NOW, updated_at=NOW,
                        active_flow=Flow.credit_application, application=app)


@pytest.mark.parametrize("customer_id", list(EXPECTED))
def test_demo_customer_eligibility(registry, customer_id):
    state = make_state(customer_id)
    outcome, result = registry.execute("run_eligibility_check", {}, ToolContext(state=state, now=NOW), caller="model")
    assert outcome.ok, outcome
    assert result.status == EXPECTED[customer_id], [r.code for r in result.reasons]
    assert result.simulated is True
    assert state.used_stubs is True
    if customer_id == "cust-radu-mihai":
        assert "income_gap" in {r.code for r in result.reasons}


@pytest.mark.parametrize("customer_id", list(EXPECTED))
def test_demo_customer_profile_from_dataset(registry, customer_id):
    state = make_state(customer_id, with_fields=False)
    outcome, profile = registry.execute("get_customer_profile", {}, ToolContext(state=state, now=NOW), caller="model")
    assert outcome.ok, outcome
    assert profile.full_name == CUSTOMERS[customer_id]["profile"]["full_name"]
    assert profile.age == CUSTOMERS[customer_id]["profile"]["age"]


def test_unbound_customer_profile_fails_cleanly(registry):
    state = make_state("cust-001", with_fields=False)
    outcome, _ = registry.execute("get_customer_profile", {}, ToolContext(state=state, now=NOW), caller="model")
    assert not outcome.ok
    assert outcome.error_code == "tool_failed"
