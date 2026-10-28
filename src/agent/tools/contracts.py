"""Tool input and output contracts for the orchestrator."""
from typing import Literal
from pydantic import BaseModel, field_validator

from src.agent.orchestration.state import ExtractedField
from src.models.credit import CreditProduct, ProductRequirements, EligibilityResult, LoanOffer
from src.models.knowledge import Product


class PassageView(BaseModel):
    """A passage view for tool output."""
    citation_id: str
    header: str
    text: str
    publisher: str
    title: str
    url: str
    flags: list[str] = []


class SearchPoliciesInput(BaseModel):
    """Input for search_policies tool."""
    text: str
    products: list[Product] | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        """Validate text length."""
        v = v.strip()
        if not v or len(v) > 1000:
            raise ValueError("text must be 1-1000 characters after stripping")
        return v


class SearchPoliciesOutput(BaseModel):
    """Output for search_policies tool."""
    status: Literal["ok", "insufficient_evidence"]
    passages: list[PassageView]
    simulated: bool


class GetCreditProductsInput(BaseModel):
    """Input for get_credit_products tool."""
    purpose: str | None = None


class GetCreditProductsOutput(BaseModel):
    """Output for get_credit_products tool."""
    products: list[CreditProduct]
    simulated: bool = True


class GetCustomerProfileInput(BaseModel):
    """Input for get_customer_profile tool."""
    pass


class CustomerProfileOutput(BaseModel):
    """Output for get_customer_profile tool."""
    customer_id: str
    full_name: str
    age: int
    simulated: bool = True


class GetProductRequirementsInput(BaseModel):
    """Input for get_product_requirements tool."""
    product_code: Product


class ProcessDocumentInput(BaseModel):
    """Input for process_document tool."""
    document_id: str
    doc_type: str
    filename: str
    size_bytes: int


class ProcessDocumentOutput(BaseModel):
    """Output for process_document tool."""
    status: Literal["accepted", "rejected"]
    rejection_reason: str | None
    extracted_fields: dict[str, ExtractedField]
    simulated: bool = True


class CalculateOffersInput(BaseModel):
    """Input for calculate_offers tool."""
    term_options_months: list[int] | None = None

    @field_validator("term_options_months")
    @classmethod
    def validate_term_options(cls, v: list[int] | None) -> list[int] | None:
        """Validate term options."""
        if v is None:
            return v
        if len(v) > 3:
            raise ValueError("term_options_months must have at most 3 entries")
        for term in v:
            if term < 6 or term > 360:
                raise ValueError("each term must be between 6 and 360 months")
        return v


class CalculateOffersOutput(BaseModel):
    """Output for calculate_offers tool."""
    offers: list[LoanOffer]
    simulated: bool = True


class CreateApplicationInput(BaseModel):
    """Input for create_application tool."""
    pass


class CreateApplicationOutput(BaseModel):
    """Output for create_application tool."""
    draft_application_id: str
    simulated: bool = True


class SubmitApplicationInput(BaseModel):
    """Input for submit_application tool."""
    application_id: str
    idempotency_key: str


class SubmitApplicationOutput(BaseModel):
    """Output for submit_application tool."""
    application_id: str
    status: Literal["PENDING_HUMAN_REVIEW"]
    simulated: bool = True


class GetApplicationStatusInput(BaseModel):
    """Input for get_application_status tool."""
    pass


class StatusEntry(BaseModel):
    """A status history entry."""
    status: str
    at: str


class ApplicationStatusOutput(BaseModel):
    """Output for get_application_status tool."""
    application_id: str | None
    status: str
    history: list[StatusEntry]
    simulated: bool = True


class RequestHumanReviewInput(BaseModel):
    """Input for request_human_review tool."""
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        """Validate reason length."""
        v = v.strip()
        if not v or len(v) > 500:
            raise ValueError("reason must be 1-500 characters after stripping")
        return v


class RequestHumanReviewOutput(BaseModel):
    """Output for request_human_review tool."""
    ticket_id: str
    message: str
    simulated: bool = True


# Re-export ProductRequirements and EligibilityResult for convenience
__all__ = [
    "PassageView",
    "SearchPoliciesInput",
    "SearchPoliciesOutput",
    "GetCreditProductsInput",
    "GetCreditProductsOutput",
    "GetCustomerProfileInput",
    "CustomerProfileOutput",
    "GetProductRequirementsInput",
    "ProductRequirements",
    "ProcessDocumentInput",
    "ProcessDocumentOutput",
    "CalculateOffersInput",
    "CalculateOffersOutput",
    "CreateApplicationInput",
    "CreateApplicationOutput",
    "SubmitApplicationInput",
    "SubmitApplicationOutput",
    "GetApplicationStatusInput",
    "ApplicationStatusOutput",
    "RequestHumanReviewInput",
    "RequestHumanReviewOutput",
    "EligibilityResult",
]
