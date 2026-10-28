"""Session-bound adapter for the deterministic pricing engine (13b4cf2).

Only alternative terms are model arguments. All money, identity/product selection
and the simulation clock come from the owned session. No banking action occurs.
"""

import hashlib
import json
from datetime import UTC
from decimal import Decimal

from pydantic import ValidationError

from src.agent.orchestration.progress import (
    all_verified, can_calculate_offers, fingerprint, offer_input_names,
)
from src.agent.orchestration.state import SessionState
from src.agent.tools.contracts import (
    CalculateOffersInput, CalculateOffersOutput, OfferCalculationError,
)
from src.agent.tools.registry import Flow, ToolContext, ToolRegistry, ToolSpec
from src.core.errors import ToolUnavailable
from src.models.credit import CreditProduct, LoanOffer, Money
from src.models.knowledge import Product
from src.rules.pricing.rules import PricingRuleError, ProductConfig, SalaryAccount
from src.services.financial_calculations.calculations import RepaymentMethod
from src.services.pricing import service as pricing_service
from src.services.pricing.models import LoanOffer as PricedOffer, LoanOfferRequest


PRODUCT_IDS = {
    Product.personal_loan: "personal_loan_fixed",
    Product.refinancing_unsecured: "refinancing_fixed",
    Product.mortgage_casa_ta: "mortgage_fixed_then_ircc",
}
ZERO = Decimal("0.00")


def _product(code: Product) -> ProductConfig:
    try:
        return pricing_service.load_product(PRODUCT_IDS[code])
    except KeyError as error:
        raise ValueError("UNSUPPORTED_PRODUCT: no pricing mapping for selected product") from error
    except (OSError, PricingRuleError, ValidationError) as error:
        raise ToolUnavailable("Pricing configuration is unavailable; no illustrative fallback was used.") from error


def priced_catalog_product(product: CreditProduct) -> CreditProduct:
    """Use engine limits/rates for discovery instead of contradictory YAML rates.

    Keep the existing catalog's code/name/purpose metadata and wire model. This
    does not change the separate illustrative eligibility stub's rule calculation.
    """
    configured = _product(product.code)
    interest = configured.interest
    minimum_term = configured.term_months.min
    if interest.type == "fixed_then_variable":
        first = min(interest.fixed_periods, key=lambda period: period.months)
        rate = first.annual_rate
        minimum_term = max(minimum_term, first.months + 1)
        note = (f"Synthetic {configured.product_id} v{configured.version}: initial fixed rate for "
                f"{first.months} months, then {interest.index} + {interest.margin} percentage points. "
                "Future index values and omitted mortgage costs are assumptions; calculate a dated simulation.")
    else:
        rate = interest.base_annual_rate.min
        note = (f"Synthetic {configured.product_id} v{configured.version}: minimum base rate before "
                "optional discounts, not a personalized rate. Salary discounts and optional insurance "
                "are not assumed. Fees apply; calculate a dated simulation for totals and DAE.")
    return product.model_copy(update={
        "min_amount": Money(amount=configured.amount.min, currency=configured.currency),
        "max_amount": Money(amount=configured.amount.max, currency=configured.currency),
        "min_term_months": minimum_term, "max_term_months": configured.term_months.max,
        "indicative_annual_rate_percent": rate, "rate_note": note,
    })


def pricing_precondition(state: SessionState) -> str | None:
    reason = can_calculate_offers(state)
    if reason is not None:
        return reason
    if state.application.application_id is not None:
        return "application already submitted; start a separate simulation"
    if state.escalation is not None:
        return "application is awaiting human review"
    if state.application.conflicts or not all_verified(state.application):
        return "pricing requires current verified inputs with no unresolved conflicts"
    return None


def _invalid(code: str, message: str, term: int | None = None) -> CalculateOffersOutput:
    return CalculateOffersOutput(offers=[], status="invalid", errors=[
        OfferCalculationError(code=code, message=message, term_months=term),
    ])


def _money_field(ctx: ToolContext, name: str, *, optional: bool = False) -> Decimal | None:
    field = ctx.state.application.fields.get(name)
    if field is None:
        if optional:
            return None
        raise ValueError(f"Missing pricing field: {name}")
    if field.kind != "money" or isinstance(field.value, bool):
        raise ValueError(f"Invalid pricing field type: {name}")
    value = Decimal(str(field.value))
    if not value.is_finite() or value < 0:
        raise ValueError(f"Pricing field must be a finite nonnegative amount: {name}")
    return value


