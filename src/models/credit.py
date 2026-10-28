"""Credit-related wire models for the orchestrator API."""
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, field_validator, field_serializer

from src.models.knowledge import Product


class Money(BaseModel):
    """Monetary amount with currency."""
    amount: Decimal
    currency: Literal["RON", "EUR"] = "RON"

    @field_validator("amount", mode="before")
    @classmethod
    def quantize_amount(cls, v: Decimal | float | str | int) -> Decimal:
        """Quantize amount to 2 decimal places with ROUND_HALF_UP."""
        if not isinstance(v, Decimal):
            v = Decimal(str(v))
        return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @field_serializer("amount", when_used="json")
    def serialize_amount(self, value: Decimal) -> str:
        """Serialize amount as string for JSON."""
        return str(value)


class FieldType(StrEnum):
    """Field types for credit application fields."""
    money = "money"
    integer = "integer"
    enum = "enum"
    text = "text"
    boolean = "boolean"


class FieldSpec(BaseModel):
    """Specification for a credit application field."""
    name: str
    label: str
    type: FieldType
    required: bool = True
    verified_by: str | None = None
    identity: bool = False
    min: Decimal | None = None
    max: Decimal | None = None
    options: list[str] | None = None

    @property
    def must_verify(self) -> bool:
        """Return True if this field requires verification."""
        return self.verified_by is not None


class DocumentRequirement(BaseModel):
    """Required document for a credit product."""
    doc_type: str
    label: str


class CreditProduct(BaseModel):
    """Credit product information."""
    code: Product
    name: str
    purposes: list[str]
    min_amount: Money
    max_amount: Money
    min_term_months: int
    max_term_months: int
    indicative_annual_rate_percent: Decimal
    rate_note: str


class ProductRequirements(BaseModel):
    """Requirements for a credit product."""
    product_code: Product
    fields: list[FieldSpec]
    documents: list[DocumentRequirement]


class ReasonItem(BaseModel):
    """A reason code with message."""
    code: str
    message: str


class EligibilityStatus(StrEnum):
    """Eligibility check status."""
    satisfied = "satisfied"
    not_satisfied = "not_satisfied"
    more_information_required = "more_information_required"
    manual_review = "manual_review"


class EligibilityResult(BaseModel):
    """Result of an eligibility check."""
    status: EligibilityStatus
    reasons: list[ReasonItem]
    rule_version: str
    missing_fields: list[str] = []
    simulated: bool = True


class LoanOffer(BaseModel):
    """A loan offer with calculated terms."""
    offer_id: str
    product_code: Product
    amount: Money
    term_months: int
    annual_interest_rate_percent: Decimal
    monthly_installment: Money
    total_repayment: Money
    total_cost: Money
    fees: Money
    assumptions: list[str]
    indicative: bool = True
    simulated: bool = True
