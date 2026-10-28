"""Tests for field parsing and update validation."""
from datetime import datetime, UTC
from decimal import Decimal

import pytest

from src.agent.orchestration.fields import (
    parse_money,
    parse_field_value,
    FieldValueError,
    FieldUpdate,
    apply_field_updates,
    merge_document_extraction,
    DISCOVERY_FIELDS
)
from src.agent.orchestration.state import (
    DocumentRecord,
    DocumentStatus,
    ExtractedField,
    FieldValue,
    FieldSource,
    SessionState,
    Flow
)
from src.models.credit import FieldSpec, FieldType
from src.models.knowledge import Product
from tests.unit.orchestrator.factories import make_specs, make_app


@pytest.mark.parametrize("raw,expected", [
    ("30.000 lei", Decimal("30000")),
    ("30 000 RON", Decimal("30000")),
    ("30,5", Decimal("30.5")),
    ("30k", Decimal("30000")),
    ("1.250,50", Decimal("1250.50")),
    ("1,250.50", Decimal("1250.50")),
    (25000, Decimal("25000")),
    ("5200.75", Decimal("5200.75")),
    ("5 200,75", Decimal("5200.75")),
    ("1.500", Decimal("1500")),  # Ambiguous, but treated as thousands separator
    ("100", Decimal("100")),
    ("100.00", Decimal("100")),
])
def test_parse_money_formats(raw, expected):
    """Test parse_money handles various Romanian and standard formats."""
    assert parse_money(raw) == expected


def test_parse_money_rejects_garbage():
    """Test parse_money rejects invalid input."""
    with pytest.raises(FieldValueError):
        parse_money("about thirty")


def test_amount_out_of_range_rejected():
    """Test that amount outside min/max is rejected."""
    specs = make_specs()
    app = make_app()
    now = datetime.now(UTC)

    updates = [FieldUpdate(field="amount", value="500")]  # Below min of 1000
    results = apply_field_updates(app, updates, specs, offer_ids=set(), now=now)

    assert len(results) == 1
    assert results[0].accepted is False
    assert results[0].reason is not None
    assert "invalid_value" in results[0].reason
    assert "amount" not in app.fields


def test_unknown_field_rejected():
    """Test that unknown field name is rejected."""
    specs = make_specs()
    app = make_app()
    now = datetime.now(UTC)

    updates = [FieldUpdate(field="nonexistent_field", value="test")]
    results = apply_field_updates(app, updates, specs, offer_ids=set(), now=now)

    assert len(results) == 1
    assert results[0].accepted is False
    assert results[0].reason == "unknown_field"
    assert "nonexistent_field" not in app.fields


def test_unknown_product_and_offer_rejected():
    """Test that unknown product_code and offer_id are rejected."""
    specs = make_specs()
    # Add product_code spec with catalog options
    specs["product_code"] = FieldSpec(
        name="product_code",
        label="Product",
        type=FieldType.enum,
        options=["personal_loan", "mortgage_casa_ta"]
    )
    app = make_app()
    now = datetime.now(UTC)

    # Test unknown product
    updates = [FieldUpdate(field="product_code", value="unknown_product")]
    results = apply_field_updates(app, updates, specs, offer_ids=set(), now=now)
    assert len(results) == 1
    assert results[0].accepted is False
    assert results[0].reason == "unknown_product"

    # Test unknown offer
    updates = [FieldUpdate(field="selected_offer_id", value="offer-999")]
    results = apply_field_updates(app, updates, specs, offer_ids={"offer-1", "offer-2"}, now=now)
    assert len(results) == 1
    assert results[0].accepted is False
    assert results[0].reason == "unknown_offer"


