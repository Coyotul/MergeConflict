"""Deterministic credit-check rules over hand-built ANAF and bureau reports."""
from datetime import date
from decimal import Decimal

from src.integrations.credit_sources.models import AnafReport, BureauReport
from src.models.credit import CreditProduct, EligibilityStatus, Money
from src.models.knowledge import Product
from src.rules.eligibility.credit_check import EligibilityRule, annuity_installment, evaluate

AS_OF = date(2026, 10, 28)
PRODUCT = CreditProduct(
    code=Product.personal_loan, name="Flexicredit", purposes=["personal"],
    min_amount=Money(amount=Decimal("1000"), currency="RON"),
    max_amount=Money(amount=Decimal("75000"), currency="RON"),
    min_term_months=6, max_term_months=84,
    indicative_annual_rate_percent=Decimal("9.5"), rate_note="indicative",
)
RULE = EligibilityRule(
    product_code=Product.personal_loan, min_age=18, max_age_at_maturity=70,
    min_monthly_income=Decimal("2500"), max_dti=Decimal("0.40"), min_employment_months=3,
    manual_review_employment_types=["self_employed"], rule_version="credit-check-2026-10-29",
    reject_dpd=90, review_dpd=31, min_score=500, income_gap_ratio=Decimal("0.10"),
)


def fields(**overrides):
    base = {"amount": Decimal("30000"), "term_months": 60, "age": 35, "employment_type": "employed",
            "employment_months": 48, "monthly_net_income": Decimal("8500"),
            "existing_monthly_obligations": Decimal("0")}
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def anaf(income="8500", **overrides):
    data = {"status": "found", "net_monthly_income": Decimal(income) if income is not None else None,
            "income_basis": "monthly_salary" if income is not None else None, "income_kinds": ["SALARY"],
            "self_employed": False, "employment_start": date(2020, 1, 1), "as_of": AS_OF}
    data.update(overrides)
    return AnafReport(**data)


def bureau(**overrides):
    data = {"status": "found", "active_products": 0, "monthly_instalments": Decimal("0"),
            "current_max_dpd": 0, "max_dpd_12m": 0, "written_off_or_assigned": False,
            "open_insolvency": False, "events_12m": [], "fraud_records": 0, "score": 720,
            "score_status": "SCORED", "as_of": AS_OF}
    data.update(overrides)
    return BureauReport(**data)


def run(f=None, a=None, b=None):
    return evaluate(f if f is not None else fields(), PRODUCT, RULE, a or anaf(), b or bureau())


def codes(result):
    return {r.code for r in result.reasons}


def test_clean_customer_satisfied():
    result = run()
    assert result.status == EligibilityStatus.satisfied
    assert "all_preliminary_rules_passed" in codes(result)
    assert result.rule_version == "credit-check-2026-10-29" and result.simulated


def test_income_exactly_minimum_passes():
    result = run(fields(amount=Decimal("1000"), monthly_net_income=Decimal("2500")), anaf("2500"))
    assert result.status == EligibilityStatus.satisfied


def test_income_below_minimum_rejects():
    result = run(fields(amount=Decimal("1000"), monthly_net_income=Decimal("2499.99")), anaf("2499.99"))
    assert result.status == EligibilityStatus.not_satisfied
    assert "income_below_minimum" in codes(result)


def _obligations_for_dti(income: Decimal, ratio: Decimal) -> Decimal:
    return income * ratio - annuity_installment(Decimal("30000"), Decimal("9.5"), 60)


def test_dti_exactly_limit_passes():
    obl = _obligations_for_dti(Decimal("10000"), Decimal("0.40"))
    result = run(fields(monthly_net_income=Decimal("10000"), existing_monthly_obligations=obl), anaf("10000"))
    assert result.status == EligibilityStatus.satisfied
    assert "dti_computed" in codes(result)


