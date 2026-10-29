"""Test factories for orchestrator unit tests."""
import json
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
    """Return a personal-loan ApplicationState for cust-alex-morgan with every required
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
        "full_name": "Alex Morgan",
        "age": 38,
        "employment_type": "employed",
        "employment_months": 48,
        "monthly_net_income": Decimal("8500"),
        "employer_name": "FICTIV Employer's Studio 1",
        "existing_monthly_obligations": Decimal("0"),
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


def make_collecting_app(requirements: ProductRequirements, customer_values: dict | None = None,
                        now: datetime | None = None):
    """Return an ApplicationState with the product's requirements set, the
    discovery fields, plus `customer_values` (name -> value) as confirmed
    customer-stated fields. No documents, eligibility or offers."""
    from src.agent.orchestration.fields import field_type_to_kind
    from src.agent.orchestration.state import ApplicationState, FieldSource, FieldValue

    now = now or datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    specs = {spec.name: spec for spec in requirements.fields}
    values = {"purpose": ("text", "renovation"), "amount": ("money", Decimal("30000")),
              "term_months": ("integer", 48)}
    for name, value in (customer_values or {}).items():
        values[name] = (field_type_to_kind(specs[name].type), value)
    fields = {
        name: FieldValue(kind=kind, value=value, source=FieldSource.customer, confirmed=True, updated_at=now)
        for name, (kind, value) in values.items()
    }
    return ApplicationState(fields=fields, product_code=requirements.product_code, requirements=requirements)


# ---- scripted model output and session seeding -----------------------------

def respond(message="OK", intent="other", updates=None, citations=None) -> str:
    """A scripted model `respond` action as raw JSON text."""
    return json.dumps({
        "intent": intent,
        "field_updates": updates or [],
        "action": {"type": "respond", "message": message, "citation_ids": citations or []},
    })


def call(tool, arguments=None, intent="credit_application", updates=None) -> str:
    """A scripted model `call_tool` action as raw JSON text."""
    return json.dumps({
        "intent": intent,
        "field_updates": updates or [],
        "action": {"type": "call_tool", "tool": tool, "arguments": arguments or {}},
    })


def spy_tool(registry, name: str, *, fail: Exception | None = None) -> list:
    """Wrap a registered tool's handler; return the list its inputs are recorded in.

    With `fail`, the handler raises it instead of running.
    """
    import dataclasses

    spec = registry.get(name)
    calls: list = []

    def handler(input, ctx):
        calls.append(input)
        if fail is not None:
            raise fail
        return spec.handler(input, ctx)

    registry.register(dataclasses.replace(spec, handler=handler))
    return calls


def seed_application(store, session_id, app, *, active_flow=None) -> None:
    """Put `app` into a stored session, bypassing model turns."""
    from src.agent.orchestration.state import Flow

    state = store.get(session_id)
    state.application = app
    state.active_flow = active_flow or Flow.credit_application
    store.save(state, state.version)
