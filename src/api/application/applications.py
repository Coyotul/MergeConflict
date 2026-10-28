from fastapi import APIRouter

from src.api.gateway.dependencies import Context, Services
from src.api.gateway.errors import ERROR_RESPONSES
from src.models.banking import ApplicationDocument, ApplicationState, LoanApplication
from src.models.common import ApiResponse
from src.models.requests import CancelApplicationInput, CreateApplicationInput, SubmitApplicationInput, UploadDocumentInput


router = APIRouter(tags=["Applications"], responses=ERROR_RESPONSES)


@router.get("/applications", operation_id="list_loan_applications")
def applications(context: Context, services: Services) -> ApiResponse[list[LoanApplication]]:
    return ApiResponse(data=services.workflow.list(context))


@router.post("/applications", operation_id="create_loan_application")
def create_application(input: CreateApplicationInput, context: Context, services: Services) -> ApiResponse[LoanApplication]:
    """Idempotently save a synthetic draft; never implicitly submit or approve."""
    return ApiResponse(data=services.workflow.create(context, input))


@router.get("/applications/{application_id}", operation_id="get_loan_application")
def application(application_id: str, context: Context, services: Services) -> ApiResponse[LoanApplication]:
    return ApiResponse(data=services.workflow.get(context, application_id))


@router.get("/applications/{application_id}/status", operation_id="get_application_status")
def application_status(application_id: str, context: Context, services: Services) -> ApiResponse[ApplicationState]:
    return ApiResponse(data=services.workflow.status(context, application_id))


@router.get("/applications/{application_id}/documents", operation_id="get_application_documents")
def application_documents(application_id: str, context: Context, services: Services) -> ApiResponse[list[ApplicationDocument]]:
    return ApiResponse(data=services.workflow.get(context, application_id).documents)


@router.post("/applications/{application_id}/documents", operation_id="add_application_document_metadata")
def add_document(application_id: str, input: UploadDocumentInput, context: Context, services: Services) -> ApiResponse[LoanApplication]:
    """Metadata only; FORMAT_ACCEPTED must never be described as VERIFIED."""
    return ApiResponse(data=services.workflow.upload(context, application_id, input))


@router.post("/applications/{application_id}/submit", operation_id="submit_application")
def submit(application_id: str, input: SubmitApplicationInput, context: Context, services: Services) -> ApiResponse[LoanApplication]:
    """Requires explicit customer confirmation and complete synthetic metadata."""
    return ApiResponse(data=services.workflow.submit(context, application_id, input))


@router.post("/applications/{application_id}/cancel", operation_id="cancel_loan_application")
def cancel(application_id: str, input: CancelApplicationInput, context: Context, services: Services) -> ApiResponse[LoanApplication]:
    return ApiResponse(data=services.workflow.cancel(context, application_id, input))