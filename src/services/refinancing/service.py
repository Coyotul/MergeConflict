"""Compare only owned synthetic loans using backend-configured assumptions."""

from src.core.catalogue import Catalogue
from src.core.context import CallContext
from src.core.errors import DomainError
from src.models.banking import RefinanceQuote, Role
from src.models.requests import RefinancingInput
from src.observability.audit import record_audit
from src.security.permissions import require_role
from src.services.financial_calculations.engine import compare_refinancing
from src.storage.application_db.repository import Repository


class RefinancingService:
    def __init__(self, repository: Repository, catalogue: Catalogue):
        self.repository = repository
        self.catalogue = catalogue

    def compare(self, context: CallContext, input: RefinancingInput) -> RefinanceQuote:
        require_role(context.actor, Role.CUSTOMER)
        rules = self.catalogue.rules
        if not rules.refinancing_min_months <= input.months <= rules.refinancing_max_months:
            raise DomainError("VALIDATION_ERROR", "Duration is outside the synthetic refinancing range.")
        with self.repository.transaction() as unit:
            loans = [unit.loan(loan_id, context.actor.id) for loan_id in input.loan_ids]
            quote = compare_refinancing(loans, rules.refinancing_annual_rate, input.months, rules.refinancing_fee, rules.version)
            record_audit(unit, context, "REFINANCING_COMPARED", context.actor.id, "Synthetic comparison only; no payoff or debt closure")
            return quote