def test_product_change_clears_downstream():
    """Test that changing product_code clears downstream state."""
    from src.models.credit import EligibilityResult, EligibilityStatus, LoanOffer, Money
    from src.agent.orchestration.state import EligibilityRecord, OffersRecord

    specs = make_specs()
    specs["product_code"] = FieldSpec(
        name="product_code",
        label="Product",
        type=FieldType.enum,
        options=["personal_loan", "mortgage_casa_ta"]
    )

    # Start with an app that has everything set
    app = make_app(
        product_code=Product.personal_loan,
        eligibility=EligibilityRecord(
            result=EligibilityResult(
                status=EligibilityStatus.satisfied,
                reasons=[],
                rule_version="1.0"
            ),
            input_fingerprint="hash123",
            verified_inputs=True
        ),
        offers=OffersRecord(
            offers=[
                LoanOffer(
                    offer_id="offer-1",
                    product_code=Product.personal_loan,
                    amount=Money(amount=Decimal("30000")),
                    term_months=48,
                    annual_interest_rate_percent=Decimal("8.5"),
                    monthly_installment=Money(amount=Decimal("740")),
                    total_repayment=Money(amount=Decimal("35520")),
                    total_cost=Money(amount=Decimal("5520")),
                    fees=Money(amount=Decimal("0")),
                    assumptions=["Good credit history"],
                    indicative=True,
                    simulated=True
                )
            ],
            input_fingerprint="hash456"
        ),
        selected_offer_id="offer-1"
    )
    app.fields["amount"] = FieldValue(
        value=Decimal("30000"),
        source=FieldSource.customer,
        confirmed=True,
        updated_at=datetime.now(UTC)
    )

    now = datetime.now(UTC)
    updates = [FieldUpdate(field="product_code", value="mortgage_casa_ta")]
    results = apply_field_updates(app, updates, specs, offer_ids=set(), now=now)

    assert len(results) == 1
    assert results[0].accepted is True
    assert app.product_code == Product.mortgage_casa_ta
    assert app.eligibility is None
    assert app.offers is None
    assert app.selected_offer_id is None
    # Fields should be kept
    assert "amount" in app.fields


def test_document_conflict_detected_and_resolved_by_confirm():
    """Test that document extraction creates a conflict and confirm resolves it."""
    specs = make_specs()
    app = make_app()
    now = datetime.now(UTC)

    # Customer states income of 6000
    updates = [FieldUpdate(field="monthly_net_income", value="6000")]
    results = apply_field_updates(app, updates, specs, offer_ids=set(), now=now)
    assert results[0].accepted is True
    assert app.fields["monthly_net_income"].value == Decimal("6000")
    assert app.fields["monthly_net_income"].source == FieldSource.customer
    assert app.fields["monthly_net_income"].confirmed is True

    # Document extraction shows 5200
    doc = DocumentRecord(
        document_id="doc-1",
        doc_type="payslip",
        filename="payslip.pdf",
        status=DocumentStatus.accepted,
        rejection_reason=None,
        extracted_fields={
            "monthly_net_income": ExtractedField(
                value="5200",
                confidence=0.95,
                location="page 1"
            )
        },
        uploaded_at=now
    )
    merge_document_extraction(app, doc, specs, now=now)

    # Should create conflict
    assert len(app.conflicts) == 1
    assert app.conflicts[0].field == "monthly_net_income"
    assert app.conflicts[0].customer_value == "6000"
    assert app.conflicts[0].document_value == "5200"
    assert app.conflicts[0].document_id == "doc-1"

    # Field should have document value, unconfirmed
    assert app.fields["monthly_net_income"].value == Decimal("5200")
    assert app.fields["monthly_net_income"].source == FieldSource.document
    assert app.fields["monthly_net_income"].confirmed is False
    assert app.fields["monthly_net_income"].confidence == 0.95

    # Confirm accepts document value and removes conflict
    updates = [FieldUpdate(field="monthly_net_income", confirm=True)]
    results = apply_field_updates(app, updates, specs, offer_ids=set(), now=now)
    assert results[0].accepted is True
    assert app.fields["monthly_net_income"].confirmed is True
    assert len(app.conflicts) == 0


def test_customer_cannot_override_verified_value():
    """Test that customer cannot override a verified document value."""
    specs = make_specs()
    app = make_app()
    now = datetime.now(UTC)

    # Document extraction provides income
    doc = DocumentRecord(
        document_id="doc-1",
        doc_type="payslip",
        filename="payslip.pdf",
        status=DocumentStatus.accepted,
        rejection_reason=None,
        extracted_fields={
            "monthly_net_income": ExtractedField(
                value="5200",
                confidence=0.95,
                location="page 1"
            )
        },
        uploaded_at=now
    )
    merge_document_extraction(app, doc, specs, now=now)

    # Field is now from document
    assert app.fields["monthly_net_income"].source == FieldSource.document

    # Customer tries to change it
    updates = [FieldUpdate(field="monthly_net_income", value="7000")]
    results = apply_field_updates(app, updates, specs, offer_ids=set(), now=now)

    assert len(results) == 1
    assert results[0].accepted is False
    assert results[0].reason == "must_verify_from_document"
    # Field should remain unchanged
    assert app.fields["monthly_net_income"].value == Decimal("5200")


