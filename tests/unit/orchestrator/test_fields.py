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
    FieldConflict,
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
    ("30k lei", Decimal("30000")),
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


@pytest.mark.parametrize("invalid_value", ["nan", "inf", "1e5", "-inf", "infinity"])
def test_parse_money_rejects_special_floats(invalid_value):
    """Test parse_money rejects special float values like nan, inf, and scientific notation."""
    with pytest.raises(FieldValueError):
        parse_money(invalid_value)


def test_field_update_with_nan_gives_invalid_value():
    """Test that FieldUpdate with 'nan' returns invalid_value reason, not exception."""
    specs = make_specs()
    app = make_app()
    now = datetime.now(UTC)

    updates = [FieldUpdate(field="amount", value="nan")]
    results = apply_field_updates(app, updates, specs, offer_ids=set(), now=now)

    assert len(results) == 1
    assert results[0].accepted is False
    assert results[0].reason is not None
    assert "invalid_value" in results[0].reason
    assert "amount" not in app.fields


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
        kind="money",
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
    app.documents.append(doc)  # Add to documents list
    merge_document_extraction(app, doc, specs, now=now)

    # Should create conflict
    assert len(app.conflicts) == 1
    assert app.conflicts[0].field == "monthly_net_income"
    assert app.conflicts[0].customer_value == "6000.00"
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
    app.documents.append(doc)  # Add to documents list
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
    app.documents.append(doc1)  # Add to documents list
    merge_document_extraction(app, doc1, specs, now=now)
    assert len(app.conflicts) == 1
    assert app.conflicts[0].customer_value == "6000.00"
    assert app.conflicts[0].document_value == "5200"

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
    app.documents.append(doc2)  # Add to documents list
    merge_document_extraction(app, doc2, specs, now=now)

    # Conflict should be cleared because new extraction matches customer value
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


def test_conflicts_not_wiped_across_doc_types():
    """Test that merging a document doesn't wipe conflicts from other document types."""
    specs = make_specs()
    # Add id_card verified field
    specs["full_name"] = FieldSpec(
        name="full_name",
        label="Full Name",
        type=FieldType.text,
        required=True,
        verified_by="id_card"
    )
    app = make_app()
    now = datetime.now(UTC)

    # Customer states values for both fields
    updates = [
        FieldUpdate(field="monthly_net_income", value="6000"),
        FieldUpdate(field="full_name", value="John Doe")
    ]
    apply_field_updates(app, updates, specs, offer_ids=set(), now=now)

    # ID card doc creates conflict on full_name
    id_card = DocumentRecord(
        document_id="id-1",
        doc_type="id_card",
        filename="id.pdf",
        status=DocumentStatus.accepted,
        rejection_reason=None,
        extracted_fields={
            "full_name": ExtractedField(value="Jane Doe", confidence=0.98)
        },
        uploaded_at=now
    )
    app.documents.append(id_card)
    merge_document_extraction(app, id_card, specs, now=now)
    assert len(app.conflicts) == 1
    assert app.conflicts[0].field == "full_name"

    # Payslip doc creates conflict on monthly_net_income
    payslip = DocumentRecord(
        document_id="pay-1",
        doc_type="payslip",
        filename="payslip.pdf",
        status=DocumentStatus.accepted,
        rejection_reason=None,
        extracted_fields={
            "monthly_net_income": ExtractedField(value="5200", confidence=0.95)
        },
        uploaded_at=now
    )
    app.documents.append(payslip)
    merge_document_extraction(app, payslip, specs, now=now)

    # Should now have both conflicts (payslip merge shouldn't wipe id_card conflict)
    assert len(app.conflicts) == 2
    conflict_fields = {c.field for c in app.conflicts}
    assert conflict_fields == {"full_name", "monthly_net_income"}


