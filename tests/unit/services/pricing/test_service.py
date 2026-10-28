"""Service tests: published Raiffeisen Bank Romania examples as known results, plus simulations.

Sources: personal-loan cost sheet effective 15.10.2026 and the "Casa Ta" mortgage page (28.10.2026).
Instalments and DAE must match exactly. Totals may differ by a few bani: the bank's representative
totals use unrounded instalments, while a payable schedule rounds every instalment.
"""

from datetime import date
from decimal import Decimal as D

import pytest

from src.services.pricing.models import EarlyRepaymentRequest, ExistingLoan, LoanOfferRequest, RefinancingRequest
from src.services.pricing.service import (calculate_loan_offer, compare_refinancing_options,
                                          simulate_early_repayment)

ON = date(2026, 10, 28)


def personal(**overrides):
    values = dict(product_id="personal_loan_fixed", amount=D("50000"), term_months=60, simulation_date=ON)
    return LoanOfferRequest(**{**values, **overrides})


@pytest.mark.parametrize("overrides, payment, dae, total", [
    (dict(salary_account="standard", with_insurance=True), "961.21", "9.49", "57672.75"),
    (dict(salary_account="premium", with_insurance=True), "956.60", "9.26", "57396.01"),
    (dict(base_annual_rate=D("17.95")), "1273.31", "19.94", "76398.71"),
])
def test_offer_reproduces_published_representative_examples(overrides, payment, dae, total):
    offer = calculate_loan_offer(personal(**overrides))
    assert offer.status == "ok"
    assert offer.first_monthly_payment == D(payment)
    assert offer.dae == D(dae)
    assert abs(offer.totals.total_payable - D(total)) <= D("0.05")


def test_offer_breaks_down_fees_and_payout():
    offer = calculate_loan_offer(personal(salary_account="standard", with_insurance=True))
    assert {f.code: f.amount for f in offer.fees} == {"ANALYSIS_FEE": D("200.00"),
                                                      "LIFE_UNEMPLOYMENT_SINGLE_PREMIUM": D("3600.00")}
    assert offer.net_amount_paid_out == D("46200.00")
    totals = offer.totals
    assert totals.total_cost_of_credit == totals.total_payable - offer.net_amount_paid_out
    assert offer.indicative and offer.assumptions


def test_mortgage_uses_the_ircc_of_the_simulation_quarter():
    offer = calculate_loan_offer(LoanOfferRequest(product_id="mortgage_fixed_then_ircc", amount=D("350900"), term_months=300,
                                                  fixed_period_months=36, simulation_date=ON))
    assert offer.rate.index_value == D("5.57")
    assert offer.monthly_payment_after_fixed_period == D("2713.05")
    assert abs(offer.first_monthly_payment - D("2155.80")) <= D("0.01")
    assert any(w.startswith("DAE_INCOMPLETE") for w in offer.warnings)


@pytest.mark.parametrize("request_, code", [
    (personal(amount=D("300000")), "AMOUNT_OUT_OF_RANGE"),
    (personal(product_id="no_such_product"), "UNKNOWN_PRODUCT"),
    (LoanOfferRequest(product_id="mortgage_fixed_then_ircc", amount=D("300000"), term_months=240, with_insurance=True,
                      simulation_date=ON), "INSURANCE_NOT_OFFERED"),
    (LoanOfferRequest(product_id="mortgage_fixed_then_ircc", amount=D("300000"), term_months=240,
                      simulation_date=date(2030, 1, 1)), "INDEX_UNAVAILABLE"),
])
def test_invalid_requests_return_typed_errors(request_, code):
    offer = calculate_loan_offer(request_)
    assert offer.status == "invalid"
    assert [e.code for e in offer.errors] == [code]
    assert offer.schedule is None


@pytest.mark.parametrize("income, existing, within", [(D("5557"), D("0"), True), (D("2000"), D("0"), False),
                                                      (D("5557"), D("1500"), False)])
def test_affordability_against_the_40_percent_limit(income, existing, within):
    offer = calculate_loan_offer(personal(salary_account="standard", with_insurance=True,
                                          net_monthly_income=income, existing_monthly_debt_payments=existing))
    assert offer.affordability.limit == D("0.40")
    assert offer.affordability.within_limit is within


