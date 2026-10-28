from fastapi import APIRouter

from src.api.gateway.dependencies import Context, Services
from src.api.gateway.errors import ERROR_RESPONSES
from src.models.banking import AuditEvent, LoanApplication
from src.models.common import ApiResponse
from src.models.requests import NoteInput, ReviewInput


router = APIRouter(tags=["Human review"], responses=ERROR_RESPONSES)


@router.get("/reviews/queue", operation_id="get_assigned_review_queue")
def review_queue(context: Context, services: Services) -> ApiResponse[list[LoanApplication]]:
    return ApiResponse(data=services.reviews.queue(context))


@router.post("/applications/{application_id}/review", operation_id="record_human_review_decision")
def review(application_id: str, input: ReviewInput, context: Context, services: Services) -> ApiResponse[LoanApplication]:
    """Human-only staff capability. Never expose this tool to a customer LLM."""
    return ApiResponse(data=services.reviews.review(context, application_id, input))


@router.post("/applications/{application_id}/notes", operation_id="add_internal_review_note")
def add_note(application_id: str, input: NoteInput, context: Context, services: Services) -> ApiResponse[LoanApplication]:
    return ApiResponse(data=services.reviews.add_note(context, application_id, input))


@router.get("/audit", operation_id="get_permitted_audit_events")
def audit(context: Context, services: Services) -> ApiResponse[list[AuditEvent]]:
    return ApiResponse(data=services.audit(context.actor))