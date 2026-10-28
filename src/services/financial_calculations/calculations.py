"""Deterministic loan mathematics: repayment schedules, DAE and early repayment.

Pure functions on Decimal values: no I/O, no product knowledge, no LLM. Rates are annual
nominal percentages (e.g. Decimal("5.55")). Money is rounded to 0.01 with ROUND_HALF_UP
per schedule row; the last row absorbs rounding so principal repaid equals principal lent.
"""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, localcontext
from enum import Enum

from pydantic import BaseModel, Field

CENT = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class RepaymentMethod(str, Enum):
    ANNUITY = "annuity"  # equal instalments (rate egale)
    DECREASING = "decreasing"  # equal principal, decreasing instalments (rate descrescătoare)


class RatePeriod(BaseModel):
    """Annual nominal rate (percent) applying from `start_month` until the next period starts."""

    start_month: int = Field(ge=1)
    annual_rate: Decimal = Field(ge=0)


class MonthlyCharge(BaseModel):
    """Recurring cost added to every instalment, e.g. an administration fee or life insurance."""

    code: str
    fixed: Decimal = ZERO
    percent_of_principal: Decimal = ZERO  # monthly percent of the initial principal


class ScheduleRow(BaseModel):
    month: int
    annual_rate: Decimal
    instalment: Decimal  # principal + interest
    principal: Decimal
    interest: Decimal
    charges: Decimal
    total_due: Decimal  # instalment + charges
    balance_after: Decimal


class ScheduleTotals(BaseModel):
    principal: Decimal
    interest: Decimal
    charges: Decimal
    total_due: Decimal


class Schedule(BaseModel):
    method: RepaymentMethod
    opening_balance: Decimal
    rows: list[ScheduleRow]

    def totals(self) -> ScheduleTotals:
        return ScheduleTotals(principal=sum((r.principal for r in self.rows), ZERO),
                              interest=sum((r.interest for r in self.rows), ZERO),
                              charges=sum((r.charges for r in self.rows), ZERO),
                              total_due=sum((r.total_due for r in self.rows), ZERO))


def monthly_rate(annual_rate: Decimal) -> Decimal:
    return Decimal(annual_rate) / HUNDRED / 12


