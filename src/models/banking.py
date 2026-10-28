"""Typed synthetic banking records; no model contains authoritative decisions."""

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import Field

from src.models.common import Money, WireModel


class Role(str, Enum):
    CUSTOMER = "customer"
    REVIEWER = "reviewer"


class DocumentKind(str, Enum):
    IDENTITY = "identity"
    INCOME = "income"
    STATEMENT = "statement"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    AWAITING_DOCUMENTS = "AWAITING_DOCUMENTS"
    READY_FOR_SUBMISSION = "READY_FOR_SUBMISSION"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    MORE_INFORMATION_REQUIRED = "MORE_INFORMATION_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Actor(WireModel):
    id: str
    name: str
    role: Role


class Session(WireModel):
    token: str
    actor: Actor
    expires_at: datetime


class Customer(WireModel):
    id: str
    name: str
    email: str
    initials: str
    monthly_income: Money = Field(gt=0)
    monthly_expenses: Money = Field(ge=0)
    balance: Money
    employer: str
    synthetic: Literal[True] = True


class Product(WireModel):
    id: str
    name: str
    description: str
    annual_rate: Money = Field(ge=0, le=100)
    fee: Money = Field(ge=0)
    monthly_insurance: Money = Field(ge=0)
    min_amount: Money = Field(gt=0)
    max_amount: Money = Field(gt=0)
    min_months: int = Field(ge=1, le=600)
    max_months: int = Field(ge=1, le=600)
    policy_id: str
    policy_version: str
    required_documents: list[DocumentKind]


class PolicySource(WireModel):
    id: str
    title: str
    version: str
    effective_date: date
    section: str
    content: str
    product_id: str | None = None
    synthetic: Literal[True] = True


class Loan(WireModel):
    id: str
    customer_id: str
    name: str
    principal: Money = Field(gt=0)
    annual_rate: Money = Field(ge=0, le=100)
    remaining_months: int = Field(ge=1, le=600)
    original_amount: Money = Field(gt=0)
    next_payment_date: datetime
    synthetic: Literal[True] = True


class PaymentRow(WireModel):
    month: int
    payment: Money
    principal: Money
    interest: Money
    balance: Money


class LoanQuote(WireModel):
    amount: Money
    months: int
    annual_rate: Money
    installment: Money
    monthly_payment: Money
    fee: Money
    monthly_insurance: Money
    interest_cost: Money
    total_cost: Money
    schedule: list[PaymentRow]
    currency: Literal["RON"] = "RON"
    indicative: Literal[True] = True
    policy_version: str | None = None
    assumptions: list[str] = Field(default_factory=list)


class Assessment(WireModel):
    status: Literal[
        "PRELIMINARY_REQUIREMENTS_SATISFIED",
        "PRELIMINARY_REQUIREMENTS_NOT_SATISFIED",
        "ADDITIONAL_INFORMATION_REQUIRED",
        "MANUAL_REVIEW_REQUIRED",
    ]
    debt_ratio: Money
    threshold: Money
    reasons: list[str]
    reason_codes: list[str]
    evidence_references: list[str]
    policy_version: str
    assessed_at: datetime
    human_review_required: Literal[True] = True
    indicative: Literal[True] = True


class ApplicationDocument(WireModel):
    kind: DocumentKind
    status: Literal["MISSING", "FORMAT_ACCEPTED"] = "MISSING"
    name: str | None = None
    mime_type: str | None = None
    size: int | None = None
    uploaded_at: datetime | None = None
    authenticity_verified: Literal[False] = False


class DocumentValidation(WireModel):
    kind: DocumentKind
    status: Literal["FORMAT_ACCEPTED"] = "FORMAT_ACCEPTED"
    metadata_only: Literal[True] = True
    authenticity_verified: Literal[False] = False
    identity_verified: Literal[False] = False
    income_verified: Literal[False] = False
    reasons: list[str]


class RequiredDocuments(WireModel):
    product_id: str
    required: list[DocumentKind]
    optional: list[DocumentKind]
    allowed_mime_types: list[str]
    max_size_bytes: int
    policy_version: str
    metadata_only: Literal[True] = True


class HistoryEntry(WireModel):
    id: str
    status: ApplicationStatus
    at: datetime
    actor: str
    description: str
    correlation_id: str


class ReviewNote(WireModel):
    id: str
    author: str
    at: datetime
    text: str
    internal: bool


class LoanApplication(WireModel):
    id: str
    reference: str
    customer_id: str
    customer: Customer
    reviewer_id: str
    product_id: str
    policy_version: str
    amount: Money
    months: int
    quote: LoanQuote
    assessment: Assessment
    status: ApplicationStatus
    created_at: datetime
    updated_at: datetime
    documents: list[ApplicationDocument]
    required_document_kinds: list[DocumentKind]
    requested_document: DocumentKind | None = None
    request_reason: str | None = None
    decision_reason: str | None = None
    history: list[HistoryEntry]
    notes: list[ReviewNote] = Field(default_factory=list)
    synthetic: Literal[True] = True
    human_review_required: Literal[True] = True


class ApplicationState(WireModel):
    application_id: str
    status: ApplicationStatus
    updated_at: datetime
    requested_document: DocumentKind | None = None
    request_reason: str | None = None
    decision_reason: str | None = None
    history: list[HistoryEntry]
    synthetic: Literal[True] = True
    human_review_required: Literal[True] = True
    signed: Literal[False] = False
    funded: Literal[False] = False


class RepaymentQuote(WireModel):
    current: LoanQuote
    reduced_payment: LoanQuote
    reduced_term: LoanQuote
    repayment: Money
    new_principal: Money
    early_fee: Money
    payment_savings: Money
    interest_savings: Money
    months_saved: int
    indicative: Literal[True] = True
    policy_version: str
    assumptions: list[str]


class RefinanceQuote(WireModel):
    current_monthly: Money
    current_total: Money
    new_quote: LoanQuote
    monthly_savings: Money
    total_savings: Money
    principal: Money
    indicative: Literal[True] = True
    policy_version: str
    assumptions: list[str]


class PolicySearchResult(WireModel):
    sources: list[PolicySource]
    method: Literal["synthetic-keyword"] = "synthetic-keyword"
    authoritative: Literal[False] = False
    warnings: list[str]


class Consent(WireModel):
    financial_insights: bool = False
    notifications: bool = True


class Notification(WireModel):
    id: str
    customer_id: str
    title: str
    text: str
    at: datetime
    read: bool = False
    application_id: str | None = None
    mandatory: bool = False
    synthetic: Literal[True] = True


class AuditEvent(WireModel):
    id: str
    actor_id: str
    actor: str
    action: str
    object_id: str
    at: datetime
    result: str
    correlation_id: str


class ChatMessage(WireModel):
    id: str
    role: Literal["user", "assistant"]
    text: str
    at: datetime
    kind: Literal["text"] = "text"


class SupportRequest(WireModel):
    id: str
    customer_id: str
    application_id: str | None = None
    message: str
    created_at: datetime
    message_ids: list[str]
    status: Literal["RECORDED_SIMULATED"] = "RECORDED_SIMULATED"
    simulated: Literal[True] = True


class Snapshot(WireModel):
    actor: Actor
    customer: Customer | None
    products: list[Product]
    policies: list[PolicySource]
    loans: list[Loan]
    applications: list[LoanApplication]
    messages: list[ChatMessage]
    notifications: list[Notification]
    audit: list[AuditEvent]
    consent: Consent | None