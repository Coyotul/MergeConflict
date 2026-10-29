"""Deterministic preliminary credit check: session fields + ANAF + bureau -> EligibilityResult.

Pure function, no I/O. ANAF figures win over declared values; declared values only
explain gaps. Precedence: not_satisfied > manual_review > more_information_required > satisfied.
"""
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from src.integrations.credit_sources.models import AnafReport, BureauReport
from src.models.credit import CreditProduct, EligibilityResult, EligibilityStatus, ReasonItem
from src.models.knowledge import Product

REQUIRED_FIELDS = ("amount", "term_months", "age", "employment_type", "employment_months",
                   "monthly_net_income", "existing_monthly_obligations")
REVIEW_EVENTS = {"RESTRUCTURING", "PAYMENT_SUSPENSION"}


def annuity_installment(principal: Decimal, annual_rate_percent: Decimal, months: int) -> Decimal:
    """Monthly annuity installment quantized to 0.01 with ROUND_HALF_UP."""
    if annual_rate_percent == Decimal("0"):
        result = principal / Decimal(months)
    else:
        monthly_rate = annual_rate_percent / Decimal("100") / Decimal("12")
        denominator = Decimal("1") - ((Decimal("1") + monthly_rate) ** (-months))
        result = principal * monthly_rate / denominator
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class EligibilityRule:
    """Eligibility rules for a product."""
    product_code: Product
    min_age: int
    max_age_at_maturity: int
    min_monthly_income: Decimal
    max_dti: Decimal
    min_employment_months: int
    manual_review_employment_types: list[str]
    rule_version: str
    reject_dpd: int = 90
    review_dpd: int = 31
    min_score: int = 500
    income_gap_ratio: Decimal = Decimal("0.10")

    def make_satisfied_result(self) -> EligibilityResult:
        """Create a satisfied eligibility result."""
        return EligibilityResult(
            status=EligibilityStatus.satisfied,
            reasons=[ReasonItem(code="all_preliminary_rules_passed", message="All preliminary rules passed")],
            rule_version=self.rule_version,
            simulated=True
        )


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month - (1 if end.day < start.day else 0)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def evaluate(fields: dict[str, Any], product: CreditProduct, rule: EligibilityRule,
             anaf: AnafReport, bureau: BureauReport) -> EligibilityResult:
    """Apply every rule and return all triggered reasons with the winning status."""
    reject: list[ReasonItem] = []
    review: list[ReasonItem] = []
    info: list[ReasonItem] = []
    missing = [name for name in REQUIRED_FIELDS if fields.get(name) in (None, "")]
    has = lambda name: name not in missing  # noqa: E731

    amount = _dec(fields["amount"]) if has("amount") else None
    term = int(fields["term_months"]) if has("term_months") else None
    if amount is not None and not product.min_amount.amount <= amount <= product.max_amount.amount:
        reject.append(ReasonItem(code="amount_out_of_range", message=(
            f"Amount {amount} is outside {product.min_amount.amount}-{product.max_amount.amount} RON.")))
    if term is not None and not product.min_term_months <= term <= product.max_term_months:
        reject.append(ReasonItem(code="term_out_of_range", message=(
            f"Term {term} months is outside {product.min_term_months}-{product.max_term_months} months.")))
    if has("age"):
        age = int(fields["age"])
        if age < rule.min_age or (term is not None and age + math.ceil(term / 12) > rule.max_age_at_maturity):
            reject.append(ReasonItem(code="age_out_of_range", message=(
                f"Age must be at least {rule.min_age} and at most {rule.max_age_at_maturity} at loan maturity.")))

    employment_months = (_months_between(anaf.employment_start, anaf.as_of) if anaf.employment_start
                         else int(fields["employment_months"]) if has("employment_months") else None)
    if employment_months is not None and employment_months < rule.min_employment_months:
        reject.append(ReasonItem(code="employment_too_short", message=(
            f"Current employment of {employment_months} months is under {rule.min_employment_months} months.")))

    if fields.get("employment_type") in rule.manual_review_employment_types or anaf.self_employed:
        review.append(ReasonItem(code="self_employed", message="Self-employed income needs an advisor review."))

    income = anaf.net_monthly_income if anaf.status == "found" else None
    declared_obligations = _dec(fields["existing_monthly_obligations"]) if has("existing_monthly_obligations") else Decimal("0")
    if income is None:
        review.append(ReasonItem(code="anaf_income_not_found", message=(
            "Your income could not be verified with ANAF; an advisor will check your documents.")))
    else:
        if income < rule.min_monthly_income:
            reject.append(ReasonItem(code="income_below_minimum", message=(
                f"ANAF net monthly income {income} RON is below the {rule.min_monthly_income} RON minimum.")))
        if has("monthly_net_income") and income > 0:
            declared = _dec(fields["monthly_net_income"])
            if abs(declared - income) / income > rule.income_gap_ratio:
                info.append(ReasonItem(code="income_gap", message=(
                    f"Declared income {declared} RON differs from ANAF income {income} RON; ANAF is used.")))
        if amount is not None and term is not None and term > 0 and income > 0:
            new_instalment = annuity_installment(amount, product.indicative_annual_rate_percent, term)
            existing = max(declared_obligations, bureau.monthly_instalments)
            dti = (new_instalment + existing) / income
            percent = (dti * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            info.append(ReasonItem(code="dti_computed", message=(
                f"Debt-to-income {percent}%: new instalment {new_instalment} + existing {existing} RON "
                f"over income {income} RON (limit {rule.max_dti * 100:.0f}%).")))
            if dti > rule.max_dti:
                reject.append(ReasonItem(code="dti_above_limit", message=(
                    f"Debt-to-income {percent}% is above the {rule.max_dti * 100:.0f}% limit.")))

    if bureau.status == "not_found":
        review.append(ReasonItem(code="bureau_not_found", message=(
            "Your credit bureau record could not be found; an advisor will check it.")))
    else:
        if bureau.current_max_dpd >= rule.reject_dpd:
            reject.append(ReasonItem(code="bureau_current_delinquency", message=(
                f"A loan is currently {bureau.current_max_dpd} days past due.")))
        elif bureau.max_dpd_12m >= rule.review_dpd:
            review.append(ReasonItem(code="bureau_past_delinquency", message=(
                f"A payment was {bureau.max_dpd_12m} days late in the last 12 months.")))
        if bureau.written_off_or_assigned:
            reject.append(ReasonItem(code="bureau_written_off_or_assigned",
                                     message="A debt was written off or assigned to a collector."))
        if bureau.open_insolvency:
            reject.append(ReasonItem(code="bureau_open_insolvency", message="An insolvency procedure is open."))
        if REVIEW_EVENTS & set(bureau.events_12m):
            review.append(ReasonItem(code="bureau_recent_restructuring",
                                     message="A loan was restructured or suspended in the last 12 months."))
        if bureau.fraud_records:
            review.append(ReasonItem(code="bureau_fraud_record", message="A card-fraud record is on file."))
        if bureau.score_status == "SCORED" and bureau.score is not None and bureau.score < rule.min_score:
            review.append(ReasonItem(code="bureau_low_score", message=(
                f"Credit score {bureau.score} is below {rule.min_score}.")))
        if bureau.score_status != "SCORED":
            info.append(ReasonItem(code="no_score", message="No credit score is available; this is neutral."))
        if bureau.active_products == 0:
            info.append(ReasonItem(code="no_credit_history", message="No active loans in the credit bureau; this is neutral."))
        else:
            info.append(ReasonItem(code="bureau_obligations_counted", message=(
                f"{bureau.active_products} active loan(s) with {bureau.monthly_instalments} RON monthly "
                "instalments were counted.")))

    if missing:
        more_info = [ReasonItem(code="missing_field", message=f"Missing information: {', '.join(missing)}.")]
    else:
        more_info = []
    if reject:
        status = EligibilityStatus.not_satisfied
    elif review:
        status = EligibilityStatus.manual_review
    elif more_info:
        status = EligibilityStatus.more_information_required
    else:
        status = EligibilityStatus.satisfied
        info.append(ReasonItem(code="all_preliminary_rules_passed", message="All preliminary rules passed"))
    return EligibilityResult(status=status, reasons=reject + review + more_info + info,
                             rule_version=rule.rule_version, missing_fields=missing, simulated=True)