def test_session_state_json_round_trip():
    """Test that SessionState with all nested models round-trips through JSON exactly."""
    from src.models.credit import (
        EligibilityResult, EligibilityStatus, LoanOffer, Money,
        ProductRequirements, FieldSpec, FieldType, DocumentRequirement, ReasonItem
    )
    from src.agent.orchestration.state import (
        ApplicationState, EligibilityRecord, OffersRecord, EscalationRecord,
        SessionState, StoredMessage
    )
    from src.models.chat import CitationRef, ApplicationSummary, SummaryField, DocumentChecklistItem
    from datetime import date

    now = datetime.now(UTC)

    # Create a session with ALL nested models populated
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
                    kind="money",
                    value=Decimal("30000"),
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                ),
                "dependents": FieldValue(
                    kind="integer",
                    value=2,
                    source=FieldSource.customer,
                    confirmed=True,
                    updated_at=now
                ),
                "employer_name": FieldValue(
                    kind="text",
                    value="ACME Corp",
                    source=FieldSource.document,
                    document_id="doc-1",
                    confidence=0.95,
                    confirmed=False,
                    updated_at=now
                )
            },
            product_code=Product.personal_loan,
            requirements=ProductRequirements(
                product_code=Product.personal_loan,
                fields=[
                    FieldSpec(
                        name="monthly_net_income",
                        label="Monthly Net Income",
                        type=FieldType.money,
                        required=True,
                        verified_by="payslip"
                    )
                ],
                documents=[
                    DocumentRequirement(doc_type="payslip", label="Payslip")
                ]
            ),
            documents=[
                DocumentRecord(
                    document_id="doc-1",
                    doc_type="payslip",
                    filename="payslip.pdf",
                    status=DocumentStatus.accepted,
                    rejection_reason=None,
                    extracted_fields={
                        "employer_name": ExtractedField(
                            value="ACME Corp",
                            confidence=0.95,
                            location="page 1"
                        )
                    },
                    uploaded_at=now
                )
            ],
            conflicts=[
                FieldConflict(
                    field="monthly_net_income",
                    customer_value="6000",
                    document_value="5200",
                    document_id="doc-1"
                )
            ],
            eligibility=EligibilityRecord(
                result=EligibilityResult(
                    status=EligibilityStatus.satisfied,
                    reasons=[
                        ReasonItem(code="INCOME_OK", message="Sufficient income")
                    ],
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
                        monthly_installment=Money(amount=Decimal("740.50")),
                        total_repayment=Money(amount=Decimal("35544")),
                        total_cost=Money(amount=Decimal("5544")),
                        fees=Money(amount=Decimal("150")),
                        assumptions=["Good credit history"],
                        indicative=True,
                        simulated=True
                    )
                ],
                input_fingerprint="hash456"
            ),
            selected_offer_id="offer-1",
            draft_application_id="draft-123",
            summary=ApplicationSummary(
                summary_version="v1",
                application_id="draft-123",
                product_code=Product.personal_loan,
                product_name="Personal Loan",
                amount=Money(amount=Decimal("30000")),
                term_months=48,
                offer=LoanOffer(
                    offer_id="offer-1",
                    product_code=Product.personal_loan,
                    amount=Money(amount=Decimal("30000")),
                    term_months=48,
                    annual_interest_rate_percent=Decimal("8.5"),
                    monthly_installment=Money(amount=Decimal("740.50")),
                    total_repayment=Money(amount=Decimal("35544")),
                    total_cost=Money(amount=Decimal("5544")),
                    fees=Money(amount=Decimal("150")),
                    assumptions=["Good credit history"],
                    indicative=True,
                    simulated=True
                ),
                fields=[
                    SummaryField(label="Amount", value="30000 RON", source="customer")
                ],
                documents=[
                    DocumentChecklistItem(
                        doc_type="payslip",
                        label="Payslip",
                        status="accepted",
                        rejection_reason=None
                    )
                ]
            ),
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
        escalation=EscalationRecord(
            reason="Complex case",
            created_at=now
        ),
        used_stubs=True
    )

    # Round-trip through JSON
    json_str = session.model_dump_json()
    restored = SessionState.model_validate_json(json_str)

    # Full equality check
    assert restored == session


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


