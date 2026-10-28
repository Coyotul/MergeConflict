"""Synthetic authorized profile, owned loans and explicit preferences."""

from src.core.context import CallContext
from src.models.banking import Consent, Customer, Loan, Role
from src.models.requests import ConsentInput
from src.observability.audit import record_audit
from src.security.permissions import require_role
from src.storage.application_db.repository import Repository


class CustomerService:
    def __init__(self, repository: Repository):
        self.repository = repository

    def profile(self, context: CallContext) -> Customer:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.read() as unit:
            return unit.customer(context.actor.id)

    def loans(self, context: CallContext) -> list[Loan]:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.read() as unit:
            return unit.loans(context.actor.id)

    def loan(self, context: CallContext, loan_id: str) -> Loan:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.read() as unit:
            return unit.loan(loan_id, context.actor.id)

    def consent(self, context: CallContext) -> Consent:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.read() as unit:
            return unit.consent(context.actor.id)

    def update_consent(self, context: CallContext, input: ConsentInput) -> Consent:
        require_role(context.actor, Role.CUSTOMER)
        consent = Consent(financial_insights=input.financial_insights, notifications=input.notifications)
        with self.repository.transaction() as unit:
            unit.save_consent(context.actor.id, consent)
            record_audit(unit, context, "CONSENT_UPDATED", context.actor.id, "Customer financial-insight and optional-notification preferences updated")
        return consent