"""Chat and session wire models for the orchestrator API."""
from datetime import datetime, date
from enum import StrEnum
from typing import Literal, Annotated, Union
from pydantic import BaseModel, Field, field_validator

from src.models.credit import Money, EligibilityResult, LoanOffer
from src.models.knowledge import Product


class CitationRef(BaseModel):
    """Citation reference for assistant messages."""
    id: str
    publisher: str
    title: str
    url: str
    section: str | None = None
    effective_date: date | None = None


class ChatMessageView(BaseModel):
    """A chat message in the conversation."""
    role: Literal["customer", "assistant"]
    text: str
    citations: list[CitationRef] = []
    created_at: datetime


class AwaitingKind(StrEnum):
    """What the assistant is waiting for from the customer."""
    text = "text"
    document = "document"
    offer_choice = "offer_choice"
    confirmation = "confirmation"
    none = "none"


class Awaiting(BaseModel):
    """What the assistant is currently awaiting."""
    kind: AwaitingKind
    document_types: list[str] = []
    summary_version: str | None = None


StepStatus = Literal["done", "current", "todo"]


class ProgressStep(BaseModel):
    """A step in the credit application progress."""
    stage: str
    status: StepStatus


class Progress(BaseModel):
    """Progress through the credit application flow."""
    flow: Literal["none", "product_info", "credit_application"]
    stage: str | None
    steps: list[ProgressStep]


class DocumentChecklistItem(BaseModel):
    """An item in the document checklist."""
    doc_type: str
    label: str
    status: str
    rejection_reason: str | None = None


class DocumentChecklistBlock(BaseModel):
    """Block showing document checklist."""
    type: Literal["document_checklist"] = "document_checklist"
    items: list[DocumentChecklistItem]


class ExtractedFieldView(BaseModel):
    """A field extracted from documents or conversation."""
    field: str
    label: str
    value: str
    source: str
    confidence: float | None = None
    needs_confirmation: bool
    conflict_with: str | None = None


class ExtractedFieldsBlock(BaseModel):
    """Block showing extracted fields."""
    type: Literal["extracted_fields"] = "extracted_fields"
    fields: list[ExtractedFieldView]


class EligibilityResultBlock(BaseModel):
    """Block showing eligibility check result."""
    type: Literal["eligibility_result"] = "eligibility_result"
    result: EligibilityResult


class OffersBlock(BaseModel):
    """Block showing loan offers."""
    type: Literal["offers"] = "offers"
    offers: list[LoanOffer]
    selected_offer_id: str | None = None


class SummaryField(BaseModel):
    """A field in the application summary."""
    label: str
    value: str
    source: str


class ApplicationSummary(BaseModel):
    """Complete application summary for confirmation."""
    summary_version: str
    application_id: str
    product_code: Product
    product_name: str
    amount: Money
    term_months: int
    offer: LoanOffer
    fields: list[SummaryField]
    documents: list[DocumentChecklistItem]


class ApplicationSummaryBlock(BaseModel):
    """Block showing application summary."""
    type: Literal["application_summary"] = "application_summary"
    summary: ApplicationSummary


class ApplicationSubmittedBlock(BaseModel):
    """Block confirming application submission."""
    type: Literal["application_submitted"] = "application_submitted"
    application_id: str
    status: str


class EscalationBlock(BaseModel):
    """The chat stopped; the customer should contact a bank representative."""
    type: Literal["escalation"] = "escalation"
    message: str


# Discriminated union of all block types
Block = Annotated[
    Union[
        DocumentChecklistBlock,
        ExtractedFieldsBlock,
        EligibilityResultBlock,
        OffersBlock,
        ApplicationSummaryBlock,
        ApplicationSubmittedBlock,
        EscalationBlock
    ],
    Field(discriminator="type")
]


class TurnResponse(BaseModel):
    """Response from a single turn in the conversation."""
    session_id: str
    turn_id: str
    session_version: int
    messages: list[ChatMessageView]
    awaiting: Awaiting
    progress: Progress
    blocks: list[Block]
    simulated: bool


class SessionView(BaseModel):
    """Complete view of a session."""
    session_id: str
    created_at: datetime
    messages: list[ChatMessageView]
    latest: TurnResponse


class SendMessageRequest(BaseModel):
    """Request to send a text message."""
    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        """Validate text is not blank and within length limits."""
        v = v.strip()
        if not v:
            raise ValueError("text must not be blank")
        if len(v) > 4000:
            raise ValueError("text must be at most 4000 characters")
        return v


class OfferSelectionRequest(BaseModel):
    """Request to select a loan offer."""
    offer_id: str


class ConfirmationRequest(BaseModel):
    """Request to confirm or decline the application summary."""
    summary_version: str
    decision: Literal["confirm", "decline"]


class ErrorBody(BaseModel):
    """Error response body."""
    code: str
    message: str
    retryable: bool