def test_field_type_to_kind_maps_enum_to_text():
    """enum is a FieldType but not a FieldValue kind; enum values are stored as text."""
    from src.agent.orchestration.fields import field_type_to_kind

    assert field_type_to_kind(FieldType.money) == "money"
    assert field_type_to_kind(FieldType.integer) == "integer"
    assert field_type_to_kind(FieldType.text) == "text"
    assert field_type_to_kind(FieldType.boolean) == "boolean"
    assert field_type_to_kind(FieldType.enum) == "text"


def test_enum_field_update_accepted():
    app = make_app()
    results = apply_field_updates(
        app,
        [FieldUpdate(field="employment_type", value="Employed")],
        make_specs(),
        offer_ids=set(),
        now=datetime.now(UTC),
    )
    assert results[0].accepted
    assert app.fields["employment_type"].value == "employed"
    assert app.fields["employment_type"].kind == "text"


_TERM_SPEC = FieldSpec(
    name="term_months", label="Term (months)", type=FieldType.integer,
    required=True, min=Decimal("6"), max=Decimal("360"),
)


@pytest.mark.parametrize("raw,expected", [
    ("60", 60),
    (60, 60),
    (" 60 ", 60),
    ("60 luni", 60),
    ("60 de luni", 60),
    ("60 months", 60),
    ("12 month", 12),
    ("12 lună", 12),
    ("12 luna", 12),
    ("5 ani", 60),
    ("1 an", 12),
    ("5 years", 60),
    ("1 year", 12),
    ("60.0", 60),
    (60.0, 60),
])
def test_parse_integer_accepts_numbers_with_unit_words(raw, expected):
    """Integer fields accept one whole number with an optional month/year unit word."""
    value = parse_field_value(_TERM_SPEC, raw)
    assert value == expected
    assert type(value) is int


@pytest.mark.parametrize("raw", [True, False, "60.7", 60.7, "60 si 12", "sixty", "60 zile", ""])
def test_parse_integer_rejects_bools_fractions_and_garbage(raw):
    """Integer fields reject bools, non-whole numbers and unparseable text."""
    with pytest.raises(FieldValueError):
        parse_field_value(_TERM_SPEC, raw)


def test_parse_integer_year_unit_on_non_month_field_keeps_number():
    """'34 ani' for age is 34 (not 408); a month unit on a non-month field is rejected."""
    age = FieldSpec(name="age", label="Age", type=FieldType.integer, min=Decimal("18"), max=Decimal("100"))
    assert parse_field_value(age, "34 ani") == 34
    assert parse_field_value(age, "34 years") == 34
    assert parse_field_value(age, "34") == 34
    with pytest.raises(FieldValueError):
        parse_field_value(age, "34 luni")


@pytest.mark.parametrize("raw,expected", [
    ("6200.555", Decimal("6200.56")),
    ("6200,555", Decimal("6200.56")),
    ("1250.505", Decimal("1250.51")),
    ("30.000", Decimal("30000")),
    ("1.250", Decimal("1250")),
    ("1,250", Decimal("1250")),
    ("10.005", Decimal("10005")),
    ("6200 lei net", Decimal("6200")),
    ("6200 RON net", Decimal("6200")),
])
def test_parse_money_thousands_vs_decimals_and_rounding(raw, expected):
    """A lone separator + 3 digits is thousands only after a 1-3 digit integer part; results quantize to 0.01."""
    value = parse_money(raw)
    assert value == expected
    assert value.as_tuple().exponent == -2


def test_parse_money_quantizes_half_up():
    """Money is rounded ROUND_HALF_UP to two decimals for every input type."""
    assert parse_money(Decimal("10.005")) == Decimal("10.01")
    assert parse_money("10,005.5") == Decimal("10005.50")
    assert parse_money(25000).as_tuple().exponent == -2