def test_reupload_matching_customer_value_clears_conflict():
    """Test that re-uploading a document with customer's value clears the conflict."""
    specs = make_specs()
    app = make_app()
    now = datetime.now(UTC)

    # Customer states income
    updates = [FieldUpdate(field="monthly_net_income", value="6000")]
    apply_field_updates(app, updates, specs, offer_ids=set(), now=now)

    # First document has different value
    doc1 = DocumentRecord(
        document_id="doc-1",
        doc_type="payslip",
        filename="payslip_old.pdf",
        status=DocumentStatus.accepted,
        rejection_reason=None,
        extracted_fields={
            "monthly_net_income": ExtractedField(value="5200", confidence=0.95)
        },
        uploaded_at=now
    )
    merge_document_extraction(app, doc1, specs, now=now)
    assert len(app.conflicts) == 1

    # Re-upload with customer's value
    doc2 = DocumentRecord(
        document_id="doc-2",
        doc_type="payslip",
        filename="payslip_new.pdf",
        status=DocumentStatus.accepted,
        rejection_reason=None,
        extracted_fields={
            "monthly_net_income": ExtractedField(value="6000", confidence=0.96)
        },
        uploaded_at=now
    )
    merge_document_extraction(app, doc2, specs, now=now)

    # Conflict should be cleared
    assert len(app.conflicts) == 0
    assert app.fields["monthly_net_income"].value == Decimal("6000")


def test_locked_after_submission():
    """Test that field updates are rejected after submission."""
    specs = make_specs()
    app = make_app(
        application_id="APP123",
        submitted_at=datetime.now(UTC)
    )
    now = datetime.now(UTC)

    updates = [FieldUpdate(field="amount", value="50000")]
    results = apply_field_updates(app, updates, specs, offer_ids=set(), now=now)

    assert len(results) == 1
    assert results[0].accepted is False
    assert results[0].reason == "application_locked"


def test_session_state_json_round_trip():
    """Test that SessionState with nested models round-trips through JSON."""
    from src.models.credit import EligibilityResult, EligibilityStatus
    from src.agent.orchestration.state import (
        ApplicationState,
        EligibilityRecord,
        SessionState
    )
    from src.models.chat import CitationRef
    from datetime import date

    now = datetime.now(UTC)

    # Create a session with nested state
    session = SessionState(
        session_id="sess-123",
        customer_id="cust-456",
        created_at=now,
        updated_at=now,
        version=1,
        language="ro",
        active_flow=Flow.credit_application,
        application=ApplicationState(
            fields={
                "amount": FieldValue(
                    value=Decimal("30000"),
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                )
            },
            product_code=Product.personal_loan,
            requirements=None,
            documents=[],
            conflicts=[],
            eligibility=EligibilityRecord(
                result=EligibilityResult(
                    status=EligibilityStatus.satisfied,
                    reasons=[],
                    rule_version="1.0"
                ),
                input_fingerprint="hash123",
                verified_inputs=False
            ),
            offers=None,
            selected_offer_id=None,
            draft_application_id=None,
            summary=None,
            application_id=None,
            submitted_at=None,
            idempotency_key=None
        ),
        retrieved_sources={
            "c1": CitationRef(
                id="c1",
                publisher="Test Bank",
                title="Test Doc",
                url="https://example.com",
                section="Section 1",
                effective_date=date(2026, 1, 1)
            )
        },
        escalation=None,
        used_stubs=False
    )

    # Round-trip through JSON
    json_str = session.model_dump_json()
    restored = SessionState.model_validate_json(json_str)

    # Verify key fields
    assert restored.session_id == session.session_id
    assert restored.application.fields["amount"].value == Decimal("30000")
    assert restored.application.eligibility.result.status == EligibilityStatus.satisfied
    assert "c1" in restored.retrieved_sources


def test_discovery_fields_defined():
    """Test that DISCOVERY_FIELDS contains the expected fields."""
    assert len(DISCOVERY_FIELDS) == 3
    field_names = {f.name for f in DISCOVERY_FIELDS}
    assert field_names == {"purpose", "amount", "term_months"}

    # Check types
    amount_field = next(f for f in DISCOVERY_FIELDS if f.name == "amount")
    assert amount_field.type == FieldType.money
    assert amount_field.min == Decimal("1000")
    assert amount_field.max == Decimal("1000000")
