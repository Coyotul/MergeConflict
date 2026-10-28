"""Pure Decimal financial calculations, independent of HTTP, storage and AI."""

import re
from decimal import Decimal, ROUND_HALF_UP, localcontext

from src.core.errors import DomainError
from src.models.banking import Loan, LoanQuote, PaymentRow, RefinanceQuote, RepaymentQuote


CENT = Decimal("0.01")
ZERO = Decimal("0")
MAX_AMOUNT = Decimal("10000000")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def value(input: str | Decimal, label: str, allow_zero: bool = False) -> Decimal:
    if isinstance(input, str):
        if not re.fullmatch(r"[0-9]+(\.[0-9]{1,2})?", input):
            raise DomainError("VALIDATION_ERROR", f"{label} must be a decimal string.")
        number = Decimal(input)
    elif isinstance(input, Decimal):
        number = input
    else:
        raise DomainError("VALIDATION_ERROR", f"{label} must not be a floating-point number.")
    if not number.is_finite() or number > MAX_AMOUNT or number < 0 or (not allow_zero and number == 0):
        raise DomainError("VALIDATION_ERROR", f"{label} is outside the supported range.")
    if number != cents(number):
        raise DomainError("VALIDATION_ERROR", f"{label} may have at most two decimal places.")
    return number


def validate_months(months: int) -> None:
    if type(months) is not int or months < 1 or months > 600:
        raise DomainError("VALIDATION_ERROR", "Duration must be between 1 and 600 whole months.")


def monthly_rate(annual_rate: str | Decimal) -> Decimal:
    rate = value(annual_rate, "Annual interest rate", allow_zero=True)
    if rate > 100:
        raise DomainError("VALIDATION_ERROR", "Annual interest must not exceed 100%.")
    return rate / Decimal("1200")


def schedule_for(
    principal: Decimal, rate: Decimal, payment: Decimal, max_months: int, fixed_term: bool
) -> list[PaymentRow]:
    schedule = []
    balance = cents(principal)
    for month in range(1, max_months + 1):
        if balance <= 0:
            break
        interest = cents(balance * rate)
        if payment <= interest:
            raise DomainError("VALIDATION_ERROR", "The payment does not cover the monthly interest.")
        due = balance + interest if fixed_term and month == max_months else min(payment, balance + interest)
        repaid = cents(due - interest)
        balance = cents(balance - repaid)
        schedule.append(PaymentRow(month=month, payment=due, principal=repaid, interest=interest, balance=balance))
    if balance > 0:
        raise DomainError("VALIDATION_ERROR", "The schedule exceeds the supported repayment duration.")
    return schedule


def assemble(
    principal: Decimal, annual_rate: Decimal, schedule: list[PaymentRow],
    installment: Decimal, fee: Decimal, insurance: Decimal,
) -> LoanQuote:
    interest = sum((row.interest for row in schedule), ZERO)
    total = sum((row.payment for row in schedule), fee) + insurance * len(schedule)
    return LoanQuote(
        amount=cents(principal), annual_rate=annual_rate, months=len(schedule), installment=installment,
        monthly_payment=installment + insurance, fee=fee, monthly_insurance=insurance,
        interest_cost=interest, total_cost=total, schedule=schedule,
        assumptions=[
            "Synthetic fixed nominal annual interest; monthly annuity; no external bank pricing.",
            "RON amounts rounded HALF_UP to cents each month; the last payment reconciles the balance.",
            "Fees are one-off and not financed; insurance is added to each monthly payment.",
            "No APR, tax, arrears, daily accrued interest or authoritative payoff quotation is calculated.",
        ],
    )


def calculate_loan(
    amount: str | Decimal, annual_rate: str | Decimal, months: int,
    fee: str | Decimal = "0", insurance: str | Decimal = "0",
) -> LoanQuote:
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_UP
        validate_months(months)
        principal = value(amount, "Loan amount")
        annual = value(annual_rate, "Annual interest rate", allow_zero=True)
        rate = monthly_rate(annual)
        installment = cents(
            principal / months if rate == 0 else principal * rate / (1 - (1 + rate) ** -months)
        )
        if installment <= 0:
            raise DomainError("VALIDATION_ERROR", "The amount is too small for this duration.")
        return assemble(
            principal, annual, schedule_for(principal, rate, installment, months, True), installment,
            value(fee, "Fee", allow_zero=True), value(insurance, "Insurance", allow_zero=True),
        )


def simulate_repayment(loan: Loan, repayment: str, fee_percent: Decimal, policy_version: str) -> RepaymentQuote:
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_UP
        paid = value(repayment, "Repayment")
        principal = value(loan.principal, "Principal")
        if paid >= principal:
            raise DomainError(
                "SETTLEMENT_QUOTE_REQUIRED",
                "Full repayment needs an authoritative bank settlement quote; principal is not a payoff amount.",
                409,
            )
        percent = value(fee_percent, "Repayment fee percentage", allow_zero=True)
        if percent > 100:
            raise DomainError("VALIDATION_ERROR", "The repayment fee must not exceed 100%.")
        new_principal = cents(principal - paid)
        current = calculate_loan(principal, loan.annual_rate, loan.remaining_months)
        reduced_payment = calculate_loan(new_principal, loan.annual_rate, loan.remaining_months)
        schedule = schedule_for(new_principal, monthly_rate(loan.annual_rate), current.installment, loan.remaining_months, False)
        reduced_term = assemble(new_principal, loan.annual_rate, schedule, current.installment, ZERO, ZERO)
        early_fee = cents(paid * percent / 100)
        return RepaymentQuote(
            current=current, reduced_payment=reduced_payment, reduced_term=reduced_term,
            repayment=paid, new_principal=new_principal, early_fee=early_fee,
            payment_savings=current.monthly_payment - reduced_payment.monthly_payment,
            interest_savings=current.interest_cost - reduced_term.interest_cost - early_fee,
            months_saved=loan.remaining_months - reduced_term.months, policy_version=policy_version,
            assumptions=[
                f"Fictional early-repayment fee: {percent}% of the repayment amount.",
                "Partial repayment only, based on synthetic outstanding principal and a fixed rate.",
                "Interest savings use the shorter-term scenario and subtract the early-repayment fee.",
                "No money is transferred, no debt is closed and no authoritative payoff is returned.",
            ],
        )


def compare_refinancing(
    loans: list[Loan], annual_rate: Decimal, months: int, fee: Decimal, policy_version: str
) -> RefinanceQuote:
    if not loans:
        raise DomainError("VALIDATION_ERROR", "Select at least one existing loan.")
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_UP
        quotes = [calculate_loan(loan.principal, loan.annual_rate, loan.remaining_months) for loan in loans]
        principal = sum((q.amount for q in quotes), ZERO)
        current_monthly = sum((q.monthly_payment for q in quotes), ZERO)
        current_total = sum((q.total_cost for q in quotes), ZERO)
        new_quote = calculate_loan(principal, annual_rate, months, fee)
        new_quote.policy_version = policy_version
        return RefinanceQuote(
            principal=principal, new_quote=new_quote, current_monthly=current_monthly, current_total=current_total,
            monthly_savings=current_monthly - new_quote.monthly_payment,
            total_savings=current_total - new_quote.total_cost, policy_version=policy_version,
            assumptions=[
                "Synthetic outstanding principal is used, not bank payoff statements.",
                f"Fictional refinancing nominal annual rate {annual_rate}%, one-off fee {fee} RON.",
                "Existing-loan closure fees, daily accrued interest and settlement costs are unknown and excluded.",
                "A lower monthly payment can increase total repayment. No refinancing is executed.",
            ],
        )