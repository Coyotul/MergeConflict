"""Loan Pricing & Simulation use cases, exposed to the AI orchestrator as tools:

  calculate_loan_offer        -> LoanOffer
  simulate_early_repayment    -> EarlyRepaymentResult
  compare_refinancing_options -> RefinancingComparison

All arithmetic happens in src/services/financial_calculations and src/rules/pricing; this
module loads versioned configuration, composes the rules and records assumptions. Invalid
input returns status "invalid" with typed errors instead of raising.
"""

import json
from datetime import date
from decimal import ROUND_CEILING, Decimal
from functools import lru_cache
from pathlib import Path

from src.rules.pricing.rules import (PricingRuleError, ProductConfig, RateQuote, early_repayment_fee,
                                     insurance_premium, quote_rate, validate_limits)
from src.services.financial_calculations.calculations import (CENT, RatePeriod, Schedule, annual_percentage_rate,
                                                              build_schedule, money, reschedule_after_prepayment)

from .models import (Affordability, CalcError, EarlyRepaymentRequest, EarlyRepaymentResult, FeeLine,
                     LoanOffer, LoanOfferRequest, OfferTotals, RefinancingComparison, RefinancingRequest)

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
ZERO = Decimal("0.00")


@lru_cache
def load_product(product_id: str) -> ProductConfig:
    path = CONFIG_DIR / "products" / f"{product_id}.json"
    if not path.is_file():
        raise PricingRuleError("UNKNOWN_PRODUCT", f"unknown product {product_id!r}")
    return ProductConfig.model_validate_json(path.read_text(encoding="utf-8"))


@lru_cache
def _rules_config(name: str) -> dict:
    return json.loads((CONFIG_DIR / "rules" / f"{name}.json").read_text(encoding="utf-8"))


def index_value(index: str, on: date) -> Decimal:
    if index != "IRCC":
        raise PricingRuleError("INDEX_UNAVAILABLE", f"unsupported index {index!r}")
    quarter = f"{on.year}-Q{(on.month - 1) // 3 + 1}"
    values = _rules_config("ircc")["values_by_applied_quarter"]
    if quarter not in values:
        raise PricingRuleError("INDEX_UNAVAILABLE", f"no IRCC value configured for {quarter}")
    return Decimal(values[quarter])


def affordability(monthly_payment: Decimal, other_payments: Decimal, net_income: Decimal | None,
                  currency: str, first_home: bool = False) -> Affordability | None:
    if net_income is None:
        return None
    limits = _rules_config("affordability")["max_debt_service_ratio"]
    key = ("RON" if currency == "RON" else "FX") + ("_first_home" if first_home else "")
    limit = Decimal(limits[key])
    ratio = ((monthly_payment + other_payments) / net_income).quantize(Decimal("0.0001"))
    return Affordability(debt_service_ratio=ratio, limit=limit, within_limit=ratio <= limit)


# --------------------------------------------------------------------------- loan offer

def calculate_loan_offer(request: LoanOfferRequest) -> LoanOffer:
    try:
        return _calculate_offer(request)
    except PricingRuleError as exc:
        return LoanOffer(status="invalid", errors=[CalcError(code=exc.code, message=str(exc))],
                         product_id=request.product_id, request=request)


