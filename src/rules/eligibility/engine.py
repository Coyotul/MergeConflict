"""Pure preliminary reference rules. No providers, workflow writes or LLM calls."""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN, localcontext

from src.models.eligibility import (
    AgePolicyCategory, ApplicationSnapshot, AssessmentStatus, CreditBureauData,
    EmploymentContract, EvidenceReference, EvidenceSource, EvidenceStatus,
    FinancialAssessment, IncomeBasis, IncomeKind, IncomeVerificationData, LoanVerificationData,
    PricingScenario, RuleCheck, RuleStatus,
)
from src.rules.eligibility.calendar import add_months, completed_years
from src.services.eligibility.policy import EligibilityPolicy
from src.services.financial_calculations.affordability import (
    FinancialInputError, proposed_monthly_debt, reconcile_monthly_debt, within_dti_limit,
)


def check(
    policy: EligibilityPolicy, rule: str, status: RuleStatus, code: str,
    message: str, evidence_ids: tuple[str, ...] = (),
) -> RuleCheck:
    return RuleCheck(
        rule_id=rule, status=status, reason_code=code, message=message,
        evidence_ids=evidence_ids, source_ids=policy.source_ids_for(rule),
    )


def aggregate_status(checks: tuple[RuleCheck, ...]) -> AssessmentStatus:
    """Integrity/review flags outrank failure: questionable evidence cannot reject."""
    if not checks:
        return AssessmentStatus.INFORMATION_REQUIRED
    statuses = {item.status for item in checks}
    if RuleStatus.REVIEW_REQUIRED in statuses:
        return AssessmentStatus.REVIEW_REQUIRED
    if RuleStatus.FAIL in statuses:
        return AssessmentStatus.NOT_SATISFIED
    if RuleStatus.INFORMATION_REQUIRED in statuses:
        return AssessmentStatus.INFORMATION_REQUIRED
    return AssessmentStatus.SATISFIED


def evidence_problem(
    evidence: EvidenceReference | None, expected_source: EvidenceSource,
    policy: EligibilityPolicy, now: datetime,
) -> str | None:
    if evidence is None:
        return "MISSING_EVIDENCE"
    if evidence.source != expected_source or evidence.status != EvidenceStatus.VERIFIED:
        return "UNVERIFIED_EVIDENCE"
    if evidence.recorded_at > now:
        return "FUTURE_EVIDENCE"
    if now - evidence.recorded_at > timedelta(days=policy.evidence_max_age_days[expected_source]):
        return "STALE_EVIDENCE"
    if evidence.expires_on is not None and evidence.expires_on < now.date():
        return "EXPIRED_EVIDENCE"
    return None


def product_checks(
    application: ApplicationSnapshot, policy: EligibilityPolicy,
) -> tuple[RuleCheck, ...]:
    request = application.request
    if request.product_id != policy.product_id:
        return (check(policy, "PRODUCT", RuleStatus.REVIEW_REQUIRED, "UNSUPPORTED_PRODUCT",
                      "No automatic eligibility policy covers this product."),)
    amount_ok = policy.minimum_amount_ron <= request.amount_ron <= policy.maximum_amount_ron
    term_ok = policy.minimum_term_months <= request.term_months <= policy.maximum_term_months
    return (
        check(policy, "PRODUCT", RuleStatus.PASS if amount_ok else RuleStatus.FAIL,
              "AMOUNT_WITHIN_BOUNDS" if amount_ok else "AMOUNT_OUTSIDE_BOUNDS",
              "Requested amount checked against the configured reference bounds."),
        check(policy, "PRODUCT", RuleStatus.PASS if term_ok else RuleStatus.FAIL,
              "TERM_WITHIN_BOUNDS" if term_ok else "TERM_OUTSIDE_BOUNDS",
              "Requested term checked against the configured personal-loan bounds."),
    )


