import unittest
from datetime import date, timedelta
from decimal import Decimal

from src.models.eligibility import AssessmentStatus, EvidenceSource, RuleStatus
from src.rules.eligibility.calendar import add_months, completed_years
from src.rules.eligibility.engine import (
    affordability_checks, aggregate_status, check, evidence_problem, history_checks,
    identity_check, income_checks, product_checks, profile_checks,
)
from src.services.eligibility.policy import load_policy
from tests.fixtures.eligibility import NOW, application, changed_model, verification_models


class EligibilityRuleTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()
        self.application = application()
        self.results = verification_models()

    def codes(self, checks):
        return {item.reason_code: item.status for item in checks}

    def profile(self, **changes):
        profile = changed_model(self.application.profile, **changes)
        return changed_model(self.application, profile=profile.model_dump(mode="json"))

    def test_calendar_months_clamp_and_leap_years(self):
        self.assertEqual(add_months(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(add_months(date(2023, 1, 31), 1), date(2023, 2, 28))
        self.assertEqual(add_months(date(2024, 2, 29), 12), date(2025, 2, 28))
        self.assertEqual(completed_years(date(2000, 2, 29), date(2021, 2, 28)), 20)

    def test_minimum_age_exactly_21_and_day_before(self):
        for birthday, expected in [("2005-10-28", "MINIMUM_AGE_MET"), ("2005-10-29", "BELOW_MINIMUM_AGE")]:
            with self.subTest(birthday=birthday):
                self.assertIn(expected, self.codes(profile_checks(self.profile(birth_date=birthday), self.policy, NOW)))

    def test_maturity_age_uses_maturity_not_today(self):
        item = self.profile(birth_date="1963-10-28")
        self.assertIn("MATURITY_AGE_EXCEEDED", self.codes(profile_checks(item, self.policy, NOW)))

    def test_both_maturity_category_boundaries(self):
        for category, birth, expected in [
            ("FEMALE_REFERENCE", "1968-10-28", "MATURITY_AGE_MET"),
            ("FEMALE_REFERENCE", "1967-10-28", "MATURITY_AGE_EXCEEDED"),
            ("MALE_REFERENCE", "1966-10-28", "MATURITY_AGE_MET"),
            ("MALE_REFERENCE", "1965-10-28", "MATURITY_AGE_EXCEEDED"),
        ]:
            with self.subTest(category=category, birth=birth):
                self.assertIn(expected, self.codes(profile_checks(self.profile(birth_date=birth, age_policy_category=category), self.policy, NOW)))

    def test_unspecified_category_never_inferred(self):
        codes = self.codes(profile_checks(self.profile(age_policy_category="UNSPECIFIED"), self.policy, NOW))
        self.assertEqual(codes["AGE_POLICY_CATEGORY_REQUIRED"], RuleStatus.REVIEW_REQUIRED)

    def test_future_and_missing_birth_dates(self):
        for birth, code in [(None, "BIRTH_DATE_REQUIRED"), ("2027-01-01", "INVALID_BIRTH_DATE")]:
            self.assertIn(code, self.codes(profile_checks(self.profile(birth_date=birth), self.policy, NOW)))

    def test_three_calendar_months_not_90_days(self):
        for start, expected in [("2026-07-28", "EMPLOYMENT_TENURE_MET"), ("2026-07-29", "EMPLOYMENT_TENURE_TOO_SHORT")]:
            with self.subTest(start=start):
                self.assertIn(expected, self.codes(profile_checks(self.profile(employment_start_date=start), self.policy, NOW)))

    def test_fixed_term_covering_maturity(self):
        item = self.profile(employment_contract="FIXED_TERM", employment_end_date="2031-10-28")
        self.assertIn("CONTRACT_COVERS_LOAN", self.codes(profile_checks(item, self.policy, NOW)))

    def test_short_fixed_term_two_renewals_and_missing_evidence(self):
        for count, expected in [(2, "CONTRACT_RENEWALS_MET"), (1, "CONTRACT_RENEWALS_INSUFFICIENT"), (None, "CONTRACT_RENEWALS_REQUIRED")]:
            with self.subTest(count=count):
                item = self.profile(employment_contract="FIXED_TERM", employment_end_date="2027-01-01", successive_contract_renewals=count)
                self.assertIn(expected, self.codes(profile_checks(item, self.policy, NOW)))

    def test_expired_contract_requires_review(self):
        item = self.profile(employment_contract="FIXED_TERM", employment_end_date="2026-01-01")
        self.assertIn("INVALID_EMPLOYMENT_CONTRACT", self.codes(profile_checks(item, self.policy, NOW)))

    def test_other_income_is_review_not_automatic_refusal(self):
        for kind in ("PENSION", "FOREIGN_SALARY", "SELF_EMPLOYED", "RENTAL", "DIVIDENDS"):
            with self.subTest(kind=kind):
                codes = self.codes(profile_checks(self.profile(income_kind=kind), self.policy, NOW))
                self.assertEqual(codes["INCOME_POLICY_REVIEW"], RuleStatus.REVIEW_REQUIRED)

    def test_amount_and_term_boundaries(self):
        for amount, term, amount_ok, term_ok in [
            ("2500", 18, True, True), ("250000", 60, True, True),
            ("2499.99", 17, False, False), ("250000.01", 61, False, False),
        ]:
            with self.subTest(amount=amount, term=term):
                item = changed_model(self.application, request={"product_id": "personal_loan_ron", "amount_ron": amount, "term_months": term})
                results = product_checks(item, self.policy)
                self.assertEqual(results[0].status == RuleStatus.PASS, amount_ok)
                self.assertEqual(results[1].status == RuleStatus.PASS, term_ok)

    def test_identity_is_verified_unexpired_and_correct_kind(self):
        self.assertEqual(identity_check(self.application, self.policy, NOW).status, RuleStatus.PASS)
        self.assertEqual(identity_check(changed_model(self.application, identity_document=None), self.policy, NOW).status, RuleStatus.INFORMATION_REQUIRED)
        for changes in ({"status": "UNVERIFIED"}, {"expires_on": "2026-01-01"}, {"document_kind": "INCOME"}, {"expires_on": None}):
            with self.subTest(changes=changes):
                doc = changed_model(self.application.identity_document, **changes)
                item = changed_model(self.application, identity_document=doc.model_dump(mode="json"))
                self.assertEqual(identity_check(item, self.policy, NOW).status, RuleStatus.REVIEW_REQUIRED)

    def test_evidence_freshness_boundary_and_future(self):
        original = self.results[EvidenceSource.ANAF].evidence
        for age, expected in [(30, None), (31, "STALE_EVIDENCE"), (-1, "FUTURE_EVIDENCE")]:
            evidence = changed_model(original, recorded_at=NOW - timedelta(days=age))
            self.assertEqual(evidence_problem(evidence, EvidenceSource.ANAF, self.policy, NOW), expected)

    def test_declared_income_mismatch_is_review(self):
        item = changed_model(self.application, declared_net_income_ron="8000")
        result = self.results[EvidenceSource.ANAF]
        codes = self.codes(income_checks(item, result.data, result.evidence, self.policy, NOW))
        self.assertEqual(codes["INCOME_AMOUNT_MISMATCH"], RuleStatus.REVIEW_REQUIRED)

    def test_synthetic_income_threshold_exact_boundary(self):
        result = self.results[EvidenceSource.ANAF]
        for amount, expected in [("2700", RuleStatus.PASS), ("2699.99", RuleStatus.FAIL), ("0", RuleStatus.FAIL)]:
            data = changed_model(result.data, net_monthly_income_ron=amount)
            item = changed_model(self.application, declared_net_income_ron=amount)
            self.assertEqual(income_checks(item, data, result.evidence, self.policy, NOW)[0].status, expected)

    def test_old_future_and_nonrecurring_income_require_review(self):
        result = self.results[EvidenceSource.ANAF]
        for changes in ({"period_end": "2026-01-01"}, {"period_end": "2027-01-01"}, {"recurring": False}):
            data = changed_model(result.data, **changes)
            self.assertEqual(income_checks(self.application, data, result.evidence, self.policy, NOW)[0].status, RuleStatus.REVIEW_REQUIRED)

    def test_no_fico_cutoff_and_missing_score(self):
        result = self.results[EvidenceSource.CREDIT_BUREAU]
        for score in (300, 850, None):
            checks = history_checks(changed_model(result.data, fico_score=score), result.evidence, self.policy)
            self.assertEqual(checks[0].status, RuleStatus.PASS)
            self.assertEqual(checks[1].status, RuleStatus.NOT_APPLICABLE)

    def test_disputed_adverse_and_unclassified_history(self):
        result = self.results[EvidenceSource.CREDIT_BUREAU]
        for changes, expected in [({"disputed": True, "has_enforced_loans": True}, RuleStatus.REVIEW_REQUIRED),
                                  ({"has_enforced_loans": True}, RuleStatus.FAIL),
                                  ({"has_large_repeated_delays": None}, RuleStatus.REVIEW_REQUIRED)]:
            self.assertEqual(history_checks(changed_model(result.data, **changes), result.evidence, self.policy)[0].status, expected)

    def test_incident_is_not_rejected_by_reporting_threshold(self):
        result = self.results[EvidenceSource.CREDIT_BUREAU]
        incident = {"incident_id": "old-delay", "days_past_due": 31, "amount_ron": "100", "reported_on": "2025-01-01", "resolved": True}
        data = changed_model(result.data, payment_incidents=[incident])
        self.assertEqual(history_checks(data, result.evidence, self.policy)[0].status, RuleStatus.REVIEW_REQUIRED)

    def test_aggregation_precedence(self):
        def outcome(statuses):
            return aggregate_status(tuple(check(self.policy, "AGE", s, "TEST", "Test rule.") for s in statuses))
        self.assertEqual(outcome([RuleStatus.PASS]), AssessmentStatus.SATISFIED)
        self.assertEqual(outcome([RuleStatus.PASS, RuleStatus.INFORMATION_REQUIRED]), AssessmentStatus.INFORMATION_REQUIRED)
        self.assertEqual(outcome([RuleStatus.FAIL, RuleStatus.INFORMATION_REQUIRED]), AssessmentStatus.NOT_SATISFIED)
        self.assertEqual(outcome([RuleStatus.FAIL, RuleStatus.REVIEW_REQUIRED]), AssessmentStatus.REVIEW_REQUIRED)
        self.assertEqual(aggregate_status(()), AssessmentStatus.INFORMATION_REQUIRED)

    def test_contradictory_employment_dates_require_review(self):
        for changes, code in [({"employment_end_date": "2027-01-01"}, "EMPLOYMENT_CONTRACT_CONFLICT"),
                              ({"employment_start_date": "1980-01-01"}, "INVALID_EMPLOYMENT_START")]:
            item = self.profile(**changes)
            self.assertEqual(self.codes(profile_checks(item, self.policy, NOW))[code], RuleStatus.REVIEW_REQUIRED)

    def test_affordability_without_pricing_does_not_pass(self):
        income, bureau, internal = (self.results[s].data for s in (EvidenceSource.ANAF, EvidenceSource.CREDIT_BUREAU, EvidenceSource.INTERNAL_LOANS))
        checks, financial = affordability_checks(self.application, income, bureau, internal, None, self.policy, NOW, ())
        self.assertIsNone(financial)
        self.assertEqual(checks[0].reason_code, "PRICING_SCENARIO_REQUIRED")

    def test_quoted_financed_costs_match_principal(self):
        income, bureau, internal = (self.results[s].data for s in (EvidenceSource.ANAF, EvidenceSource.CREDIT_BUREAU, EvidenceSource.INTERNAL_LOANS))
        scenario = changed_model(self.application.pricing_scenarios[0], principal_ron="30000")
        checks, financial = affordability_checks(self.application, income, bureau, internal, scenario, self.policy, NOW, ())
        self.assertIsNone(financial)
        self.assertEqual(checks[0].reason_code, "PRICING_SCENARIO_MISMATCH")