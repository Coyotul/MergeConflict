"""Backend-only actor and provider authorization for preliminary assessments."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.core.eligibility_errors import AccessDenied
from src.models.eligibility import (
    ApplicationSnapshot, AuthorizationRecord, AuthorizationScope, LegalBasis,
)


class ActorRole(str, Enum):
    CUSTOMER = "CUSTOMER"
    REVIEWER = "REVIEWER"
    SERVICE = "SERVICE"


@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    role: ActorRole
    customer_id: str | None = None
    permissions: frozenset[str] = frozenset()
    assigned_application_ids: frozenset[str] = frozenset()


def authorize_assessment(
    actor: ActorContext, application: ApplicationSnapshot,
    permission: str = "eligibility:assess",
) -> None:
    if permission not in actor.permissions:
        raise AccessDenied()
    if actor.role == ActorRole.CUSTOMER:
        if actor.customer_id == application.customer_id:
            return
    elif actor.role in {ActorRole.REVIEWER, ActorRole.SERVICE}:
        if application.application_id in actor.assigned_application_ids:
            return
    raise AccessDenied()


def authorization_is_valid(
    record: AuthorizationRecord | None,
    scope: AuthorizationScope,
    customer_id: str,
    now: datetime,
) -> bool:
    if record is None or record.scope != scope or record.customer_id != customer_id:
        return False
    if record.recorded_at > now or not record.notice_acknowledged:
        return False
    if record.revoked_at is not None:
        return False
    if record.expires_at is not None and record.expires_at <= now:
        return False
    if record.expires_at is not None and record.expires_at <= record.recorded_at:
        return False
    needs_consent = (
        scope == AuthorizationScope.INCOME_VERIFICATION
        or record.legal_basis == LegalBasis.CONSENT
    )
    if needs_consent and (
        record.legal_basis != LegalBasis.CONSENT
        or record.consent_recorded_at is None
        or record.consent_recorded_at > now
    ):
        return False
    return True