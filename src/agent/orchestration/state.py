"""Session state models for the orchestrator."""
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from src.models.chat import CitationRef, ApplicationSummary
from src.models.credit import EligibilityResult, LoanOffer, ProductRequirements
from src.models.knowledge import Product


class Flow(StrEnum):
    """Active conversation flow."""
    none = "none"
    product_info = "product_info"
    credit_application = "credit_application"


class FieldSource(StrEnum):
    """Source of a field value."""
    customer = "customer"
    document = "document"
    profile = "profile"


class FieldValue(BaseModel):
    """A field value with metadata."""
    value: Decimal | int | str | bool
    source: FieldSource
    document_id: str | None = None
    confidence: float | None = None
    confirmed: bool = False
    updated_at: datetime


class DocumentStatus(StrEnum):
    """Status of a document."""
    requested = "requested"
    uploaded = "uploaded"
    processing = "processing"
    accepted = "accepted"
    rejected = "rejected"


class ExtractedField(BaseModel):
    """A field extracted from a document."""
    value: str
    confidence: float
    location: str | None = None


class DocumentRecord(BaseModel):
    """Record of a document in the session."""
    document_id: str
    doc_type: str
    filename: str
    status: DocumentStatus
    rejection_reason: str | None = None
    extracted_fields: dict[str, ExtractedField] = {}
    uploaded_at: datetime


class FieldConflict(BaseModel):
    """Conflict between customer and document values."""
    field: str
    customer_value: str
    document_value: str
    document_id: str


class EligibilityRecord(BaseModel):
    """Record of an eligibility check result."""
    result: EligibilityResult
    input_fingerprint: str
    verified_inputs: bool


class OffersRecord(BaseModel):
    """Record of loan offers."""
    offers: list[LoanOffer]
    input_fingerprint: str


class EscalationRecord(BaseModel):
    """Record of an escalation to human review."""
    ticket_id: str
    reason: str
    created_at: datetime


class ApplicationState(BaseModel):
    """State of the credit application within a session."""
    fields: dict[str, FieldValue] = {}
    product_code: Product | None = None
    requirements: ProductRequirements | None = None
    documents: list[DocumentRecord] = []
    conflicts: list[FieldConflict] = []
    eligibility: EligibilityRecord | None = None
    offers: OffersRecord | None = None
    selected_offer_id: str | None = None
    draft_application_id: str | None = None
    summary: ApplicationSummary | None = None
    application_id: str | None = None
    submitted_at: datetime | None = None
    idempotency_key: str | None = None


class SessionState(BaseModel):
    """Complete session state."""
    session_id: str
    customer_id: str
    created_at: datetime
    updated_at: datetime
    version: int = 0
    language: Literal["ro", "en"] = "ro"
    active_flow: Flow = Flow.none
    application: ApplicationState | None = None
    retrieved_sources: dict[str, CitationRef] = {}
    escalation: EscalationRecord | None = None
    used_stubs: bool = False


class StoredMessage(BaseModel):
    """A stored message in the conversation log."""
    message_id: str
    turn_id: str
    role: Literal["customer", "assistant", "action", "tool", "event"]
    content: str
    citations: list[CitationRef] = []
    created_at: datetime
