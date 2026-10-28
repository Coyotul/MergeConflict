"""Server-owned product pricing; callers cannot override interest, fees or rules."""

from decimal import Decimal

from src.core.catalogue import Catalogue
from src.core.errors import DomainError
from src.models.banking import LoanQuote
from src.models.requests import LoanScenarioInput
from src.services.financial_calculations.engine import calculate_loan


class PricingService:
    def __init__(self, catalogue: Catalogue):
        self.catalogue = catalogue

    def calculate(self, input: LoanScenarioInput) -> LoanQuote:
        product = self.catalogue.product(input.product_id)
        amount = Decimal(input.amount)
        if not product.min_amount <= amount <= product.max_amount or not product.min_months <= input.months <= product.max_months:
            raise DomainError("VALIDATION_ERROR", "Amount or duration is outside this synthetic product's range.")
        quote = calculate_loan(amount, product.annual_rate, input.months, product.fee, product.monthly_insurance)
        quote.policy_version = product.policy_version
        if product.id == "mortgage":
            quote.assumptions.append("Illustrative mortgage only: property valuation and down-payment rules are not implemented.")
        return quote