def _calculate_offer(request: LoanOfferRequest) -> LoanOffer:
    product = load_product(request.product_id)
    on = request.simulation_date or date.today()
    amount, months = money(request.amount), request.term_months
    validate_limits(product, amount, months, request.repayment_method)
    if request.with_insurance and product.insurance is None:
        raise PricingRuleError("INSURANCE_NOT_OFFERED", "this product has no optional insurance")

    index = (index_value(product.interest.index, on)
             if product.interest.type == "fixed_then_variable" else None)
    rate = quote_rate(product, salary_account=request.salary_account, with_insurance=request.with_insurance,
                      base_annual_rate=request.base_annual_rate,
                      fixed_period_months=request.fixed_period_months, index_value=index)
    if rate.fixed_rate_months is not None and rate.fixed_rate_months >= months:
        raise PricingRuleError("TERM_TOO_SHORT", "the term must be longer than the fixed-rate period")

    fees = [FeeLine(code=f.code, amount=money(f.fixed), financed=f.financed) for f in product.upfront_fees]
    premium = ZERO
    if request.with_insurance:
        premium = insurance_premium(product, amount, months)
        fees.append(FeeLine(code=product.insurance.code, amount=premium, financed=product.insurance.financed))
    financed = sum((f.amount for f in fees if f.financed), ZERO)
    separate = sum((f.amount for f in fees if not f.financed), ZERO)
    net_paid_out = amount - financed
    if net_paid_out <= 0:
        raise PricingRuleError("AMOUNT_TOO_SMALL", "financed fees exceed the credit amount")

    schedule = build_schedule(amount, months, rate.rate_periods, request.repayment_method, product.monthly_charges)
    totals = schedule.totals()
    repayments = totals.total_due

    # DAE: amount actually available to the customer at t=0 against every scheduled payment.
    # Fees paid separately reduce what the customer effectively receives; insurance excluded
    # from the DAE (when configured so) is added back.
    net_for_dae = net_paid_out - separate
    if request.with_insurance and not product.insurance.included_in_dae:
        net_for_dae += premium
    dae = annual_percentage_rate(net_for_dae, [row.total_due for row in schedule.rows])

    after_fixed = None
    if rate.fixed_rate_months is not None:
        after_fixed = schedule.rows[rate.fixed_rate_months].total_due

    offer = LoanOffer(
        status="ok", product_id=product.product_id, product_version=product.version, currency=product.currency,
        request=request, rate=rate, fees=fees, net_amount_paid_out=net_paid_out,
        first_monthly_payment=schedule.rows[0].total_due, monthly_payment_after_fixed_period=after_fixed,
        totals=OfferTotals(interest=totals.interest, monthly_charges=totals.charges, repayments=repayments,
                           fees_paid_separately=separate, total_payable=repayments + separate,
                           total_cost_of_credit=repayments + separate - net_paid_out),
        dae=dae, schedule=schedule,
        affordability=affordability(schedule.rows[0].total_due, request.existing_monthly_debt_payments,
                                    request.net_monthly_income, product.currency, request.first_home),
        assumptions=_offer_assumptions(product, request, rate, on))

    if request.property_value is not None:
        offer.loan_to_value_percent = (amount / request.property_value * 100).quantize(CENT)
        if product.max_loan_to_value_percent and offer.loan_to_value_percent > product.max_loan_to_value_percent:
            offer.warnings.append(f"LTV_ABOVE_LIMIT: maximum {product.max_loan_to_value_percent}%")
    if product.kind == "mortgage":
        offer.warnings.append("DAE_INCOMPLETE: valuation and property insurance are not modelled")
    return offer


def _offer_assumptions(product: ProductConfig, request: LoanOfferRequest, rate: RateQuote, on: date) -> list[str]:
    items = [f"Product {product.product_id} version {product.version} (synthetic parameters).",
             f"Simulation date {on.isoformat()}; the credit is paid out in full on that date.",
             "Instalments are monthly; DAE uses equal months of 1/12 year (OUG 50/2010, Annex 1).",
             "Amounts are rounded to 0.01 per instalment; the last instalment absorbs rounding."]
    if rate.base_annual_rate is not None:
        chosen = "provided" if request.base_annual_rate is not None else "product minimum (no risk-based rate provided)"
        items.append(f"Base rate {rate.base_annual_rate}% ({chosen}); fixed for the whole term.")
    if rate.fixed_rate_months is not None:
        items.append(f"Fixed rate for {rate.fixed_rate_months} months, then {product.interest.index} "
                     f"{rate.index_value}% + margin {rate.margin}%; the index is assumed to stay at its current value.")
    if request.net_monthly_income is not None:
        items.append("Affordability uses the declared net monthly income and existing payments, unverified.")
    return items