def _wire_offer(result: PricedOffer, ctx: ToolContext, extra: list[str]) -> LoanOffer:
    """Project engine values without recomputing instalments, interest or DAE."""
    app = ctx.state.application
    currency = result.currency
    upfront = sum((fee.amount for fee in result.fees), ZERO)
    all_charges = upfront + result.totals.monthly_charges
    assumptions = list(result.assumptions) + extra + [
        f"Net amount paid out: {result.net_amount_paid_out} {currency}; requested amount is total credit including financed costs.",
        f"DAE/APR: {result.dae}%; nominal interest is not the total cost of credit.",
        "No salary-account discount or optional insurance is assumed; annuity repayment, no first-home uplift.",
        f"Total upfront fees/premiums: {upfront} {currency}; total recurring charges: {result.totals.monthly_charges} {currency}.",
        "Fees include upfront and recurring charges over the full term. Do not add them again to total repayment or total cost.",
    ]
    for fee in result.fees:
        treatment = "financed and deducted from payout" if fee.financed else "paid separately"
        assumptions.append(f"{fee.code}: {fee.amount} {currency} ({treatment}).")
    if result.monthly_payment_after_fixed_period is not None:
        assumptions.append(
            f"Monthly payment after the initial {result.rate.fixed_rate_months} fixed-rate months: "
            f"{result.monthly_payment_after_fixed_period} {currency}, using the stated constant-index assumption."
        )
    if result.loan_to_value_percent is not None:
        assumptions.append(f"Loan-to-value: {result.loan_to_value_percent}%.")
    if result.affordability is not None:
        check = result.affordability
        assumptions.append(
            f"Simulation debt-service ratio: {check.debt_service_ratio}; limit: {check.limit}; "
            f"within limit: {str(check.within_limit).lower()}. {check.note}"
        )
        if result.monthly_payment_after_fixed_period is not None:
            assumptions.append("The service affordability ratio uses the first payment, not a stress test of later variable payments.")
    assumptions.extend(result.warnings)
    assumptions.append(result.disclaimer)
    # Rates/date/version/charges matter too: the old field-only ID could refer to
    # a different quote after a quarter or configuration change.
    identity = json.dumps({
        "inputs": fingerprint(app, offer_input_names(app)),
        "calculation": result.model_dump(mode="json", exclude={"schedule"}),
    }, sort_keys=True, separators=(",", ":"))
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return LoanOffer(
        offer_id=f"{app.product_code.value}-{result.request.term_months}m-{suffix}",
        product_code=app.product_code,
        amount=Money(amount=result.request.amount, currency=currency),
        term_months=result.request.term_months,
        annual_interest_rate_percent=result.rate.rate_periods[0].annual_rate,
        monthly_installment=Money(amount=result.first_monthly_payment, currency=currency),
        total_repayment=Money(amount=result.totals.total_payable, currency=currency),
        total_cost=Money(amount=result.totals.total_cost_of_credit, currency=currency),
        fees=Money(amount=all_charges, currency=currency),
        assumptions=assumptions, indicative=True, simulated=True,
    )


def calculate_offers(request: CalculateOffersInput, ctx: ToolContext) -> CalculateOffersOutput:
    app = ctx.state.application
    if app is None or app.product_code not in PRODUCT_IDS:
        return _invalid("UNSUPPORTED_PRODUCT", "Select a supported credit product before pricing.")
    _product(app.product_code)  # Fail closed on missing/malformed configuration.
    try:
        amount = _money_field(ctx, "amount")
        field = app.fields.get("term_months")
        if field is None or field.kind != "integer" or isinstance(field.value, bool):
            return _invalid("INVALID_PRICING_INPUT", "A valid requested term is required.")
        term = field.value
        income = _money_field(ctx, "monthly_net_income", optional=True)
        obligations = _money_field(ctx, "existing_monthly_obligations", optional=True)
        property_value = (_money_field(ctx, "property_value", optional=True)
                          if app.product_code == Product.mortgage_casa_ta else None)
        extra = []
        if income is None or income == 0 or obligations is None:
            income = None
            extra.append("Affordability is not calculated: positive income and existing obligations are not both available.")
        simulation = LoanOfferRequest(
            product_id=PRODUCT_IDS[app.product_code], amount=amount, term_months=term,
            simulation_date=ctx.now.astimezone(UTC).date(),
            net_monthly_income=income, existing_monthly_debt_payments=obligations if obligations is not None else ZERO,
            property_value=property_value, salary_account=SalaryAccount.NONE, with_insurance=False,
            repayment_method=RepaymentMethod.ANNUITY, first_home=False,
        )
    except (ValueError, ArithmeticError):
        return _invalid("INVALID_PRICING_INPUT", "Session pricing inputs are missing or invalid; correct them before retrying.")

    terms = list(dict.fromkeys([term, *(request.term_options_months or [])]))[:3]
    results = []
    errors = []
    for index, alternative in enumerate(terms):
        try:
            calculated = pricing_service.calculate_loan_offer(simulation.model_copy(update={"term_months": alternative}))
        except (OSError, ValidationError) as error:
            raise ToolUnavailable("Pricing configuration is unavailable; no illustrative fallback was used.") from error
        if calculated.status != "ok":
            errors.extend(OfferCalculationError(code=e.code, message=e.message, term_months=alternative)
                          for e in calculated.errors)
            # Never silently change the customer's primary term/amount to an alternative.
            if index == 0:
                return CalculateOffersOutput(offers=[], status="invalid", errors=errors)
        else:
            results.append(calculated)
    extra.extend(f"Alternative {e.term_months} months was not priced: {e.code}: {e.message}" for e in errors)
    return CalculateOffersOutput(offers=[_wire_offer(result, ctx, extra) for result in results], errors=errors)


def register_pricing_tool(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="calculate_loan_offer",
        description=("Calculate deterministic indicative loan offers, fees, DAE and disclosures from verified session inputs. "
                     "Only alternative terms may be supplied; rejected product limits are not silently clamped."),
        input_model=CalculateOffersInput, output_model=CalculateOffersOutput,
        model_callable=True, flows=frozenset([Flow.credit_application]),
        handler=calculate_offers, precondition=pricing_precondition,
    ))