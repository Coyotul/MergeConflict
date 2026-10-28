"""Audit changes in the same transaction as the authoritative synthetic record."""

from src.core.context import CallContext
from src.models.banking import AuditEvent
from src.models.common import new_id, utc_now
from src.storage.application_db.repository import UnitOfWork


def record_audit(unit: UnitOfWork, context: CallContext, action: str, object_id: str, result: str) -> None:
    unit.add_audit(AuditEvent(
        id=new_id(), actor_id=context.actor.id, actor=context.actor.name,
        action=action, object_id=object_id, at=utc_now(), result=result,
        correlation_id=context.correlation_id,
    ))