def profile_checks(
    application: ApplicationSnapshot, policy: EligibilityPolicy, now: datetime,
) -> tuple[RuleCheck, ...]:
    problem = evidence_problem(application.profile_evidence, EvidenceSource.CUSTOMER_PROFILE, policy, now)
    if problem is not None:
        status = RuleStatus.INFORMATION_REQUIRED if problem == "MISSING_EVIDENCE" else RuleStatus.REVIEW_REQUIRED
        return (check(policy, "AGE", status, problem, "A current verified profile is required."),)
    evidence_ids = (application.profile_evidence.evidence_id,)
    profile = application.profile
    checks: list[RuleCheck] = []
    maturity = add_months(now.date(), application.request.term_months)
    if profile.birth_date is None:
        checks.append(check(policy, "AGE", RuleStatus.INFORMATION_REQUIRED, "BIRTH_DATE_REQUIRED",
                            "Verified birth date is missing.", evidence_ids))
    elif profile.birth_date > now.date():
        checks.append(check(policy, "AGE", RuleStatus.REVIEW_REQUIRED, "INVALID_BIRTH_DATE",
                            "The profile birth date requires correction.", evidence_ids))
    else:
        age_ok = completed_years(profile.birth_date, now.date()) >= policy.minimum_age_years
        checks.append(check(policy, "AGE", RuleStatus.PASS if age_ok else RuleStatus.FAIL,
                            "MINIMUM_AGE_MET" if age_ok else "BELOW_MINIMUM_AGE",
                            "Minimum age checked using completed calendar years.", evidence_ids))
        if profile.age_policy_category == AgePolicyCategory.UNSPECIFIED:
            checks.append(check(policy, "AGE", RuleStatus.REVIEW_REQUIRED, "AGE_POLICY_CATEGORY_REQUIRED",
                                "The reference maturity-age category needs authorized review; it is never inferred.", evidence_ids))
        else:
            maximum_age = policy.maximum_maturity_age_years[profile.age_policy_category]
            age_ok = completed_years(profile.birth_date, maturity) <= maximum_age
            checks.append(check(policy, "AGE", RuleStatus.PASS if age_ok else RuleStatus.FAIL,
                                "MATURITY_AGE_MET" if age_ok else "MATURITY_AGE_EXCEEDED",
                                "Age at indicative maturity checked against the reference category.", evidence_ids))
    if profile.income_kind is None:
        checks.append(check(policy, "INCOME", RuleStatus.INFORMATION_REQUIRED, "INCOME_KIND_REQUIRED",
                            "Income type is missing.", evidence_ids))
    elif profile.income_kind != IncomeKind.SALARY:
        checks.append(check(policy, "INCOME", RuleStatus.REVIEW_REQUIRED, "INCOME_POLICY_REVIEW",
                            "Non-domestic-salary income requires product-specific review, not automatic refusal.", evidence_ids))
    else:
        start = profile.employment_start_date
        if start is None:
            checks.append(check(policy, "EMPLOYMENT", RuleStatus.INFORMATION_REQUIRED, "EMPLOYMENT_START_REQUIRED",
                                "Verified employment start date is missing.", evidence_ids))
        elif start > now.date() or (profile.birth_date is not None and start < profile.birth_date):
            checks.append(check(policy, "EMPLOYMENT", RuleStatus.REVIEW_REQUIRED, "INVALID_EMPLOYMENT_START",
                                "Employment start date requires correction.", evidence_ids))
        else:
            tenure_ok = add_months(start, policy.minimum_employment_months) <= now.date()
            checks.append(check(policy, "EMPLOYMENT", RuleStatus.PASS if tenure_ok else RuleStatus.FAIL,
                                "EMPLOYMENT_TENURE_MET" if tenure_ok else "EMPLOYMENT_TENURE_TOO_SHORT",
                                "Current-employer tenure checked in calendar months.", evidence_ids))
        if profile.employment_contract is None:
            checks.append(check(policy, "EMPLOYMENT", RuleStatus.INFORMATION_REQUIRED, "CONTRACT_TYPE_REQUIRED",
                                "Employment contract type is missing.", evidence_ids))
        elif profile.employment_contract == EmploymentContract.INDEFINITE:
            if profile.employment_end_date is not None:
                checks.append(check(policy, "EMPLOYMENT", RuleStatus.REVIEW_REQUIRED, "EMPLOYMENT_CONTRACT_CONFLICT",
                                    "An indefinite contract with an end date requires clarification.", evidence_ids))
            else:
                checks.append(check(policy, "EMPLOYMENT", RuleStatus.PASS, "INDEFINITE_CONTRACT",
                                    "The verified contract is indefinite.", evidence_ids))
        else:
            end = profile.employment_end_date
            if end is None:
                checks.append(check(policy, "EMPLOYMENT", RuleStatus.INFORMATION_REQUIRED, "CONTRACT_END_REQUIRED",
                                    "Fixed-term contract end date is required.", evidence_ids))
            elif end < now.date() or (start is not None and end < start):
                checks.append(check(policy, "EMPLOYMENT", RuleStatus.REVIEW_REQUIRED, "INVALID_EMPLOYMENT_CONTRACT",
                                    "The contract has expired or its dates conflict.", evidence_ids))
            elif end >= maturity:
                checks.append(check(policy, "EMPLOYMENT", RuleStatus.PASS, "CONTRACT_COVERS_LOAN",
                                    "The fixed-term contract covers indicative maturity.", evidence_ids))
            elif profile.successive_contract_renewals is None:
                checks.append(check(policy, "EMPLOYMENT", RuleStatus.INFORMATION_REQUIRED, "CONTRACT_RENEWALS_REQUIRED",
                                    "A shorter fixed-term contract needs successive-renewal evidence.", evidence_ids))
            else:
                renewals_ok = profile.successive_contract_renewals >= policy.minimum_successive_renewals
                checks.append(check(policy, "EMPLOYMENT", RuleStatus.PASS if renewals_ok else RuleStatus.FAIL,
                                    "CONTRACT_RENEWALS_MET" if renewals_ok else "CONTRACT_RENEWALS_INSUFFICIENT",
                                    "Successive renewals checked for the shorter fixed-term contract.", evidence_ids))
    return tuple(checks)


