"""Tests for product pricing rules on the synthetic product configurations."""

from decimal import Decimal as D

import pytest

from src.rules.pricing.rules import (PricingRuleError, SalaryAccount, early_repayment_fee, insurance_premium,
                                     quote_rate, validate_limits)
from src.services.financial_calculations.calculations import RepaymentMethod
from src.services.pricing.service import load_product


@pytest.fixture
def personal():
    return load_product("personal_loan_fixed")


@pytest.fixture
def mortgage():
    return load_product("mortgage_fixed_then_ircc")


@pytest.mark.parametrize("salary, insurance, base, expected", [
    (SalaryAccount.NONE, False, None, "8.55"),
    (SalaryAccount.STANDARD, True, None, "5.55"),  # published minimum
    (SalaryAccount.PREMIUM, True, None, "5.35"),  # published Premium minimum
    (SalaryAccount.STANDARD, True, "17.95", "14.95"),  # published maximum for a salary client
    (SalaryAccount.PREMIUM, True, "17.95", "14.75"),  # published Premium maximum
    (SalaryAccount.NONE, False, "17.95", "17.95"),  # published overall maximum
])
def test_fixed_rate_reproduces_the_published_rate_grid(personal, salary, insurance, base, expected):
    quote = quote_rate(personal, salary_account=salary, with_insurance=insurance,
                       base_annual_rate=None if base is None else D(base))
    assert quote.rate_periods[0].annual_rate == D(expected)


def test_premium_discount_replaces_the_standard_one(personal):
    quote = quote_rate(personal, salary_account=SalaryAccount.PREMIUM, with_insurance=False)
    assert [d.code for d in quote.discounts] == ["SALARY_ACCOUNT_PREMIUM"]


@pytest.mark.parametrize("base", ["8.54", "17.96"])
def test_base_rate_outside_the_product_range_is_rejected(personal, base):
    with pytest.raises(PricingRuleError) as err:
        quote_rate(personal, salary_account=SalaryAccount.NONE, with_insurance=False, base_annual_rate=D(base))
    assert err.value.code == "RATE_OUT_OF_RANGE"


def test_mortgage_rate_is_fixed_then_index_plus_margin(mortgage):
    quote = quote_rate(mortgage, salary_account=SalaryAccount.NONE, with_insurance=False,
                       fixed_period_months=60, index_value=D("5.57"))
    assert [(p.start_month, p.annual_rate) for p in quote.rate_periods] == [(1, D("5.65")), (61, D("7.87"))]


@pytest.mark.parametrize("period, index, code", [(48, D("5.57"), "FIXED_PERIOD_NOT_OFFERED"),
                                                 (36, None, "INDEX_UNAVAILABLE")])
def test_mortgage_rate_errors(mortgage, period, index, code):
    with pytest.raises(PricingRuleError) as err:
        quote_rate(mortgage, salary_account=SalaryAccount.NONE, with_insurance=False,
                   fixed_period_months=period, index_value=index)
    assert err.value.code == code


def test_single_premium_insurance_matches_published_example(personal):
    assert insurance_premium(personal, D("50000"), 60) == D("3600.00")  # 50,000 x 0.12% x 60


@pytest.mark.parametrize("amount, months, method, code", [
    (D("2499"), 24, RepaymentMethod.ANNUITY, "AMOUNT_OUT_OF_RANGE"),
    (D("250001"), 24, RepaymentMethod.ANNUITY, "AMOUNT_OUT_OF_RANGE"),
    (D("10000"), 17, RepaymentMethod.ANNUITY, "TERM_OUT_OF_RANGE"),
    (D("10000"), 61, RepaymentMethod.ANNUITY, "TERM_OUT_OF_RANGE"),
])
def test_product_limits(personal, amount, months, method, code):
    with pytest.raises(PricingRuleError) as err:
        validate_limits(personal, amount, months, method)
    assert err.value.code == code


@pytest.mark.parametrize("months_left, in_fixed, interest_saved, expected", [
    (48, True, D("5000"), D("100.00")),  # 1% when more than 12 months remain
    (12, True, D("5000"), D("50.00")),  # 0.5% in the last year
    (48, False, D("5000"), D("0.00")),  # never during a variable-rate period
    (48, True, D("30.40"), D("30.40")),  # capped at the interest the customer would have paid
])
def test_early_repayment_fee_follows_oug_50_2010(personal, months_left, in_fixed, interest_saved, expected):
    fee = early_repayment_fee(personal, amount=D("10000"), months_left=months_left, in_fixed_rate_period=in_fixed,
                              interest_saved_in_fixed_period=interest_saved)
    assert fee == expected