def test_dti_above_limit_rejects():
    obl = _obligations_for_dti(Decimal("10000"), Decimal("0.40")) + Decimal("0.01")
    result = run(fields(monthly_net_income=Decimal("10000"), existing_monthly_obligations=obl), anaf("10000"))
    assert result.status == EligibilityStatus.not_satisfied
    assert "dti_above_limit" in codes(result)


def test_declared_obligations_win_when_higher():
    obl = _obligations_for_dti(Decimal("10000"), Decimal("0.40")) + Decimal("1")
    result = run(fields(monthly_net_income=Decimal("10000"), existing_monthly_obligations=obl), anaf("10000"),
                 bureau(active_products=1, monthly_instalments=Decimal("100")))
    assert "dti_above_limit" in codes(result)
    assert "bureau_obligations_counted" in codes(result)


def test_current_dpd_90_rejects():
    result = run(b=bureau(active_products=1, current_max_dpd=90, max_dpd_12m=90))
    assert result.status == EligibilityStatus.not_satisfied
    assert "bureau_current_delinquency" in codes(result)
    assert "bureau_past_delinquency" not in codes(result)


def test_current_dpd_89_reviews():
    result = run(b=bureau(active_products=1, current_max_dpd=89, max_dpd_12m=89))
    assert result.status == EligibilityStatus.manual_review
    assert "bureau_past_delinquency" in codes(result)


def test_cured_90_dpd_in_12m_reviews():
    result = run(b=bureau(active_products=1, current_max_dpd=0, max_dpd_12m=120))
    assert result.status == EligibilityStatus.manual_review
    assert "bureau_past_delinquency" in codes(result)


def test_insolvency_rejects():
    result = run(b=bureau(open_insolvency=True))
    assert result.status == EligibilityStatus.not_satisfied
    assert "bureau_open_insolvency" in codes(result)


def test_restructuring_reviews():
    result = run(b=bureau(active_products=1, events_12m=["RESTRUCTURING"]))
    assert result.status == EligibilityStatus.manual_review
    assert "bureau_recent_restructuring" in codes(result)


def test_self_employed_reviews():
    assert "self_employed" in codes(run(fields(employment_type="self_employed")))
    result = run(a=anaf(self_employed=True, income_kinds=["INDEPENDENT_ACTIVITY"]))
    assert result.status == EligibilityStatus.manual_review
    assert "self_employed" in codes(result)


def test_anaf_not_found_reviews_and_skips_income_rules():
    result = run(fields(monthly_net_income=Decimal("1000"), existing_monthly_obligations=Decimal("5000")),
                 anaf(None, status="not_found", income_kinds=[], employment_start=None))
    assert result.status == EligibilityStatus.manual_review
    assert "anaf_income_not_found" in codes(result)
    assert not codes(result) & {"income_below_minimum", "dti_above_limit", "dti_computed", "income_gap"}


def test_missing_field_more_information():
    result = run(fields(amount=None, employment_months=None))
    assert result.status == EligibilityStatus.more_information_required
    assert [r.code for r in result.reasons].count("missing_field") == 1
    assert set(result.missing_fields) == {"amount", "employment_months"}


def test_reject_beats_review():
    result = run(fields(employment_type="self_employed"), b=bureau(open_insolvency=True))
    assert result.status == EligibilityStatus.not_satisfied
    assert {"self_employed", "bureau_open_insolvency"} <= codes(result)


def test_income_gap_reason_message():
    result = run(fields(monthly_net_income=Decimal("7000")), anaf("5000"))
    gap = next(r for r in result.reasons if r.code == "income_gap")
    assert "7000" in gap.message and "5000" in gap.message


def test_no_credit_history_is_neutral():
    result = run(b=bureau(score=None, score_status="NONE"))
    assert result.status == EligibilityStatus.satisfied
    assert "no_credit_history" in codes(result)


def test_age_at_maturity_rejects():
    result = run(fields(age=66, term_months=60))
    assert "age_out_of_range" in codes(result)
