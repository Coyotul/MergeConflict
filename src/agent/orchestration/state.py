"""Session state models for the orchestrator."""
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from src.models.chat import CitationRef, ApplicationSummary
from src.models.credit import EligibilityResult, LoanOffer, ProductRequirements
from src.models.knowledge import Product
from src.models.document_processing import CrossDocumentValidationSummary, DocumentValidationSummary


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
    kind: Literal["money", "integer", "text", "boolean"]
    value: Decimal | int | str | bool
    source: FieldSource
    document_id: str | None = None
    confidence: float | None = None
    confirmed: bool = False
    updated_at: datetime

    @classmethod
    def _coerce_value(cls, value: Decimal | int | str | bool, kind: str) -> Decimal | int | str | bool:
        """Coerce value to match kind, handling JSON round-trip."""
        if kind == "money":
            if isinstance(value, Decimal):
                return value
            return Decimal(str(value))
        elif kind == "integer":
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            return int(value)
        elif kind == "text":
            if isinstance(value, str):
                return value
            return str(value)
        elif kind == "boolean":
            if isinstance(value, bool):
                return value
            return bool(value)
        return value

    def model_post_init(self, __context):
        """Coerce value after initialization to ensure type matches kind."""
        # Use object.__setattr__ to bypass frozen/immutable restrictions if any
        object.__setattr__(self, 'value', self._coerce_value(self.value, self.kind))


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
    confidence: float = Field(ge=0, le=1)
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
    human_review_required: bool = False
    validation: DocumentValidationSummary | None = None
    extracted_data: dict | None = None
    sha256_hash: str | None = None


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
    document_verification: CrossDocumentValidationSummary | None = None
    document_verification_complete: bool = False


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
