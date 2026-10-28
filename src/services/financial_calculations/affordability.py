"""Decimal-safe indicative repayments and debt-service reconciliation."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, localcontext

from src.models.eligibility import DebtKind, DebtObligation, PricingScenario, RepaymentType


CENT = Decimal("0.01")


class FinancialInputError(ValueError):
    """Evidence is incomplete or contradictory; never silently substitute zero."""


def money_round(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def proposed_monthly_debt(scenario: PricingScenario) -> Decimal:
    """Principal already includes financed costs; add recurring costs only once.

    For decreasing payments, assess the highest (first) monthly obligation.
    This is an indicative monthly model, not a contractual day-count schedule.
    """
    if scenario.repayment_type == RepaymentType.UNEQUAL:
        raise FinancialInputError("Unequal custom quotes need an authoritative maximum payment.")
    with localcontext() as context:
        context.prec = 40
        principal = scenario.principal_ron
        months = Decimal(scenario.term_months)
        monthly_rate = scenario.annual_interest_percent / Decimal("1200")
        if monthly_rate == 0:
            installment = principal / months
        elif scenario.repayment_type == RepaymentType.DECREASING:
            installment = principal / months + principal * monthly_rate
        else:
            installment = principal * monthly_rate / (
                Decimal("1") - (Decimal("1") + monthly_rate) ** -scenario.term_months
            )
        return money_round(installment + scenario.monthly_fee_ron + scenario.monthly_insurance_ron)


def liability_monthly_debt(debt: DebtObligation, revolving_factor: Decimal) -> Decimal:
    if not debt.active:
        return Decimal("0.00")
    if debt.currency != "RON":
        raise FinancialInputError("Foreign-currency obligations need reviewed conversion evidence.")
    if debt.kind == DebtKind.REVOLVING:
        if debt.credit_limit is None:
            raise FinancialInputError("A revolving facility requires its granted limit.")
        if revolving_factor < Decimal("0.03"):
            raise FinancialInputError("Revolving factor cannot be below the regulatory floor.")
        floor = (debt.credit_limit * revolving_factor).quantize(CENT, rounding=ROUND_CEILING)
        return max(floor, debt.monthly_payment or Decimal("0"), debt.maximum_monthly_payment or Decimal("0"))
    if debt.repayment_type != RepaymentType.EQUAL:
        if debt.maximum_monthly_payment is None:
            raise FinancialInputError("Unequal installments require the highest monthly obligation.")
        if debt.monthly_payment is not None and debt.maximum_monthly_payment < debt.monthly_payment:
            raise FinancialInputError("Reported maximum payment is below the current payment.")
        return debt.maximum_monthly_payment
    if debt.monthly_payment is None:
        raise FinancialInputError("An active installment loan needs a monthly payment.")
    return max(debt.monthly_payment, debt.maximum_monthly_payment or Decimal("0"))


def reconcile_monthly_debt(
    bureau: tuple[DebtObligation, ...],
    internal: tuple[DebtObligation, ...],
    revolving_factor: Decimal,
) -> Decimal:
    """Deduplicate canonical liability IDs, never guess matches by amount/name.

    Conflicting copies require review; choosing a convenient lower amount is unsafe.
    """
    liabilities: dict[str, DebtObligation] = {}
    for debt in bureau + internal:
        previous = liabilities.get(debt.liability_id)
        if previous is not None and previous != debt:
            raise FinancialInputError("Conflicting reports for a canonical liability.")
        liabilities[debt.liability_id] = debt
    return sum(
        (liability_monthly_debt(debt, revolving_factor) for debt in liabilities.values()),
        start=Decimal("0.00"),
    )


def within_dti_limit(total_debt: Decimal, net_income: Decimal, limit: Decimal) -> bool:
    if net_income <= 0:
        return False
    # Compare exact money before any percentage rounding or repeating division.
    return total_debt <= net_income * limit