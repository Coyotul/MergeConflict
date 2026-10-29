"""Thin FastAPI router: authentication injected, domain behavior stays in service."""

from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import TypeAdapter, ValidationError

from src.core.eligibility_errors import EligibilityError
from src.models.eligibility import EligibilityAssessment, EligibilityCheckRequest, Identifier
from src.security.eligibility import ActorContext
from src.services.eligibility.service import EligibilityService


def eligibility_router(
    service: EligibilityService, actor_dependency: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/eligibility", tags=["synthetic-eligibility"])

    @router.post("/assessments", response_model=dict[str, EligibilityAssessment])
    async def assess(
        body: EligibilityCheckRequest, request: Request,
        actor: ActorContext = Depends(actor_dependency),
    ) -> dict[str, EligibilityAssessment]:
        correlation_id = str(uuid4())
        request.state.correlation_id = correlation_id
        result = await service.assess(body, actor, correlation_id)
        return {"data": result}

    @router.get("/assessments/{assessment_id}", response_model=dict[str, EligibilityAssessment])
    async def get_assessment(
        assessment_id: str, actor: ActorContext = Depends(actor_dependency),
    ) -> dict[str, EligibilityAssessment]:
        # Prevent unbounded/invalid identifiers from reaching persistence.
        try:
            assessment_id = TypeAdapter(Identifier).validate_python(assessment_id)
        except ValidationError as exc:
            raise EligibilityError("VALIDATION_ERROR", "Invalid assessment identifier.", 422) from exc
        return {"data": service.get_assessment(assessment_id, actor)}

    return router