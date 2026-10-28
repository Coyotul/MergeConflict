"""Owner-filtered in-app updates. No email, SMS or bank contact is performed."""

from src.core.context import CallContext
from src.core.errors import DomainError
from src.models.banking import LoanApplication, Notification, Role
from src.models.common import new_id, utc_now
from src.models.requests import NotificationInput
from src.observability.audit import record_audit
from src.security.permissions import require_role
from src.storage.application_db.repository import Repository, UnitOfWork


def workflow_notification(unit: UnitOfWork, application: LoanApplication, title: str, text: str) -> None:
    unit.save_notification(Notification(
        id=new_id(), customer_id=application.customer_id, application_id=application.id,
        title=title, text=text, at=utc_now(), mandatory=True,
    ))


class NotificationService:
    def __init__(self, repository: Repository):
        self.repository = repository

    def list(self, context: CallContext) -> list[Notification]:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.read() as unit:
            return unit.notifications(context.actor.id)

    def mark_read(self, context: CallContext) -> list[Notification]:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.transaction() as unit:
            notifications = unit.notifications(context.actor.id)
            for notification in notifications:
                notification.read = True
                unit.save_notification(notification)
            record_audit(unit, context, "NOTIFICATIONS_READ", context.actor.id, "Own in-app notifications marked read")
            return notifications

    def create(self, context: CallContext, input: NotificationInput) -> Notification:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.transaction() as unit:
            if input.application_id is not None:
                unit.application(input.application_id, context.actor)

            def action() -> Notification:
                if not unit.consent(context.actor.id).notifications:
                    raise DomainError("CONSENT_REQUIRED", "Optional notifications are disabled by the customer.", 403)
                notification = Notification(
                    id=new_id(), customer_id=context.actor.id, application_id=input.application_id,
                    title=input.title, text=input.text, at=utc_now(),
                )
                unit.save_notification(notification)
                record_audit(unit, context, "CUSTOMER_NOTIFICATION_CREATED", input.application_id or context.actor.id, "Synthetic self-notification recorded")
                return notification

            return unit.idempotent(context.actor, str(input.idempotency_key), "notification:create", input, Notification, action)