"""Store user context without implementing or pretending to run an orchestrator."""

from __future__ import annotations  # method `list` shadows the builtin in annotations (Python < 3.14)

from src.core.context import CallContext
from src.models.banking import ChatMessage, Role, SupportRequest
from src.models.common import ResetResult, new_id, utc_now
from src.models.requests import MessageInput, SupportInput
from src.observability.audit import record_audit
from src.security.permissions import require_role
from src.storage.application_db.repository import Repository


class ConversationService:
    def __init__(self, repository: Repository):
        self.repository = repository

    def list(self, context: CallContext) -> list[ChatMessage]:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.read() as unit:
            return unit.messages(context.actor.id)

    def append(self, context: CallContext, input: MessageInput) -> ChatMessage:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.transaction() as unit:
            def action() -> ChatMessage:
                message = ChatMessage(id=new_id(), role="user", text=input.text, at=utc_now())
                unit.add_message(context.actor.id, message)
                record_audit(unit, context, "CONVERSATION_MESSAGE_ADDED", context.actor.id, "User context recorded; no AI response generated")
                return message

            return unit.idempotent(context.actor, str(input.idempotency_key), "conversation:append", input, ChatMessage, action)

    def reset(self, context: CallContext) -> ResetResult:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.transaction() as unit:
            unit.clear_messages(context.actor.id)
            record_audit(unit, context, "CONVERSATION_RESET", context.actor.id, "Messages cleared; authoritative applications retained")
        return ResetResult()

    def request_review(self, context: CallContext, input: SupportInput) -> SupportRequest:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.transaction() as unit:
            if input.application_id is not None:
                unit.application(input.application_id, context.actor)

            def action() -> SupportRequest:
                request = SupportRequest(
                    id=new_id(), customer_id=context.actor.id, application_id=input.application_id,
                    message=input.message, created_at=utc_now(),
                    message_ids=[message.id for message in unit.messages(context.actor.id)],
                )
                unit.add_support_request(request)
                record_audit(unit, context, "HUMAN_ASSISTANCE_REQUESTED", input.application_id or context.actor.id, "Simulated assistance recorded; no submission or external contact")
                return request

            return unit.idempotent(context.actor, str(input.idempotency_key), "support:request", input, SupportRequest, action)