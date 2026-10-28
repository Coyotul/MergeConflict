from fastapi import APIRouter

from src.api.gateway.dependencies import Context, Services
from src.api.gateway.errors import ERROR_RESPONSES
from src.models.banking import Consent, Customer, Loan, Snapshot
from src.models.common import ApiResponse
from src.models.requests import ConsentInput


router = APIRouter(tags=["Customers"], responses=ERROR_RESPONSES)


@router.get("/customers/me", operation_id="get_customer_profile")
def customer_profile(context: Context, services: Services) -> ApiResponse[Customer]:
    """Return only the authenticated customer's synthetic profile."""
    return ApiResponse(data=services.customers.profile(context))


@router.get("/customers/me/loans", operation_id="get_customer_loans")
def customer_loans(context: Context, services: Services) -> ApiResponse[list[Loan]]:
    return ApiResponse(data=services.customers.loans(context))


@router.get("/loans/{loan_id}", operation_id="get_customer_loan")
def customer_loan(loan_id: str, context: Context, services: Services) -> ApiResponse[Loan]:
    return ApiResponse(data=services.customers.loan(context, loan_id))


@router.get("/consent", operation_id="get_customer_consent")
def customer_consent(context: Context, services: Services) -> ApiResponse[Consent]:
    return ApiResponse(data=services.customers.consent(context))


@router.patch("/consent", operation_id="update_customer_consent")
def update_consent(input: ConsentInput, context: Context, services: Services) -> ApiResponse[Consent]:
    return ApiResponse(data=services.customers.update_consent(context, input))


@router.get("/snapshot", operation_id="get_workspace_snapshot")
def snapshot(context: Context, services: Services) -> ApiResponse[Snapshot]:
    """Owner-filtered customer or assignment-filtered reviewer workspace."""
    return ApiResponse(data=services.snapshot(context.actor))