# --------------------------------------------------------------------------- early repayment

def simulate_early_repayment(request: EarlyRepaymentRequest) -> EarlyRepaymentResult:
    try:
        return _simulate_early_repayment(request)
    except PricingRuleError as exc:
        return EarlyRepaymentResult(status="invalid", errors=[CalcError(code=exc.code, message=str(exc))])


def _simulate_early_repayment(request: EarlyRepaymentRequest) -> EarlyRepaymentResult:
    offer = calculate_loan_offer(request.loan)
    if offer.status != "ok":
        return EarlyRepaymentResult(status="invalid", errors=offer.errors)
    product = load_product(request.loan.product_id)
    schedule, rate = offer.schedule, offer.rate
    last = schedule.rows[-1].month
    if not 1 <= request.after_month < last:
        raise PricingRuleError("MONTH_OUT_OF_RANGE", f"after_month must be between 1 and {last - 1}")

    balance = schedule.rows[request.after_month - 1].balance_after
    amount = balance if request.amount is None else money(request.amount)
    if amount > balance:
        raise PricingRuleError("AMOUNT_ABOVE_BALANCE", f"the outstanding balance is {balance}")
    full = amount == balance
    new = reschedule_after_prepayment(schedule, request.after_month, amount, request.option,
                                      rate.rate_periods, product.monthly_charges, charge_base=schedule.opening_balance)

    old_rows = [r for r in schedule.rows if r.month > request.after_month]
    new_rows = new.rows if new else []
    fixed_end = rate.fixed_rate_months or last
    in_fixed = request.after_month < fixed_end
    interest_saved = _interest(old_rows) - _interest(new_rows)
    interest_saved_fixed = (_interest([r for r in old_rows if r.month <= fixed_end])
                            - _interest([r for r in new_rows if r.month <= fixed_end]))
    charges_saved = sum((r.charges for r in old_rows), ZERO) - sum((r.charges for r in new_rows), ZERO)
    fee = early_repayment_fee(product, amount=amount, months_left=last - request.after_month,
                              in_fixed_rate_period=in_fixed, interest_saved_in_fixed_period=interest_saved_fixed)

    assumptions = list(offer.assumptions) + [
        f"Repayment made right after instalment {request.after_month}, so no interest has accrued since.",
        "Insurance premiums already paid are not refunded in this simulation.",
    ]
    if full:
        assumptions.append("A real full repayment must use the bank's authoritative settlement amount for that date.")
    return EarlyRepaymentResult(
        status="ok", full_repayment=full, outstanding_balance=balance, amount_repaid=amount,
        early_repayment_fee=fee, total_to_pay_now=amount + fee,
        previous_monthly_payment=old_rows[0].total_due,
        new_monthly_payment=new_rows[0].total_due if new_rows else None,
        previous_last_month=last, new_last_month=new_rows[-1].month if new_rows else request.after_month,
        interest_saved=interest_saved, charges_saved=charges_saved,
        net_saving=interest_saved + charges_saved - fee, new_schedule=new, assumptions=assumptions)


def _interest(rows) -> Decimal:
    return sum((r.interest for r in rows), ZERO)


# --------------------------------------------------------------------------- refinancing

def compare_refinancing_options(request: RefinancingRequest) -> RefinancingComparison:
    try:
        return _compare_refinancing(request)
    except PricingRuleError as exc:
        return RefinancingComparison(status="invalid", errors=[CalcError(code=exc.code, message=str(exc))])


