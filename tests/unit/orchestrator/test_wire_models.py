"""Tests for credit and chat wire models."""
import pytest
from decimal import Decimal
from datetime import datetime, date
from pydantic import ValidationError

from src.models.credit import (
    Money, FieldType, FieldSpec, CreditProduct, ProductRequirements,
    DocumentRequirement, ReasonItem, EligibilityStatus, EligibilityResult,
    LoanOffer
)
from src.models.chat import (
    CitationRef, ChatMessageView, AwaitingKind, Awaiting, StepStatus,
    ProgressStep, Progress, DocumentChecklistBlock, DocumentChecklistItem,
    ExtractedFieldsBlock, ExtractedFieldView, EligibilityResultBlock,
    OffersBlock, ApplicationSummaryBlock, ApplicationSummary,
    ApplicationSubmittedBlock, EscalationBlock, SummaryField,
    TurnResponse, SessionView, SendMessageRequest, OfferSelectionRequest,
    ConfirmationRequest, ErrorBody, Block
)
from src.models.knowledge import Product


def test_money_quantizes_and_serializes_as_string():
    """Money quantizes to 2 decimals and serializes amount as string."""
    m = Money(amount=Decimal("630.055"))
    assert m.amount == Decimal("630.06")
    assert m.model_dump(mode="json") == {"amount": "630.06", "currency": "RON"}


def test_block_union_round_trips_by_type():
    """Block discriminated union preserves type through JSON round-trip."""
    offer = LoanOffer(
        offer_id="offer_1",
        product_code=Product.personal_loan,
        amount=Money(amount=Decimal("10000")),
        term_months=24,
        annual_interest_rate_percent=Decimal("9.5"),
        monthly_installment=Money(amount=Decimal("456.20")),
        total_repayment=Money(amount=Decimal("10948.80")),
        total_cost=Money(amount=Decimal("948.80")),
        fees=Money(amount=Decimal("100")),
        assumptions=["Income verified", "No late payments"],
        indicative=True,
        simulated=True
    )

    resp = TurnResponse(
        session_id="sess_123",
        turn_id="turn_456",
        session_version=1,
        messages=[
            ChatMessageView(
                role="assistant",
                text="Here is your offer",
                citations=[],
                created_at=datetime(2026, 10, 28, 12, 0, 0)
            )
        ],
        awaiting=Awaiting(kind=AwaitingKind.offer_choice),
        progress=Progress(flow="credit_application", stage="offers", steps=[]),
        blocks=[OffersBlock(offers=[offer], selected_offer_id=None)],
        simulated=True
    )

    again = TurnResponse.model_validate_json(resp.model_dump_json())
    assert isinstance(again.blocks[0], OffersBlock)


def test_send_message_rejects_blank_and_too_long():
    """SendMessageRequest validates text length."""
    with pytest.raises(ValidationError):
        SendMessageRequest(text="   ")
    with pytest.raises(ValidationError):
        SendMessageRequest(text="x" * 4001)


def test_field_spec_must_verify():
    """FieldSpec.must_verify returns True when verified_by is set."""
    spec = FieldSpec(
        name="monthly_net_income",
        label="Net income",
        type=FieldType.money,
        verified_by="payslip"
    )
    assert spec.must_verify


def test_money_default_currency():
    """Money defaults to RON currency."""
    m = Money(amount=Decimal("1000"))
    assert m.currency == "RON"


def test_money_eur_currency():
    """Money accepts EUR currency."""
    m = Money(amount=Decimal("1000"), currency="EUR")
    assert m.currency == "EUR"


def test_field_spec_without_verified_by():
    """FieldSpec.must_verify returns False when verified_by is None."""
    spec = FieldSpec(
        name="purpose",
        label="Loan purpose",
        type=FieldType.enum,
        options=["home_renovation", "debt_consolidation"]
    )
    assert not spec.must_verify


def test_credit_product_serialization():
    """CreditProduct serializes correctly."""
    product = CreditProduct(
        code=Product.personal_loan,
        name="Personal Loan",
        purposes=["home renovation", "debt consolidation"],
        min_amount=Money(amount=Decimal("1000")),
        max_amount=Money(amount=Decimal("50000")),
        min_term_months=6,
        max_term_months=60,
        indicative_annual_rate_percent=Decimal("8.99"),
        rate_note="Subject to approval"
    )
    dumped = product.model_dump(mode="json")
    assert dumped["code"] == "personal_loan"
    assert dumped["min_amount"]["amount"] == "1000.00"


def test_eligibility_result_with_missing_fields():
    """EligibilityResult with missing_fields."""
    result = EligibilityResult(
        status=EligibilityStatus.more_information_required,
        reasons=[ReasonItem(code="missing_info", message="Additional information needed")],
        rule_version="v1.0",
        missing_fields=["monthly_income", "employment_type"],
        simulated=True
    )
    assert len(result.missing_fields) == 2


def test_awaiting_document_types():
    """Awaiting can specify document_types."""
    awaiting = Awaiting(
        kind=AwaitingKind.document,
        document_types=["payslip", "identity_card"]
    )
    assert len(awaiting.document_types) == 2


def test_progress_with_steps():
    """Progress with multiple steps."""
    progress = Progress(
        flow="credit_application",
        stage="eligibility",
        steps=[
            ProgressStep(stage="product_selection", status="done"),
            ProgressStep(stage="eligibility", status="current"),
            ProgressStep(stage="documents", status="todo")
        ]
    )
    assert len(progress.steps) == 3


