"""Product pricing rules: product configuration model, interest rate, fees and early repayment fee.

Pure functions over a validated ProductConfig; loading the JSON files is done by
src/services/pricing/. Rates are annual nominal percentages.
"""

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

from src.services.financial_calculations.calculations import MonthlyCharge, RatePeriod, RepaymentMethod, money

HUNDRED = Decimal("100")


class SalaryAccount(str, Enum):
    NONE = "none"
    STANDARD = "standard"
    PREMIUM = "premium"


class Range(BaseModel):
    min: Decimal
    max: Decimal


class IntRange(BaseModel):
    min: int
    max: int


class Discount(BaseModel):
    code: str
    percentage_points: Decimal
    condition: str  # salary_account_standard | salary_account_premium | insurance
    description: str = ""


class FixedPeriod(BaseModel):
    months: int = Field(ge=1)
    annual_rate: Decimal


class InterestConfig(BaseModel):
    type: str  # fixed | fixed_then_variable
    base_annual_rate: Range | None = None
    discounts: list[Discount] = []
    fixed_periods: list[FixedPeriod] = []
    index: str | None = None
    margin: Decimal | None = None


class UpfrontFee(BaseModel):
    code: str
    fixed: Decimal
    financed: bool  # True: deducted from the amount paid out; False: paid separately


class InsuranceConfig(BaseModel):
    code: str
    single_premium_percent_per_month: Decimal
    financed: bool
    included_in_dae: bool


class EarlyRepaymentConfig(BaseModel):
    fee_percent_more_than_12_months_left: Decimal
    fee_percent_12_months_or_less_left: Decimal
    only_during_fixed_rate: bool
    cap_at_interest_saved: bool


class ProductConfig(BaseModel):
    product_id: str
    version: str
    name: str
    kind: str
    currency: str
    note: str = ""
    sources: list[str] = []
    amount: Range
    term_months: IntRange
    repayment_methods: list[RepaymentMethod]
    interest: InterestConfig
    upfront_fees: list[UpfrontFee] = []
    monthly_charges: list[MonthlyCharge] = []
    insurance: InsuranceConfig | None = None
    early_repayment: EarlyRepaymentConfig
    max_loan_to_value_percent: Decimal | None = None


class AppliedDiscount(BaseModel):
    code: str
    percentage_points: Decimal


class RateQuote(BaseModel):
    rate_periods: list[RatePeriod]
    base_annual_rate: Decimal | None  # before discounts (fixed products)
    discounts: list[AppliedDiscount]
    fixed_rate_months: int | None  # None: fixed for the whole term
    index_value: Decimal | None = None
    margin: Decimal | None = None


class PricingRuleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def quote_rate(product: ProductConfig, *, salary_account: SalaryAccount, with_insurance: bool,
               base_annual_rate: Decimal | None = None, fixed_period_months: int | None = None,
               index_value: Decimal | None = None) -> RateQuote:
    """Interest rate periods for a loan.

    Fixed products: base rate (risk-based, inside the product range; the minimum when not given)
    minus the discounts the customer qualifies for. Premium replaces the standard salary discount.
    Fixed-then-variable products: the chosen fixed period, then index + margin (the margin stays
    fixed for the whole contract, OUG 50/2010 art. 37).
    """
    interest = product.interest
    if interest.type == "fixed":
        rng = interest.base_annual_rate
        base = rng.min if base_annual_rate is None else Decimal(base_annual_rate)
        if not rng.min <= base <= rng.max:
            raise PricingRuleError("RATE_OUT_OF_RANGE", f"base rate must be between {rng.min}% and {rng.max}%")
        conditions = {"insurance"} if with_insurance else set()
        if salary_account == SalaryAccount.PREMIUM:
            conditions.add("salary_account_premium")
        elif salary_account == SalaryAccount.STANDARD:
            conditions.add("salary_account_standard")
        applied = [AppliedDiscount(code=d.code, percentage_points=d.percentage_points)
                   for d in interest.discounts if d.condition in conditions]
        rate = base - sum((d.percentage_points for d in applied), Decimal(0))
        return RateQuote(rate_periods=[RatePeriod(start_month=1, annual_rate=rate)], base_annual_rate=base,
                         discounts=applied, fixed_rate_months=None)

    if interest.type == "fixed_then_variable":
        options = {p.months: p for p in interest.fixed_periods}
        months = fixed_period_months or min(options)
        if months not in options:
            raise PricingRuleError("FIXED_PERIOD_NOT_OFFERED", f"fixed periods offered: {sorted(options)} months")
        if index_value is None:
            raise PricingRuleError("INDEX_UNAVAILABLE", f"{interest.index} value is required")
        variable = Decimal(index_value) + interest.margin
        return RateQuote(rate_periods=[RatePeriod(start_month=1, annual_rate=options[months].annual_rate),
                                       RatePeriod(start_month=months + 1, annual_rate=variable)],
                         base_annual_rate=None, discounts=[], fixed_rate_months=months,
                         index_value=Decimal(index_value), margin=interest.margin)

    raise PricingRuleError("UNKNOWN_INTEREST_TYPE", f"unsupported interest type {interest.type!r}")


def validate_limits(product: ProductConfig, amount: Decimal, term_months: int, method: RepaymentMethod) -> None:
    if not product.amount.min <= amount <= product.amount.max:
        raise PricingRuleError("AMOUNT_OUT_OF_RANGE",
                               f"amount must be between {product.amount.min} and {product.amount.max} {product.currency}")
    if not product.term_months.min <= term_months <= product.term_months.max:
        raise PricingRuleError("TERM_OUT_OF_RANGE",
                               f"term must be between {product.term_months.min} and {product.term_months.max} months")
    if method not in product.repayment_methods:
        raise PricingRuleError("METHOD_NOT_OFFERED", f"repayment method {method.value} is not offered")


def insurance_premium(product: ProductConfig, amount: Decimal, term_months: int) -> Decimal:
    """Single premium = amount x monthly percent x number of months."""
    if product.insurance is None:
        raise PricingRuleError("INSURANCE_NOT_OFFERED", "this product has no optional insurance")
    return money(amount * product.insurance.single_premium_percent_per_month / HUNDRED * term_months)


def early_repayment_fee(product: ProductConfig, *, amount: Decimal, months_left: int, in_fixed_rate_period: bool,
                        interest_saved_in_fixed_period: Decimal) -> Decimal:
    """Compensation for early repayment (OUG 50/2010 art. 66-69).

    Only during a fixed-rate period; at most 1% of the amount repaid when more than 12 months
    remain, 0.5% otherwise, and never more than the interest the customer would have paid
    until the fixed-rate period ends.
    """
    rule = product.early_repayment
    if rule.only_during_fixed_rate and not in_fixed_rate_period:
        return Decimal("0.00")
    percent = (rule.fee_percent_more_than_12_months_left if months_left > 12
               else rule.fee_percent_12_months_or_less_left)
    fee = money(Decimal(amount) * percent / HUNDRED)
    if rule.cap_at_interest_saved:
        fee = min(fee, money(max(interest_saved_in_fixed_period, Decimal(0))))
    return fee
