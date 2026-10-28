"""Narrow orchestrator tool; actor identity is injected by trusted backend code."""

from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from src.core.eligibility_errors import EligibilityError
from src.models.eligibility import EligibilityCheckRequest
from src.security.eligibility import ActorContext
from src.services.eligibility.service import EligibilityService


TOOL_NAME = "run_eligibility_check"
TOOL_DESCRIPTION = (
    "Run a synthetic deterministic preliminary personal-loan assessment using "
    "server-owned application evidence and an optional server-owned pricing scenario. "
    "Never approves/rejects a loan or changes workflow state. Requires backend "
    "authorization and a retry-safe idempotency key."
)


def tool_definition() -> dict[str, Any]:
    return {"name": TOOL_NAME, "description": TOOL_DESCRIPTION,
            "parameters": EligibilityCheckRequest.model_json_schema()}


async def run_eligibility_check(
    arguments: dict[str, Any], *, service: EligibilityService, actor: ActorContext,
) -> dict[str, Any]:
    correlation_id = str(uuid4())
    try:
        request = EligibilityCheckRequest.model_validate(arguments)
        result = await service.assess(request, actor, correlation_id)
        return {"data": result.model_dump(mode="json")}
    except ValidationError:
        return {"error": {"code": "VALIDATION_ERROR", "message": "Invalid eligibility tool input.",
                          "correlationId": correlation_id}}
    except EligibilityError as exc:
        return {"error": {"code": exc.code, "message": exc.message, "correlationId": correlation_id}}
    except Exception:
        return {"error": {"code": "INTERNAL_ERROR", "message": "The assessment could not be completed.",
                          "correlationId": correlation_id}}