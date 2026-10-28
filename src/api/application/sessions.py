"""Synthetic sign-in only. Session roles are fixed by server-side accounts."""

from fastapi import APIRouter

from src.api.gateway.dependencies import Context, Services, Token
from src.api.gateway.errors import ERROR_RESPONSES
from src.models.banking import Session
from src.models.common import ApiResponse, LogoutResult
from src.models.requests import EmptyInput, SessionInput


router = APIRouter(tags=["Sessions"], responses=ERROR_RESPONSES)


@router.post("/session", operation_id="create_demo_session")
def create_session(input: SessionInput, services: Services) -> ApiResponse[Session]:
    """Authenticate a public synthetic account. Never use real credentials."""
    return ApiResponse(data=services.sessions.create(input))


@router.post("/session/logout", operation_id="revoke_demo_session")
def logout(input: EmptyInput, context: Context, services: Services, token: Token) -> ApiResponse[LogoutResult]:
    services.sessions.revoke(token)
    return ApiResponse(data=LogoutResult())