def test_offer_is_deterministic():
    request = personal(salary_account="standard", with_insurance=True)
    assert calculate_loan_offer(request).model_dump() == calculate_loan_offer(request).model_dump()


def early(**overrides):
    loan = personal(salary_account="standard", with_insurance=True)
    return simulate_early_repayment(EarlyRepaymentRequest(**{"loan": loan, "after_month": 12, **overrides}))


def test_full_early_repayment_charges_one_percent_and_flags_settlement_as_indicative():
    result = early()
    assert result.full_repayment
    assert result.early_repayment_fee == (result.outstanding_balance * D("0.01")).quantize(D("0.01"))
    assert result.total_to_pay_now == result.outstanding_balance + result.early_repayment_fee
    assert any("authoritative settlement" in a for a in result.assumptions)


def test_partial_repayment_savings_add_up():
    result = early(amount=D("10000"), option="reduce_term")
    assert result.new_last_month < result.previous_last_month
    assert result.net_saving == result.interest_saved + result.charges_saved - result.early_repayment_fee
    assert result.charges_saved == D("5") * (result.previous_last_month - result.new_last_month)


def test_repayment_in_the_last_year_costs_half_a_percent():
    result = early(after_month=50, amount=D("1000"))
    assert result.early_repayment_fee == D("5.00")


def test_no_fee_after_the_fixed_rate_period():
    loan = LoanOfferRequest(product_id="mortgage_fixed_then_ircc", amount=D("350900"), term_months=300,
                            fixed_period_months=36, simulation_date=ON)
    inside = simulate_early_repayment(EarlyRepaymentRequest(loan=loan, after_month=24, amount=D("20000")))
    after = simulate_early_repayment(EarlyRepaymentRequest(loan=loan, after_month=36, amount=D("20000")))
    assert inside.early_repayment_fee == D("200.00")
    assert after.early_repayment_fee == D("0.00")


@pytest.mark.parametrize("overrides, code", [(dict(amount=D("999999")), "AMOUNT_ABOVE_BALANCE"),
                                             (dict(after_month=60), "MONTH_OUT_OF_RANGE")])
def test_invalid_early_repayment(overrides, code):
    result = early(**overrides)
    assert result.status == "invalid" and result.errors[0].code == code


def refinance(**overrides):
    loans = [ExistingLoan(label="Loan A", outstanding_balance=D("15000"), annual_rate=D("21.5"), remaining_months=36,
                          early_repayment_fee_percent=D("1")),
             ExistingLoan(label="Loan B", outstanding_balance=D("20000"), annual_rate=D("12.9"), remaining_months=48,
                          monthly_charges=D("10"))]
    values = dict(existing_loans=loans, term_months=60, salary_account="standard", simulation_date=ON)
    return compare_refinancing_options(RefinancingRequest(**{**values, **overrides}))


def test_refinancing_amount_covers_balances_switching_fees_and_its_own_fees():
    result = refinance(with_insurance=True, extra_cash=D("5000"))
    assert result.status == "ok"
    assert result.early_repayment_fees_on_current_loans == D("150.00")
    assert result.new_offer.net_amount_paid_out >= D("15000") + D("20000") + D("150") + D("5000")


def test_refinancing_reports_trade_offs_instead_of_assuming_a_benefit():
    # Same rate as the existing loan but a much longer term: lower monthly payment, higher total cost.
    loans = [ExistingLoan(label="Loan C", outstanding_balance=D("30000"), annual_rate=D("8.55"), remaining_months=24)]
    result = refinance(existing_loans=loans, term_months=120, salary_account="none")
    assert result.outcome == "LOWER_MONTHLY_HIGHER_TOTAL_COST"
    assert result.monthly_difference < 0 < result.cost_difference


def test_refinancing_flags_inconsistent_declared_payments():
    loans = [ExistingLoan(label="Loan D", outstanding_balance=D("20000"), annual_rate=D("12.9"), remaining_months=48,
                          declared_monthly_payment=D("400"))]
    assert any(w.startswith("PAYMENT_MISMATCH") for w in refinance(existing_loans=loans).warnings)
