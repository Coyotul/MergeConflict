"""Request and result models of the Loan Pricing & Simulation service.

Every result is indicative: it states its assumptions and never replaces the bank's
authoritative pricing or settlement figures.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from src.rules.pricing.rules import RateQuote, SalaryAccount
from src.services.financial_calculations.calculations import PrepaymentOption, RepaymentMethod, Schedule

DISCLAIMER = ("Indicative simulation based on synthetic product parameters and the stated assumptions. "
              "It is not an offer, an approval or an authoritative settlement amount.")


class CalcError(BaseModel):
    code: str
    message: str


class LoanOfferRequest(BaseModel):
    product_id: str
    amount: Decimal = Field(gt=0, description="Total credit amount, including financed fees and insurance")
    term_months: int = Field(gt=0)
    repayment_method: RepaymentMethod = RepaymentMethod.ANNUITY
    salary_account: SalaryAccount = SalaryAccount.NONE
    with_insurance: bool = False
    base_annual_rate: Decimal | None = Field(None, description="Risk-based rate before discounts; product minimum if omitted")
    fixed_period_months: int | None = None
    simulation_date: date | None = None
    net_monthly_income: Decimal | None = Field(None, gt=0)
    existing_monthly_debt_payments: Decimal = Field(Decimal("0"), ge=0)
    first_home: bool = False
    property_value: Decimal | None = Field(None, gt=0)


class FeeLine(BaseModel):
    code: str
    amount: Decimal
    financed: bool


class Affordability(BaseModel):
    debt_service_ratio: Decimal  # all monthly credit payments / net monthly income
    limit: Decimal
    within_limit: bool
    note: str = "Indicative check against BNR Regulation 17/2012; not an eligibility decision."


class OfferTotals(BaseModel):
    interest: Decimal
    monthly_charges: Decimal
    repayments: Decimal  # sum of all scheduled payments
    fees_paid_separately: Decimal
    total_payable: Decimal  # repayments + fees paid separately
    total_cost_of_credit: Decimal  # total payable - net amount paid out


class LoanOffer(BaseModel):
    status: Literal["ok", "invalid"]
    errors: list[CalcError] = []
    indicative: bool = True
    disclaimer: str = DISCLAIMER
    product_id: str
    product_version: str | None = None
    currency: str | None = None
    request: LoanOfferRequest
    rate: RateQuote | None = None
    fees: list[FeeLine] = []
    net_amount_paid_out: Decimal | None = None
    first_monthly_payment: Decimal | None = None
    monthly_payment_after_fixed_period: Decimal | None = None
    totals: OfferTotals | None = None
    dae: Decimal | None = None
    loan_to_value_percent: Decimal | None = None
    affordability: Affordability | None = None
    schedule: Schedule | None = None
    assumptions: list[str] = []
    warnings: list[str] = []


class EarlyRepaymentRequest(BaseModel):
    loan: LoanOfferRequest
    after_month: int = Field(ge=1, description="Instalments already paid")
    amount: Decimal | None = Field(None, gt=0, description="Principal to repay; omit for full repayment")
    option: PrepaymentOption = PrepaymentOption.REDUCE_INSTALMENT


class EarlyRepaymentResult(BaseModel):
    status: Literal["ok", "invalid"]
    errors: list[CalcError] = []
    indicative: bool = True
    disclaimer: str = DISCLAIMER
    full_repayment: bool | None = None
    outstanding_balance: Decimal | None = None
    amount_repaid: Decimal | None = None
    early_repayment_fee: Decimal | None = None
    total_to_pay_now: Decimal | None = None
    previous_monthly_payment: Decimal | None = None
    new_monthly_payment: Decimal | None = None
    previous_last_month: int | None = None
    new_last_month: int | None = None
    interest_saved: Decimal | None = None
    charges_saved: Decimal | None = None
    net_saving: Decimal | None = None  # interest + charges saved - fee
    new_schedule: Schedule | None = None
    assumptions: list[str] = []


class ExistingLoan(BaseModel):
    label: str
    outstanding_balance: Decimal = Field(gt=0)
    annual_rate: Decimal = Field(ge=0)
    remaining_months: int = Field(gt=0)
    monthly_charges: Decimal = Field(Decimal("0"), ge=0)
    early_repayment_fee_percent: Decimal = Field(Decimal("0"), ge=0)
    declared_monthly_payment: Decimal | None = Field(None, gt=0)


class RefinancingRequest(BaseModel):
    existing_loans: list[ExistingLoan] = Field(min_length=1)
    product_id: str = "refinancing_fixed"
    term_months: int = Field(gt=0)
    repayment_method: RepaymentMethod = RepaymentMethod.ANNUITY
    salary_account: SalaryAccount = SalaryAccount.NONE
    with_insurance: bool = False
    base_annual_rate: Decimal | None = None
    extra_cash: Decimal = Field(Decimal("0"), ge=0)
    simulation_date: date | None = None
    net_monthly_income: Decimal | None = Field(None, gt=0)
    other_monthly_debt_payments: Decimal = Field(Decimal("0"), ge=0)


class RefinancingComparison(BaseModel):
    status: Literal["ok", "invalid"]
    errors: list[CalcError] = []
    indicative: bool = True
    disclaimer: str = DISCLAIMER
    current_monthly_payment: Decimal | None = None
    new_monthly_payment: Decimal | None = None
    monthly_difference: Decimal | None = None  # new - current (negative = lower)
    current_remaining_months: int | None = None
    new_term_months: int | None = None
    early_repayment_fees_on_current_loans: Decimal | None = None
    new_loan_amount: Decimal | None = None
    current_cost_of_credit: Decimal | None = None  # remaining interest + charges
    new_cost_of_credit: Decimal | None = None  # new interest, fees, insurance + switching fees
    cost_difference: Decimal | None = None  # new - current (negative = cheaper)
    outcome: str | None = None  # e.g. LOWER_MONTHLY_HIGHER_TOTAL_COST
    new_offer: LoanOffer | None = None
    warnings: list[str] = []
    assumptions: list[str] = []
