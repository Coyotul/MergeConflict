"""Human review records: a submitted application and what reviewers and customers did to it."""
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel


class ReviewStatus(StrEnum):
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    MORE_INFORMATION_REQUIRED = "MORE_INFORMATION_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


STATUS_LABELS = {
    ReviewStatus.PENDING_HUMAN_REVIEW: "Waiting for review",
    ReviewStatus.MORE_INFORMATION_REQUIRED: "More information needed",
    ReviewStatus.APPROVED: "Accepted",
    ReviewStatus.REJECTED: "Rejected",
}

# Reviewer-driven moves. MORE_INFORMATION_REQUIRED -> PENDING only happens through an accepted upload.
REVIEWER_TRANSITIONS = {
    ReviewStatus.PENDING_HUMAN_REVIEW: {
        ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.MORE_INFORMATION_REQUIRED,
    },
}


class NotFound(Exception):
    pass


class InvalidTransition(Exception):
    pass


class StaleVersion(Exception):
    pass


class HistoryEntry(BaseModel):
    from_status: ReviewStatus | None
    to_status: ReviewStatus
    actor: str
    reason: str
    at: datetime


class InfoRequest(BaseModel):
    id: str
    doc_type: str
    reason: str
    status: Literal["open", "fulfilled"]
    created_at: datetime
    fulfilled_at: datetime | None = None
    fulfilled_document_id: str | None = None


class ReviewDocument(BaseModel):
    document_id: str
    doc_type: str
    origin: Literal["chat", "information_request"]
    status: str
    filename: str | None = None
    extracted_fields: dict[str, Any] = {}
    validation: dict[str, Any] | None = None
    sha256: str | None = None
    uploaded_at: datetime
    superseded_by: str | None = None


class ReviewApplication(BaseModel):
    id: str
    reference: str
    customer_id: str
    session_id: str
    product_code: str
    status: ReviewStatus
    version: int
    snapshot: dict[str, Any]
    current: dict[str, Any]
    documents: list[ReviewDocument]
    history: list[HistoryEntry]
    requests: list[InfoRequest]
    created_at: datetime
    updated_at: datetime

    @property
    def open_request(self) -> InfoRequest | None:
        return next((r for r in self.requests if r.status == "open"), None)
