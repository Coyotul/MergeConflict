"""Strict tool input schemas. Actors, rates and workflow state are never inputs."""

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from src.models.banking import DocumentKind, Role
from src.models.common import WireModel


def require_true(value: object) -> bool:
    if value is not True:
        raise ValueError("Explicit confirmation must be the boolean true.")
    return True


Confirmed = Annotated[Literal[True], BeforeValidator(require_true)]
MoneyInput = Annotated[
    str, StringConstraints(strict=True, pattern=r"^[0-9]{1,9}(\.[0-9]{1,2})?$", max_length=12)
]
Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True)]
Identifier = Annotated[Text, Field(min_length=1, max_length=80)]


class ApiInput(WireModel):
    model_config = ConfigDict(validate_by_name=False, validate_by_alias=True)


class EmptyInput(ApiInput):
    pass


class SessionInput(ApiInput):
    role: Role
    email: Annotated[Text, Field(min_length=3, max_length=254)]
    password: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid demo email address.")
        return value


class LoanScenarioInput(ApiInput):
    product_id: Identifier
    amount: MoneyInput
    months: Annotated[StrictInt, Field(ge=1, le=600)]


class EligibilityRunInput(ApiInput):
    application_id: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
    pricing_scenario_id: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")] | None = None
    idempotency_key: UUID


class CreateApplicationInput(LoanScenarioInput):
    idempotency_key: UUID


class DocumentInput(ApiInput):
    kind: DocumentKind
    name: Annotated[Text, Field(min_length=1, max_length=160)]
    mime_type: Literal["application/pdf", "image/jpeg", "image/png"]
    size: Annotated[StrictInt, Field(gt=0, le=10 * 1024 * 1024)]
    synthetic_confirmed: Confirmed

    @model_validator(mode="after")
    def validate_filename(self) -> "DocumentInput":
        if re.search(r"[\\/\x00-\x1f\x7f]", self.name) or self.name in {".", ".."}:
            raise ValueError("Invalid filename.")
        extensions = {
            "application/pdf": r"\.pdf$",
            "image/jpeg": r"\.jpe?g$",
            "image/png": r"\.png$",
        }
        if not re.search(extensions[self.mime_type], self.name, re.IGNORECASE):
            raise ValueError("File extension must match its declared MIME type.")
        return self


class UploadDocumentInput(DocumentInput):
    idempotency_key: UUID


class SubmitApplicationInput(ApiInput):
    confirmed: Confirmed
    idempotency_key: UUID


class ReviewInput(ApiInput):
    action: Literal["approve", "reject", "request-information"]
    reason: Annotated[Text, Field(min_length=10, max_length=2000)]
    evidence_reviewed: Confirmed
    requested_document: DocumentKind | None = None
    idempotency_key: UUID

    @model_validator(mode="after")
    def validate_requested_document(self) -> "ReviewInput":
        if self.action == "request-information" and self.requested_document is None:
            raise ValueError("Choose the additional document to request.")
        if self.action != "request-information" and self.requested_document is not None:
            raise ValueError("A final decision cannot request an additional document.")
        return self


class NoteInput(ApiInput):
    text: Annotated[Text, Field(min_length=3, max_length=2000)]
    idempotency_key: UUID


class CancelApplicationInput(ApiInput):
    reason: Annotated[Text, Field(min_length=3, max_length=2000)]
    idempotency_key: UUID


class EarlyRepaymentInput(ApiInput):
    repayment: MoneyInput


class RefinancingInput(ApiInput):
    loan_ids: Annotated[list[Identifier], Field(min_length=1, max_length=10)]
    months: Annotated[StrictInt, Field(ge=1, le=600)]

    @field_validator("loan_ids")
    @classmethod
    def distinct_loans(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Select each loan only once.")
        return value


class PolicySearchInput(ApiInput):
    query: Annotated[Text, Field(min_length=2, max_length=1000)]
    product_id: Identifier | None = None
    limit: Annotated[StrictInt, Field(ge=1, le=10)] = 5


class ConsentInput(ApiInput):
    financial_insights: StrictBool
    notifications: StrictBool


class NotificationInput(ApiInput):
    title: Annotated[Text, Field(min_length=3, max_length=160)]
    text: Annotated[Text, Field(min_length=3, max_length=2000)]
    application_id: Identifier | None = None
    idempotency_key: UUID


class SupportInput(ApiInput):
    message: Annotated[Text, Field(min_length=3, max_length=2000)]
    application_id: Identifier | None = None
    idempotency_key: UUID


class MessageInput(ApiInput):
    text: Annotated[Text, Field(min_length=1, max_length=2000)]
    idempotency_key: UUID