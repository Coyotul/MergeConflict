"""Known-result tests for the deterministic loan mathematics."""

from decimal import Decimal as D

import pytest

from src.services.financial_calculations.calculations import (MonthlyCharge, PrepaymentOption, RatePeriod,
                                                              RepaymentMethod, annual_percentage_rate,
                                                              annuity_payment, build_schedule, money,
                                                              reschedule_after_prepayment)

ADMIN_FEE = [MonthlyCharge(code="ADMIN", fixed=D("5"))]


def fixed(rate):
    return [RatePeriod(start_month=1, annual_rate=D(rate))]


def closed_form_balance(principal, rate, instalment, paid):
    """Balance after `paid` instalments of `instalment`: B = P(1+r)^k - A((1+r)^k - 1)/r."""
    r = D(rate) / 100 / 12
    a = D(instalment)
    growth = (1 + r) ** paid
    return D(principal) * growth - a * (growth - 1) / r


def test_annuity_payment_matches_published_raiffeisen_example():
    # 50,000 lei, 60 months, 5.55% fixed: 956.21 + 5 lei fee = 961.21 (cost sheet 15.10.2026)
    assert money(annuity_payment(D("50000"), D("5.55"), 60)) == D("956.21")


def test_zero_rate_annuity_is_principal_divided_by_months():
    assert annuity_payment(D("1200"), D("0"), 12) == D("100")


@pytest.mark.parametrize("method", list(RepaymentMethod))
def test_schedule_repays_exact_principal_and_ends_at_zero(method):
    schedule = build_schedule(D("50000"), 60, fixed("5.55"), method, ADMIN_FEE)
    assert len(schedule.rows) == 60
    assert schedule.totals().principal == D("50000.00")
    assert schedule.rows[-1].balance_after == D("0.00")
    for row in schedule.rows:
        assert row.total_due == row.principal + row.interest + row.charges == row.instalment + row.charges


def test_rounded_schedule_tracks_the_closed_form_balance():
    # The schedule pays the rounded instalment (956.21, not 956.2125), so that is the reference;
    # the remaining difference comes only from rounding each month's interest to the cent.
    schedule = build_schedule(D("50000"), 60, fixed("5.55"))
    for paid in (1, 12, 30, 59):
        expected = closed_form_balance("50000", "5.55", "956.21", paid)
        assert abs(schedule.rows[paid - 1].balance_after - expected) <= D("0.005") * paid


def test_last_instalment_absorbs_the_rounding_of_the_others():
    rows = build_schedule(D("50000"), 60, fixed("5.55")).rows
    unpaid_by_rounding = closed_form_balance("50000", "5.55", "956.21", 59) - closed_form_balance(
        "50000", "5.55", annuity_payment(D("50000"), D("5.55"), 60), 59)
    assert abs(rows[-1].instalment - D("956.21") - unpaid_by_rounding) <= D("0.30")


def test_annuity_instalments_are_equal_except_the_last():
    rows = build_schedule(D("50000"), 60, fixed("5.55")).rows
    assert {r.instalment for r in rows[:-1]} == {D("956.21")}
    assert abs(rows[-1].instalment - D("956.21")) < D("1")


def test_decreasing_method_has_equal_principal_and_falling_instalments():
    rows = build_schedule(D("12000"), 12, fixed("6"), RepaymentMethod.DECREASING).rows
    assert {r.principal for r in rows} == {D("1000.00")}
    assert all(a.instalment > b.instalment for a, b in zip(rows, rows[1:]))
    assert rows[0].interest == D("60.00")  # 12,000 x 6% / 12


