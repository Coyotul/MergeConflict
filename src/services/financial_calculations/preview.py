"""Indicative debt-ratio preview; separate from evidence-based eligibility."""

from decimal import Decimal

from src.core.catalogue import Catalogue
from src.models.banking import Actor, Assessment
from src.models.requests import LoanScenarioInput
from src.rules.eligibility.affordability import assess_affordability
from src.services.financial_calculations.engine import calculate_loan
from src.services.pricing.service import PricingService
from src.storage.application_db.repository import UnitOfWork


class EligibilityService:
    def __init__(self, catalogue: Catalogue, pricing: PricingService):
        self.catalogue = catalogue
        self.pricing = pricing

    def assess(self, unit: UnitOfWork, actor: Actor, input: LoanScenarioInput) -> Assessment:
        customer = unit.customer(actor.id)
        loans = unit.loans(actor.id)
        obligations = sum((calculate_loan(loan.principal, loan.annual_rate, loan.remaining_months).monthly_payment for loan in loans), Decimal("0"))
        return assess_affordability(
            customer.monthly_income, obligations, self.pricing.calculate(input),
            self.catalogue.rules.debt_ratio_threshold, self.catalogue.rules.version,
            [f"synthetic-customer:{customer.id}", *[f"synthetic-loan:{loan.id}" for loan in loans],
             "eligibility-policy", self.catalogue.product(input.product_id).policy_id],
        )