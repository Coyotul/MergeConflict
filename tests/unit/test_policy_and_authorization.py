import unittest
from datetime import timedelta

from pydantic import ValidationError

from src.core.eligibility_errors import AccessDenied
from src.models.eligibility import AuthorizationScope, EligibilityCheckRequest, LoanRequest
from src.security.eligibility import ActorContext, ActorRole, authorization_is_valid, authorize_assessment
from src.services.eligibility.policy import load_policy, select_policy
from tests.fixtures.eligibility import CUSTOMER, NOW, REVIEWER, application, changed_model


class PolicyAndAuthorizationTests(unittest.TestCase):
    def test_policy_provenance_and_hash_are_reproducible(self):
        policy = load_policy()
        self.assertEqual(len(policy.digest()), 64)
        self.assertEqual(policy.digest(), load_policy().digest())
        self.assertTrue(policy.is_effective(NOW.date()))
        self.assertTrue(any("synthetic" in a.lower() for a in policy.assumptions))

    def test_regulatory_caps_cannot_be_relaxed_by_configuration(self):
        policy = load_policy()
        for changes in ({"maximum_debt_to_income_ratio": "0.45"}, {"revolving_limit_factor": "0.02"},
                        {"maximum_term_months": 120}, {"maximum_debt_to_income_ratio": "0"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                changed_model(policy, **changes)

    def test_conflicting_or_missing_effective_policy_is_not_selected(self):
        policy = load_policy()
        self.assertEqual(select_policy((policy,), policy.product_id, NOW.date()), policy)
        for policies, product, date in [((policy, policy), policy.product_id, NOW.date()),
                                       ((policy,), "mortgage", NOW.date()),
                                       ((policy,), policy.product_id, (NOW + timedelta(days=100)).date())]:
            with self.subTest(product=product, date=date), self.assertRaises(ValueError):
                select_policy(policies, product, date)

    def test_missing_source_and_inverted_bounds_invalid(self):
        policy = load_policy()
        for changes in ({"minimum_amount_ron": "300000"}, {"minimum_term_months": 61},
                        {"effective_to": "2020-01-01"}, {"rule_sources": {}},
                        {"maximum_maturity_age_years": {"MALE_REFERENCE": 65}}):
            with self.assertRaises(ValidationError):
                changed_model(policy, **changes)

    def test_owner_and_assigned_reviewer_authorized(self):
        authorize_assessment(CUSTOMER, application())
        authorize_assessment(REVIEWER, application())

    def test_cross_customer_unassigned_staff_and_missing_permission_denied(self):
        for actor in (
            ActorContext("other", ActorRole.CUSTOMER, customer_id="other", permissions=CUSTOMER.permissions),
            ActorContext("unassigned", ActorRole.REVIEWER, permissions=CUSTOMER.permissions),
            ActorContext("readonly", ActorRole.CUSTOMER, customer_id="demo-customer", permissions=frozenset({"eligibility:read"})),
            ActorContext("service", ActorRole.SERVICE, permissions=CUSTOMER.permissions),
        ):
            with self.subTest(actor=actor.actor_id), self.assertRaises(AccessDenied):
                authorize_assessment(actor, application())

    def test_anaf_consent_is_not_interchangeable_with_legitimate_interest(self):
        record = application().authorizations[0]
        self.assertTrue(authorization_is_valid(record, AuthorizationScope.INCOME_VERIFICATION, "demo-customer", NOW))
        changed = changed_model(record, legal_basis="LEGITIMATE_INTEREST")
        self.assertFalse(authorization_is_valid(changed, AuthorizationScope.INCOME_VERIFICATION, "demo-customer", NOW))
        changed = changed_model(record, consent_recorded_at=None)
        self.assertFalse(authorization_is_valid(changed, AuthorizationScope.INCOME_VERIFICATION, "demo-customer", NOW))

    def test_authorization_scope_owner_expiry_notice_and_revocation(self):
        record = application().authorizations[1]
        self.assertTrue(authorization_is_valid(record, AuthorizationScope.BUREAU_PRECHECK, "demo-customer", NOW))
        for changes in ({"customer_id": "other"}, {"notice_acknowledged": False},
                        {"expires_at": NOW}, {"revoked_at": NOW},
                        {"recorded_at": NOW + timedelta(seconds=1)}, {"scope": "INTERNAL_LOANS"}):
            with self.subTest(changes=changes):
                self.assertFalse(authorization_is_valid(changed_model(record, **changes), AuthorizationScope.BUREAU_PRECHECK, "demo-customer", NOW))

    def test_float_money_bool_term_and_unknown_request_fields_rejected(self):
        for money in (1.1, True, "NaN", "Infinity", "-1"):
            with self.subTest(money=money), self.assertRaises(ValidationError):
                LoanRequest(product_id="personal_loan_ron", amount_ron=money, term_months=60)
        with self.assertRaises(ValidationError):
            LoanRequest(product_id="personal_loan_ron", amount_ron="10000", term_months=True)
        with self.assertRaises(ValidationError):
            EligibilityCheckRequest(application_id="demo-app-eligible", idempotency_key="test-key-0001", consent=True)