"""Owned-loan indicative early-repayment simulations; no payment execution."""

from src.core.catalogue import Catalogue
from src.core.context import CallContext
from src.models.banking import RepaymentQuote, Role
from src.models.requests import EarlyRepaymentInput
from src.observability.audit import record_audit
from src.security.permissions import require_role
from src.services.financial_calculations.engine import simulate_repayment
from src.storage.application_db.repository import Repository


class LoanServicingService:
    def __init__(self, repository: Repository, catalogue: Catalogue):
        self.repository = repository
        self.catalogue = catalogue

    def simulate(self, context: CallContext, loan_id: str, input: EarlyRepaymentInput) -> RepaymentQuote:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.transaction() as unit:
            loan = unit.loan(loan_id, context.actor.id)
            quote = simulate_repayment(loan, input.repayment, self.catalogue.rules.early_repayment_fee_percent, self.catalogue.rules.version)
            record_audit(unit, context, "EARLY_REPAYMENT_SIMULATED", loan.id, "Indicative partial repayment only; no transaction executed")
            return quote