def identity_check(application: ApplicationSnapshot, policy: EligibilityPolicy, now: datetime) -> RuleCheck:
    document = application.identity_document
    problem = evidence_problem(document, EvidenceSource.DOCUMENT, policy, now)
    if document is not None and (document.document_kind != "IDENTITY" or document.expires_on is None):
        problem = "IDENTITY_VALIDITY_REQUIRED"
    status = RuleStatus.PASS
    if problem == "MISSING_EVIDENCE":
        status = RuleStatus.INFORMATION_REQUIRED
    elif problem is not None:
        status = RuleStatus.REVIEW_REQUIRED
    return check(policy, "IDENTITY", status, problem or "IDENTITY_VERIFIED",
                 "A verified, unexpired identity document is required; extraction alone is insufficient.",
                 (document.evidence_id,) if document is not None else ())


def income_checks(
    application: ApplicationSnapshot, data: IncomeVerificationData,
    evidence: EvidenceReference, policy: EligibilityPolicy, now: datetime,
) -> tuple[RuleCheck, ...]:
    ids = (evidence.evidence_id,)
    if data.income_basis == IncomeBasis.ANNUAL_AVERAGE:
        return (check(policy, "INCOME", RuleStatus.REVIEW_REQUIRED, "ANAF_HISTORICAL_INCOME_ONLY",
                      f"ANAF fiscal year {data.fiscal_year} provides a historical average only; it is not current verified recurring income.", ids),)
    if data.income_kind != application.profile.income_kind:
        return (check(policy, "INCOME", RuleStatus.REVIEW_REQUIRED, "INCOME_TYPE_MISMATCH",
                      "Verified income type conflicts with the profile.", ids),)
    if data.income_kind != IncomeKind.SALARY:
        return (check(policy, "INCOME", RuleStatus.REVIEW_REQUIRED, "INCOME_POLICY_REVIEW",
                      "This income needs product-specific review.", ids),)
    if data.period_end > now.date() or (now.date() - data.period_end).days > policy.income_period_max_age_days:
        return (check(policy, "INCOME", RuleStatus.REVIEW_REQUIRED, "INCOME_PERIOD_INVALID",
                      "The income period is future-dated or too old for the demo policy.", ids),)
    if not data.recurring:
        return (check(policy, "INCOME", RuleStatus.REVIEW_REQUIRED, "INCOME_NOT_RECURRING",
                      "Income stability requires independent review.", ids),)
    if application.declared_net_income_ron is not None and application.declared_net_income_ron != data.net_monthly_income_ron:
        return (check(policy, "INCOME", RuleStatus.REVIEW_REQUIRED, "INCOME_AMOUNT_MISMATCH",
                      "Declared and externally verified net income differ.", ids),)
    meets = data.net_monthly_income_ron >= policy.minimum_net_income_ron
    return (check(policy, "INCOME", RuleStatus.PASS if meets else RuleStatus.FAIL,
                  "MINIMUM_INCOME_MET" if meets else "BELOW_CONFIGURED_MINIMUM_INCOME",
                  "Net income checked against the explicitly synthetic configured threshold.", ids),)