def annuity_payment(principal: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    """Unrounded equal instalment: P * r / (1 - (1 + r)^-n)."""
    if months < 1:
        raise ValueError("months must be at least 1")
    with localcontext() as ctx:
        ctx.prec = 40
        r = monthly_rate(annual_rate)
        if r == 0:
            return Decimal(principal) / months
        return Decimal(principal) * r / (1 - (1 + r) ** -months)


def rate_for_month(rate_periods: list[RatePeriod], month: int) -> Decimal:
    applicable = [p for p in rate_periods if p.start_month <= month]
    if not applicable:
        raise ValueError(f"no rate period covers month {month}")
    return max(applicable, key=lambda p: p.start_month).annual_rate


def monthly_charges(charges: list[MonthlyCharge], charge_base: Decimal) -> Decimal:
    return money(sum((c.fixed + charge_base * c.percent_of_principal / HUNDRED for c in charges), ZERO))


def build_schedule(principal: Decimal, months: int, rate_periods: list[RatePeriod],
                   method: RepaymentMethod = RepaymentMethod.ANNUITY,
                   charges: list[MonthlyCharge] = (), first_month: int = 1,
                   charge_base: Decimal | None = None) -> Schedule:
    """Repayment schedule for `principal` over `months`, starting at loan month `first_month`.

    Annuity instalments are recalculated on the outstanding balance and remaining term
    whenever the rate changes (e.g. at the end of a fixed-rate period). `charge_base` is the
    initial loan principal for percentage charges; it differs from `principal` when the
    schedule restarts after a partial early repayment.
    """
    principal = Decimal(principal)
    if principal <= 0:
        raise ValueError("principal must be positive")
    if months < 1:
        raise ValueError("months must be at least 1")
    charge_amount = monthly_charges(list(charges), principal if charge_base is None else Decimal(charge_base))
    last_month = first_month + months - 1

    rows, balance = [], principal
    instalment, current_rate = None, None
    principal_part = money(principal / months)  # decreasing method
    for month in range(first_month, last_month + 1):
        rate = rate_for_month(rate_periods, month)
        if method == RepaymentMethod.ANNUITY and rate != current_rate:
            instalment = money(annuity_payment(balance, rate, last_month - month + 1))
        current_rate = rate
        interest = money(balance * monthly_rate(rate))
        if month == last_month:
            repaid = balance
        elif method == RepaymentMethod.ANNUITY:
            repaid = min(instalment - interest, balance)
        else:
            repaid = min(principal_part, balance)
        balance -= repaid
        rows.append(ScheduleRow(month=month, annual_rate=rate, instalment=repaid + interest, principal=repaid,
                                interest=interest, charges=charge_amount,
                                total_due=repaid + interest + charge_amount, balance_after=balance))
    return Schedule(method=method, opening_balance=principal, rows=rows)


def annual_percentage_rate(net_amount: Decimal, payments: list[Decimal]) -> Decimal:
    """DAE per OUG 50/2010 Annex 1, in percent, rounded to 2 decimals (half up).

    Solves net_amount = sum(payment_k * (1 + X)^(-k/12)): the credit is drawn in full at
    t = 0 and payment k falls k twelfths of a year later (equal months, allowed by the annex).
    """
    net_amount = Decimal(net_amount)
    if net_amount <= 0 or not payments:
        raise ValueError("net amount must be positive and payments non-empty")
    with localcontext() as ctx:
        ctx.prec = 40

        def present_value(x: Decimal) -> Decimal:
            discount = 1 / (1 + x) ** (Decimal(1) / 12)
            factor, total = Decimal(1), ZERO
            for payment in payments:
                factor *= discount
                total += Decimal(payment) * factor
            return total

        low, high = Decimal("-0.99"), Decimal("10")  # present value falls as X rises
        for _ in range(200):
            mid = (low + high) / 2
            if present_value(mid) > net_amount:
                low = mid
            else:
                high = mid
        return ((low + high) / 2 * HUNDRED).quantize(CENT, rounding=ROUND_HALF_UP)


class PrepaymentOption(str, Enum):
    REDUCE_INSTALMENT = "reduce_instalment"  # keep the end date, lower the instalment
    REDUCE_TERM = "reduce_term"  # keep the instalment, finish earlier


def reschedule_after_prepayment(schedule: Schedule, after_month: int, amount: Decimal,
                                option: PrepaymentOption, rate_periods: list[RatePeriod],
                                charges: list[MonthlyCharge] = (),
                                charge_base: Decimal | None = None) -> Schedule | None:
    """Remaining schedule after paying `amount` of principal right after instalment `after_month`.

    Returns None when the prepayment repays the loan in full.
    """
    paid = next((r for r in schedule.rows if r.month == after_month), None)
    if paid is None:
        raise ValueError(f"month {after_month} is not in the schedule")
    amount = Decimal(amount)
    if amount <= 0 or amount > paid.balance_after:
        raise ValueError("prepayment must be positive and at most the outstanding balance")
    new_balance = paid.balance_after - amount
    if new_balance == 0:
        return None
    remaining = schedule.rows[-1].month - after_month
    base = schedule.opening_balance if charge_base is None else charge_base

    months = remaining
    if option == PrepaymentOption.REDUCE_TERM:
        months = _shortest_term(schedule, after_month, new_balance, remaining, rate_periods)
    return build_schedule(new_balance, months, rate_periods, schedule.method, list(charges),
                          first_month=after_month + 1, charge_base=base)


def _shortest_term(schedule: Schedule, after_month: int, balance: Decimal, remaining: int,
                   rate_periods: list[RatePeriod]) -> int:
    following = next(r for r in schedule.rows if r.month == after_month + 1)
    if schedule.method == RepaymentMethod.DECREASING:
        return max(1, int((balance / following.principal).to_integral_value(rounding=ROUND_CEILING)))
    rate = rate_for_month(rate_periods, after_month + 1)
    for months in range(1, remaining + 1):
        if money(annuity_payment(balance, rate, months)) <= following.instalment:
            return months
    return remaining