def test_annuity_is_recalculated_when_the_fixed_period_ends():
    # Raiffeisen "Casa Ta": 350,900 lei, 300 months, 5.05% for 36 months then IRCC 5.57% + 2.30% = 7.87%,
    # plus 3 lei account fee and 0.026%/month life insurance: published 2,155.80 then 2,713.05.
    charges = [MonthlyCharge(code="ACCOUNT", fixed=D("3")), MonthlyCharge(code="LIFE", percent_of_principal=D("0.026"))]
    periods = [RatePeriod(start_month=1, annual_rate=D("5.05")), RatePeriod(start_month=37, annual_rate=D("7.87"))]
    rows = build_schedule(D("350900"), 300, periods, charges=charges).rows
    assert rows[36].total_due == D("2713.05")
    assert abs(rows[0].total_due - D("2155.80")) <= D("0.01")  # bank rounds the sum, we round each part
    assert rows[35].annual_rate == D("5.05") and rows[36].annual_rate == D("7.87")


@pytest.mark.parametrize("rate, net, expected_dae", [
    ("5.55", "46200", "9.49"),  # 200 fee + 3,600 insurance financed
    ("5.35", "46200", "9.26"),  # Premium client
    ("17.95", "49800", "19.94"),  # maximum rate, no insurance
])
def test_dae_matches_published_raiffeisen_examples(rate, net, expected_dae):
    rows = build_schedule(D("50000"), 60, fixed(rate), charges=ADMIN_FEE).rows
    assert annual_percentage_rate(D(net), [r.total_due for r in rows]) == D(expected_dae)


def test_dae_of_a_loan_without_costs_is_zero():
    rows = build_schedule(D("1200"), 12, fixed("0")).rows
    assert annual_percentage_rate(D("1200"), [r.total_due for r in rows]) == D("0.00")


def test_dae_of_a_fee_free_loan_is_the_effective_annual_rate():
    rows = build_schedule(D("10000"), 12, fixed("12")).rows
    effective = ((1 + D("0.01")) ** 12 - 1) * 100  # 12.68%
    assert abs(annual_percentage_rate(D("10000"), [r.total_due for r in rows]) - effective) < D("0.02")


def test_prepayment_with_reduced_instalment_keeps_the_end_date():
    schedule = build_schedule(D("50000"), 60, fixed("5.55"), charges=ADMIN_FEE)
    balance = schedule.rows[11].balance_after
    new = reschedule_after_prepayment(schedule, 12, D("10000"), PrepaymentOption.REDUCE_INSTALMENT,
                                      fixed("5.55"), ADMIN_FEE)
    assert new.rows[0].month == 13 and new.rows[-1].month == 60
    assert new.rows[0].instalment == money(annuity_payment(balance - D("10000"), D("5.55"), 48))
    assert new.totals().principal == balance - D("10000")


def test_prepayment_with_reduced_term_finishes_earlier_without_raising_the_instalment():
    schedule = build_schedule(D("50000"), 60, fixed("5.55"))
    new = reschedule_after_prepayment(schedule, 12, D("10000"), PrepaymentOption.REDUCE_TERM, fixed("5.55"))
    assert new.rows[-1].month < 60
    assert new.rows[0].instalment <= schedule.rows[12].instalment
    assert new.rows[-1].balance_after == D("0.00")


def test_full_prepayment_returns_no_schedule():
    schedule = build_schedule(D("50000"), 60, fixed("5.55"))
    balance = schedule.rows[11].balance_after
    assert reschedule_after_prepayment(schedule, 12, balance, PrepaymentOption.REDUCE_INSTALMENT, fixed("5.55")) is None


@pytest.mark.parametrize("amount", ["0", "-1", "1000000"])
def test_invalid_prepayment_amount_is_rejected(amount):
    schedule = build_schedule(D("50000"), 60, fixed("5.55"))
    with pytest.raises(ValueError):
        reschedule_after_prepayment(schedule, 12, D(amount), PrepaymentOption.REDUCE_INSTALMENT, fixed("5.55"))


def test_same_inputs_give_identical_schedules():
    first = build_schedule(D("50000"), 60, fixed("5.55"), charges=ADMIN_FEE)
    second = build_schedule(D("50000"), 60, fixed("5.55"), charges=ADMIN_FEE)
    assert first.model_dump() == second.model_dump()