def history_checks(data: CreditBureauData, evidence: EvidenceReference, policy: EligibilityPolicy) -> tuple[RuleCheck, ...]:
    ids = (evidence.evidence_id,)
    if data.disputed:
        status, code = RuleStatus.REVIEW_REQUIRED, "CREDIT_HISTORY_DISPUTED"
    elif data.has_enforced_loans is None or data.has_large_repeated_delays is None:
        status, code = RuleStatus.REVIEW_REQUIRED, "CREDIT_HISTORY_CLASSIFICATION_REQUIRED"
    elif data.has_enforced_loans or data.has_large_repeated_delays:
        status, code = RuleStatus.FAIL, "ADVERSE_CREDIT_HISTORY"
    elif data.payment_incidents:
        status, code = RuleStatus.REVIEW_REQUIRED, "CREDIT_HISTORY_CONTEXT_REQUIRED"
    else:
        status, code = RuleStatus.PASS, "CREDIT_HISTORY_REQUIREMENT_MET"
    return (
        check(policy, "CREDIT_HISTORY", status, code,
              "Bureau history assessed using verified classifications, without invented arrears thresholds.", ids),
        check(policy, "CREDIT_HISTORY", RuleStatus.NOT_APPLICABLE,
              "FICO_INFORMATIONAL" if data.fico_score is not None else "FICO_NOT_AVAILABLE",
              "No automatic FICO cutoff is configured; bureau registration or missing score alone is not a refusal.", ids),
    )


