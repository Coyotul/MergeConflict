"""Test factories for orchestrator unit tests."""
from datetime import datetime, UTC
from decimal import Decimal

from src.models.credit import FieldSpec, FieldType, ProductRequirements
from src.models.knowledge import Product


def make_specs() -> dict[str, FieldSpec]:
    """Return a dict of FieldSpec for a personal-loan-like requirement set."""
    return {
        "monthly_net_income": FieldSpec(
            name="monthly_net_income",
            label="Monthly Net Income",
            type=FieldType.money,
            required=True,
            verified_by="payslip",
            min=Decimal("1000"),
            max=Decimal("100000")
        ),
        "employer_name": FieldSpec(
            name="employer_name",
            label="Employer Name",
            type=FieldType.text,
            required=True,
            verified_by="payslip"
        ),
        "dependents": FieldSpec(
            name="dependents",
            label="Number of Dependents",
            type=FieldType.integer,
            required=True,
            min=Decimal("0"),
            max=Decimal("10")
        ),
        "employment_type": FieldSpec(
            name="employment_type",
            label="Employment Type",
            type=FieldType.enum,
            required=True,
            options=["employed", "self_employed", "retired"]
        ),
        "purpose": FieldSpec(
            name="purpose",
            label="Purpose",
            type=FieldType.text,
            required=True
        ),
        "amount": FieldSpec(
            name="amount",
            label="Amount",
            type=FieldType.money,
            required=True,
            min=Decimal("1000"),
            max=Decimal("1000000")
        ),
        "term_months": FieldSpec(
            name="term_months",
            label="Term (months)",
            type=FieldType.integer,
            required=True,
            min=Decimal("6"),
            max=Decimal("360")
        )
    }


def make_app(**overrides):
    """Return an ApplicationState with reasonable defaults.

    Pass keyword arguments to override any field, e.g.:
        make_app(product_code=Product.personal_loan, application_id="APP123")
    """
    from src.agent.orchestration.state import ApplicationState

    defaults = {
        "fields": {},
        "product_code": None,
        "requirements": None,
        "documents": [],
        "conflicts": [],
        "eligibility": None,
        "offers": None,
        "selected_offer_id": None,
        "draft_application_id": None,
        "summary": None,
        "application_id": None,
        "submitted_at": None,
        "idempotency_key": None
    }
    defaults.update(overrides)
    return ApplicationState(**defaults)