def _compare_refinancing(request: RefinancingRequest) -> RefinancingComparison:
    product = load_product(request.product_id)
    warnings = []
    current_monthly, current_total, balances, switch_fees = ZERO, ZERO, ZERO, ZERO
    for loan in request.existing_loans:
        schedule = build_schedule(loan.outstanding_balance, loan.remaining_months,
                                  [RatePeriod(start_month=1, annual_rate=loan.annual_rate)])
        monthly = schedule.rows[0].total_due + money(loan.monthly_charges)
        if loan.declared_monthly_payment is not None and abs(loan.declared_monthly_payment - monthly) > 1:
            warnings.append(f"PAYMENT_MISMATCH: {loan.label} declared {loan.declared_monthly_payment}, "
                            f"computed {monthly} from balance, rate and remaining term")
        current_monthly += monthly
        current_total += schedule.totals().total_due + money(loan.monthly_charges) * loan.remaining_months
        balances += money(loan.outstanding_balance)
        switch_fees += money(loan.outstanding_balance * loan.early_repayment_fee_percent / 100)

    # The new loan must pay out: all balances + early repayment fees + extra cash, on top of the
    # fees and insurance it finances itself.
    needed = balances + switch_fees + money(request.extra_cash)
    amount = _gross_up(product, needed, request.term_months, request.with_insurance)
    offer = calculate_loan_offer(LoanOfferRequest(
        product_id=request.product_id, amount=amount, term_months=request.term_months,
        repayment_method=request.repayment_method, salary_account=request.salary_account,
        with_insurance=request.with_insurance, base_annual_rate=request.base_annual_rate,
        simulation_date=request.simulation_date, net_monthly_income=request.net_monthly_income,
        existing_monthly_debt_payments=request.other_monthly_debt_payments))
    if offer.status != "ok":
        return RefinancingComparison(status="invalid", errors=offer.errors, warnings=warnings)

    new_monthly = offer.first_monthly_payment
    current_cost = current_total - balances
    # Everything paid on the new loan beyond the old balances and the extra cash received.
    new_cost = offer.totals.total_payable - balances - money(request.extra_cash)
    lower_monthly, lower_cost = new_monthly < current_monthly, new_cost < current_cost
    outcome = {(True, True): "LOWER_MONTHLY_LOWER_TOTAL_COST", (True, False): "LOWER_MONTHLY_HIGHER_TOTAL_COST",
               (False, True): "HIGHER_MONTHLY_LOWER_TOTAL_COST",
               (False, False): "HIGHER_MONTHLY_HIGHER_TOTAL_COST"}[(lower_monthly, lower_cost)]
    assumptions = list(offer.assumptions) + [
        "Current loans are modelled as fixed-rate annuities from their balance, rate and remaining term.",
        "Early repayment fees of current loans are financed by the new loan.",
    ]
    if request.extra_cash > 0:
        assumptions.append("Costs exclude the extra cash itself, which the customer receives.")
    return RefinancingComparison(
        status="ok", current_monthly_payment=current_monthly, new_monthly_payment=new_monthly,
        monthly_difference=new_monthly - current_monthly,
        current_remaining_months=max(loan.remaining_months for loan in request.existing_loans),
        new_term_months=request.term_months, early_repayment_fees_on_current_loans=switch_fees,
        new_loan_amount=amount, current_cost_of_credit=current_cost, new_cost_of_credit=new_cost,
        cost_difference=new_cost - current_cost, outcome=outcome, new_offer=offer,
        warnings=warnings + offer.warnings, assumptions=assumptions)


def _gross_up(product: ProductConfig, needed: Decimal, months: int, with_insurance: bool) -> Decimal:
    """Smallest credit amount whose payout, after financed fees and insurance, covers `needed`."""
    financed_fixed = sum((money(f.fixed) for f in product.upfront_fees if f.financed), ZERO)
    share = Decimal(0)
    if with_insurance and product.insurance and product.insurance.financed:
        share = product.insurance.single_premium_percent_per_month / 100 * months
    amount = ((needed + financed_fixed) / (1 - share)).quantize(CENT, rounding=ROUND_CEILING)
    while with_insurance and amount - financed_fixed - insurance_premium(product, amount, months) < needed:
        amount += CENT  # premium rounding can leave the payout a cent short
    return amount
