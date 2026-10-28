"""Canonical run_eligibility_check: IDs only; use the merged reference service."""

from typing import Annotated

from fastapi import APIRouter, Path

from src.api.gateway.dependencies import Context, Services
from src.api.gateway.errors import ERROR_RESPONSES
from src.models.common import ApiResponse
from src.models.eligibility import EligibilityAssessment
from src.models.requests import EligibilityRunInput


router = APIRouter(tags=["Evidence-based preliminary eligibility"], responses=ERROR_RESPONSES)


@router.post("/eligibility/check", operation_id="run_eligibility_check")
async def eligibility_check(input: EligibilityRunInput, context: Context, services: Services) -> ApiResponse[EligibilityAssessment]:
    """Resolve server-owned evidence; never trust actor/income/rate/consent inputs."""
    return ApiResponse(data=await services.evidence_eligibility.run(context, input))


@router.get("/eligibility/assessments/{assessment_id}", operation_id="get_eligibility_assessment")
def eligibility_assessment(
    assessment_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")],
    context: Context, services: Services,
) -> ApiResponse[EligibilityAssessment]:
    return ApiResponse(data=services.evidence_eligibility.get(context, assessment_id))