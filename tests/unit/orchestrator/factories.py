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


def make_verified_app(requirements: ProductRequirements, now: datetime | None = None):
    """Return a personal-loan ApplicationState for cust-001 with every required
    field present and verified (identity from profile, the rest from accepted,
    confirmed documents) and all required documents accepted.

    Eligibility and offers are not set; run the tools to get them.
    """
    from src.agent.orchestration.fields import field_type_to_kind
    from src.agent.orchestration.state import (
        ApplicationState,
        DocumentRecord,
        DocumentStatus,
        FieldSource,
        FieldValue,
    )

    now = now or datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    values = {
        "purpose": "renovation",
        "amount": Decimal("30000"),
        "term_months": 48,
        "full_name": "Ana Popescu",
        "age": 34,
        "employment_type": "employed",
        "employment_months": 48,
        "monthly_net_income": Decimal("6200"),
        "employer_name": "TechCorp SRL",
        "existing_monthly_obligations": Decimal("400"),
    }
    kinds = {"purpose": "text", "amount": "money", "term_months": "integer"}
    specs = {spec.name: spec for spec in requirements.fields}
    documents = [
        DocumentRecord(
            document_id=f"doc-{d.doc_type}",
            doc_type=d.doc_type,
            filename=f"{d.doc_type}.pdf",
            status=DocumentStatus.accepted,
            uploaded_at=now,
        )
        for d in requirements.documents
    ]
    fields = {}
    for name, value in values.items():
        spec = specs.get(name)
        kind = kinds.get(name) or field_type_to_kind(spec.type)
        if spec is not None and spec.identity:
            fields[name] = FieldValue(kind=kind, value=value, source=FieldSource.profile,
                                      confirmed=True, updated_at=now)
        elif spec is not None and spec.verified_by:
            fields[name] = FieldValue(kind=kind, value=value, source=FieldSource.document,
                                      document_id=f"doc-{spec.verified_by}", confidence=0.95,
                                      confirmed=True, updated_at=now)
        else:
            fields[name] = FieldValue(kind=kind, value=value, source=FieldSource.customer,
                                      confirmed=True, updated_at=now)
    return ApplicationState(
        fields=fields,
        product_code=requirements.product_code,
        requirements=requirements,
        documents=documents,
    )
