from fastapi import APIRouter

from src.api.gateway.dependencies import Context, Services
from src.api.gateway.errors import ERROR_RESPONSES
from src.models.banking import Assessment, LoanQuote, RefinanceQuote, RepaymentQuote, Role
from src.models.common import ApiResponse
from src.models.requests import EarlyRepaymentInput, LoanScenarioInput, RefinancingInput
from src.security.permissions import require_role


router = APIRouter(tags=["Indicative calculations"], responses=ERROR_RESPONSES)


@router.post("/calculations/loan-offer", operation_id="calculate_loan_offer")
def calculate_offer(input: LoanScenarioInput, context: Context, services: Services) -> ApiResponse[LoanQuote]:
    """Calculate from versioned backend pricing, never from LLM-supplied rates."""
    require_role(context.actor, Role.CUSTOMER)
    return ApiResponse(data=services.pricing.calculate(input))


@router.post("/eligibility/check", operation_id="run_eligibility_check")
def eligibility_check(input: LoanScenarioInput, context: Context, services: Services) -> ApiResponse[Assessment]:
    """Preliminary synthetic screening only; human review is always required."""
    return ApiResponse(data=services.assess(context, input))


@router.post("/loans/{loan_id}/early-repayment/simulate", operation_id="simulate_early_repayment")
def early_repayment(loan_id: str, input: EarlyRepaymentInput, context: Context, services: Services) -> ApiResponse[RepaymentQuote]:
    return ApiResponse(data=services.servicing.simulate(context, loan_id, input))


@router.post("/refinancing/compare", operation_id="compare_refinancing_options")
def refinancing(input: RefinancingInput, context: Context, services: Services) -> ApiResponse[RefinanceQuote]:
    return ApiResponse(data=services.refinancing.compare(context, input))