def test_document_checklist_block():
    """DocumentChecklistBlock with items."""
    block = DocumentChecklistBlock(
        items=[
            DocumentChecklistItem(
                doc_type="payslip",
                label="Recent payslip",
                status="pending"
            ),
            DocumentChecklistItem(
                doc_type="identity_card",
                label="Identity card",
                status="verified"
            )
        ]
    )
    assert len(block.items) == 2


def test_extracted_fields_block():
    """ExtractedFieldsBlock with fields."""
    block = ExtractedFieldsBlock(
        fields=[
            ExtractedFieldView(
                field="monthly_income",
                label="Monthly income",
                value="5000",
                source="document",
                confidence=0.95,
                needs_confirmation=False,
                conflict_with=None
            )
        ]
    )
    assert len(block.fields) == 1


def test_application_summary_serialization():
    """ApplicationSummary serializes correctly."""
    summary = ApplicationSummary(
        summary_version="v1",
        application_id="app_123",
        product_code=Product.personal_loan,
        product_name="Personal Loan",
        amount=Money(amount=Decimal("15000")),
        term_months=36,
        offer=LoanOffer(
            offer_id="offer_1",
            product_code=Product.personal_loan,
            amount=Money(amount=Decimal("15000")),
            term_months=36,
            annual_interest_rate_percent=Decimal("9.5"),
            monthly_installment=Money(amount=Decimal("478.12")),
            total_repayment=Money(amount=Decimal("17212.32")),
            total_cost=Money(amount=Decimal("2212.32")),
            fees=Money(amount=Decimal("150")),
            assumptions=["Income verified"],
            indicative=True,
            simulated=True
        ),
        fields=[
            SummaryField(
                label="Monthly income",
                value="5000 RON",
                source="document"
            )
        ],
        documents=[
            DocumentChecklistItem(
                doc_type="payslip",
                label="Payslip",
                status="verified"
            )
        ]
    )
    dumped = summary.model_dump(mode="json")
    assert dumped["product_code"] == "personal_loan"


def test_session_view_structure():
    """SessionView with messages and latest turn."""
    turn = TurnResponse(
        session_id="sess_123",
        turn_id="turn_1",
        session_version=1,
        messages=[
            ChatMessageView(
                role="customer",
                text="I need a loan",
                citations=[],
                created_at=datetime(2026, 10, 28, 12, 0, 0)
            )
        ],
        awaiting=Awaiting(kind=AwaitingKind.text),
        progress=Progress(flow="none", stage=None, steps=[]),
        blocks=[],
        simulated=False
    )

    session = SessionView(
        session_id="sess_123",
        created_at=datetime(2026, 10, 28, 12, 0, 0),
        messages=[
            ChatMessageView(
                role="customer",
                text="I need a loan",
                citations=[],
                created_at=datetime(2026, 10, 28, 12, 0, 0)
            )
        ],
        latest=turn
    )

    assert session.session_id == "sess_123"
    assert len(session.messages) == 1


def test_citation_ref_with_section():
    """CitationRef with optional section."""
    citation = CitationRef(
        id="cit_1",
        publisher="Raiffeisen Bank",
        title="Personal Loan Conditions",
        url="https://example.com",
        section="Eligibility",
        effective_date=date(2026, 1, 1)
    )
    assert citation.section == "Eligibility"


def test_offer_selection_request():
    """OfferSelectionRequest validation."""
    req = OfferSelectionRequest(offer_id="offer_123")
    assert req.offer_id == "offer_123"


def test_confirmation_request_confirm():
    """ConfirmationRequest with confirm decision."""
    req = ConfirmationRequest(summary_version="v1", decision="confirm")
    assert req.decision == "confirm"


def test_confirmation_request_decline():
    """ConfirmationRequest with decline decision."""
    req = ConfirmationRequest(summary_version="v1", decision="decline")
    assert req.decision == "decline"


def test_error_body():
    """ErrorBody structure."""
    error = ErrorBody(
        code="validation_error",
        message="Invalid input",
        retryable=False
    )
    assert error.code == "validation_error"


def test_product_requirements():
    """ProductRequirements with fields and documents."""
    reqs = ProductRequirements(
        product_code=Product.personal_loan,
        fields=[
            FieldSpec(
                name="monthly_income",
                label="Monthly income",
                type=FieldType.money
            )
        ],
        documents=[
            DocumentRequirement(
                doc_type="payslip",
                label="Recent payslip"
            )
        ]
    )
    assert reqs.product_code == Product.personal_loan


def test_escalation_block():
    """EscalationBlock structure."""
    block = EscalationBlock(
        ticket_id="ticket_123",
        message="Your case has been escalated"
    )
    assert block.ticket_id == "ticket_123"


def test_application_submitted_block():
    """ApplicationSubmittedBlock structure."""
    block = ApplicationSubmittedBlock(
        application_id="app_123",
        status="pending_review"
    )
    assert block.application_id == "app_123"


def test_eligibility_result_block():
    """EligibilityResultBlock structure."""
    result = EligibilityResult(
        status=EligibilityStatus.satisfied,
        reasons=[],
        rule_version="v1.0",
        simulated=True
    )
    block = EligibilityResultBlock(result=result)
    assert block.result.status == EligibilityStatus.satisfied
