from fastapi import APIRouter

from src.api.gateway.dependencies import Context, Services
from src.api.gateway.errors import ERROR_RESPONSES
from src.core.errors import DomainError
from src.models.banking import ChatMessage, Notification, SupportRequest
from src.models.common import ApiResponse, ResetResult
from src.models.requests import EmptyInput, MessageInput, NotificationInput, SupportInput


router = APIRouter(tags=["Conversation and notifications"], responses=ERROR_RESPONSES)


@router.get("/notifications", operation_id="get_customer_notifications")
def notifications(context: Context, services: Services) -> ApiResponse[list[Notification]]:
    return ApiResponse(data=services.notifications.list(context))


@router.post("/notifications", operation_id="create_customer_notification")
def create_notification(input: NotificationInput, context: Context, services: Services) -> ApiResponse[Notification]:
    """Record an optional in-app update only for the authenticated customer."""
    return ApiResponse(data=services.notifications.create(context, input))


@router.post("/notifications/read", operation_id="mark_customer_notifications_read")
def mark_notifications_read(input: EmptyInput, context: Context, services: Services) -> ApiResponse[list[Notification]]:
    return ApiResponse(data=services.notifications.mark_read(context))


@router.post("/support", operation_id="request_human_review")
def request_human_review(input: SupportInput, context: Context, services: Services) -> ApiResponse[SupportRequest]:
    """Simulated assistance only; never submits a draft or records a decision."""
    return ApiResponse(data=services.conversations.request_review(context, input))


@router.get("/conversations/messages", operation_id="get_conversation_messages")
def messages(context: Context, services: Services) -> ApiResponse[list[ChatMessage]]:
    return ApiResponse(data=services.conversations.list(context))


@router.post("/conversations/messages", operation_id="append_customer_message")
def append_message(input: MessageInput, context: Context, services: Services) -> ApiResponse[ChatMessage]:
    return ApiResponse(data=services.conversations.append(context, input))


@router.post("/conversations/reset", operation_id="reset_customer_conversation")
def reset_conversation(input: EmptyInput, context: Context, services: Services) -> ApiResponse[ResetResult]:
    return ApiResponse(data=services.conversations.reset(context))


@router.post("/chat", operation_id="chat_orchestrator_not_configured", response_model=ApiResponse[ChatMessage])
def chat_not_configured(context: Context) -> ApiResponse[ChatMessage]:
    raise DomainError("ORCHESTRATOR_NOT_CONFIGURED", "The backend tools are ready, but no AI orchestrator is connected. No assistant response was generated.", 501)