def affordability_checks(
    application: ApplicationSnapshot, income: IncomeVerificationData | None,
    bureau: CreditBureauData | None, internal: LoanVerificationData | None,
    scenario: PricingScenario | None, policy: EligibilityPolicy, now: datetime,
    evidence_ids: tuple[str, ...],
) -> tuple[tuple[RuleCheck, ...], FinancialAssessment | None]:
    if income is None or bureau is None or internal is None:
        return ((check(policy, "AFFORDABILITY", RuleStatus.INFORMATION_REQUIRED, "FINANCIAL_EVIDENCE_REQUIRED",
                       "Income, bureau and internal-obligation verification are needed for affordability."),), None)
    if not bureau.complete or not internal.complete:
        return ((check(policy, "OBLIGATIONS", RuleStatus.REVIEW_REQUIRED, "INCOMPLETE_OBLIGATION_REPORT",
                       "Debt reports must be complete before affordability can pass.", evidence_ids),), None)
    if scenario is None:
        return ((check(policy, "AFFORDABILITY", RuleStatus.INFORMATION_REQUIRED, "PRICING_SCENARIO_REQUIRED",
                       "Basic screening is available, but full affordability needs an indicative pricing scenario."),), None)
    problem = evidence_problem(scenario.evidence, EvidenceSource.PRICING, policy, now)
    if problem is not None:
        return ((check(policy, "AFFORDABILITY", RuleStatus.REVIEW_REQUIRED, problem,
                       "A current, verified pricing scenario is required.", (scenario.evidence.evidence_id,)),), None)
    with localcontext() as context:
        context.prec = 40
        expected_principal = application.request.amount_ron + scenario.financed_costs_ron
    if (
        scenario.application_id != application.application_id
        or scenario.customer_id != application.customer_id
        or scenario.term_months != application.request.term_months
        or scenario.principal_ron != expected_principal
    ):
        return ((check(policy, "AFFORDABILITY", RuleStatus.REVIEW_REQUIRED, "PRICING_SCENARIO_MISMATCH",
                       "Pricing ownership, term or financed-principal breakdown conflicts with the application.", (scenario.evidence.evidence_id,)),), None)
    if not policy.minimum_amount_ron <= scenario.principal_ron <= policy.maximum_amount_ron:
        return ((check(policy, "AFFORDABILITY", RuleStatus.FAIL, "FINANCED_PRINCIPAL_OUTSIDE_BOUNDS",
                       "Financed costs push the total principal outside the configured product bounds.", (scenario.evidence.evidence_id,)),), None)
    if income.net_monthly_income_ron == 0:
        return ((check(policy, "AFFORDABILITY", RuleStatus.NOT_APPLICABLE, "ZERO_INCOME_NO_DTI",
                       "No ratio is calculated for verified zero income; the minimum-income rule still applies."),), None)
    if income.income_kind != IncomeKind.SALARY or not income.recurring:
        return ((check(policy, "AFFORDABILITY", RuleStatus.REVIEW_REQUIRED, "USABLE_INCOME_REQUIRED",
                       "Verified recurring domestic-salary income is required for this automatic calculation."),), None)
    try:
        existing = reconcile_monthly_debt(bureau.obligations, internal.obligations, policy.revolving_limit_factor)
        proposed = proposed_monthly_debt(scenario)
    except FinancialInputError:
        return ((check(policy, "OBLIGATIONS", RuleStatus.REVIEW_REQUIRED, "OBLIGATION_RECONCILIATION_REQUIRED",
                       "Missing, conflicting, foreign-currency or unequal-payment evidence requires review.", evidence_ids),), None)
    with localcontext() as context:
        context.prec = 40
        total = existing + proposed
    if total >= Decimal("1000000000000"):
        return ((check(policy, "OBLIGATIONS", RuleStatus.REVIEW_REQUIRED, "OBLIGATION_TOTAL_OUT_OF_RANGE",
                       "The combined debt service exceeds the supported monetary range.", evidence_ids),), None)
    with localcontext() as context:
        context.prec = 40
        ratio = total / income.net_monthly_income_ron
        remaining = max(Decimal("0"), income.net_monthly_income_ron * policy.maximum_debt_to_income_ratio - existing)
        capacity = remaining.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    # Capacity is indicative; do not round it upward above the exact configured cap.
    financial = FinancialAssessment(
        verified_net_income_ron=income.net_monthly_income_ron,
        existing_monthly_debt_ron=existing, proposed_monthly_debt_ron=proposed,
        total_monthly_debt_ron=total, debt_to_income_ratio=ratio,
        maximum_debt_to_income_ratio=policy.maximum_debt_to_income_ratio,
        remaining_installment_capacity_ron=capacity,
    )
    passed = within_dti_limit(total, income.net_monthly_income_ron, policy.maximum_debt_to_income_ratio)
    return ((check(policy, "AFFORDABILITY", RuleStatus.PASS if passed else RuleStatus.FAIL,
                   "DTI_WITHIN_LIMIT" if passed else "DTI_EXCEEDS_LIMIT",
                   "Existing and proposed monthly service checked before ratio-display rounding; no automatic derogation.",
                   evidence_ids + (scenario.evidence.evidence_id,)),), financial)