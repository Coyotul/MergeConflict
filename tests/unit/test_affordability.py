import unittest
from decimal import Decimal, localcontext

from src.models.eligibility import DebtObligation
from src.services.financial_calculations.affordability import (
    FinancialInputError, liability_monthly_debt, proposed_monthly_debt,
    reconcile_monthly_debt, within_dti_limit,
)
from tests.fixtures.eligibility import application, changed_model


class AffordabilityTests(unittest.TestCase):
    def test_published_annuity_examples(self):
        original = application().pricing_scenarios[0]
        for rate, months, expected in [
            ("5.55", 60, "961.21"), ("5.55", 18, "2906.42"),
            ("10", 60, "1067.35"), ("17.95", 60, "1273.31"),
            ("5.55", 120, "548.87"),
        ]:
            with self.subTest(rate=rate, months=months):
                scenario = changed_model(original, principal_ron="50000.00",
                                         annual_interest_percent=rate, term_months=months)
                self.assertEqual(proposed_monthly_debt(scenario), Decimal(expected))

    def test_zero_interest_includes_monthly_costs_once(self):
        scenario = changed_model(application().pricing_scenarios[0], principal_ron="6000.00",
                                 term_months=60, annual_interest_percent="0", monthly_fee_ron="5",
                                 monthly_insurance_ron="10", financed_costs_ron="200")
        self.assertEqual(proposed_monthly_debt(scenario), Decimal("115.00"))

    def test_decreasing_payment_uses_first_highest_installment(self):
        scenario = changed_model(application().pricing_scenarios[0], principal_ron="60000.00",
                                 term_months=60, annual_interest_percent="12", repayment_type="DECREASING")
        self.assertEqual(proposed_monthly_debt(scenario), Decimal("1605.00"))

    def test_custom_unequal_pricing_requires_reviewed_maximum(self):
        scenario = changed_model(application().pricing_scenarios[0], repayment_type="UNEQUAL")
        with self.assertRaises(FinancialInputError):
            proposed_monthly_debt(scenario)

    def test_unused_revolving_limit_and_reported_payment_floor(self):
        debt = DebtObligation(liability_id="card", kind="REVOLVING", credit_limit="10000", monthly_payment="0")
        self.assertEqual(liability_monthly_debt(debt, Decimal(".03")), Decimal("300.00"))
        debt = changed_model(debt, monthly_payment="400")
        self.assertEqual(liability_monthly_debt(debt, Decimal(".03")), Decimal("400.00"))

    def test_revolving_floor_rounds_up_not_down(self):
        debt = DebtObligation(liability_id="card", kind="REVOLVING", credit_limit="100.01")
        self.assertEqual(liability_monthly_debt(debt, Decimal(".03")), Decimal("3.01"))

    def test_revolving_factor_cannot_be_less_than_three_percent(self):
        debt = DebtObligation(liability_id="card", kind="REVOLVING", credit_limit="100")
        with self.assertRaises(FinancialInputError):
            liability_monthly_debt(debt, Decimal(".02"))

    def test_missing_revolving_limit_is_not_zero(self):
        with self.assertRaises(FinancialInputError):
            liability_monthly_debt(DebtObligation(liability_id="card", kind="REVOLVING"), Decimal(".03"))

    def test_missing_installment_is_not_zero(self):
        with self.assertRaises(FinancialInputError):
            liability_monthly_debt(DebtObligation(liability_id="loan", kind="INSTALLMENT"), Decimal(".03"))

    def test_unequal_existing_loan_requires_maximum(self):
        debt = DebtObligation(liability_id="loan", kind="INSTALLMENT", repayment_type="UNEQUAL", monthly_payment="100")
        with self.assertRaises(FinancialInputError):
            liability_monthly_debt(debt, Decimal(".03"))
        debt = changed_model(debt, maximum_monthly_payment="250")
        self.assertEqual(liability_monthly_debt(debt, Decimal(".03")), Decimal("250"))
        with self.assertRaises(FinancialInputError):
            liability_monthly_debt(changed_model(debt, maximum_monthly_payment="50"), Decimal(".03"))

    def test_foreign_currency_is_not_implicitly_converted(self):
        debt = DebtObligation(liability_id="loan", kind="INSTALLMENT", currency="EUR", monthly_payment="100")
        with self.assertRaises(FinancialInputError):
            liability_monthly_debt(debt, Decimal(".03"))

    def test_inactive_loan_has_no_service(self):
        debt = DebtObligation(liability_id="closed", kind="INSTALLMENT", active=False)
        self.assertEqual(liability_monthly_debt(debt, Decimal(".03")), Decimal("0"))

    def test_canonical_duplicates_are_counted_once(self):
        debt = DebtObligation(liability_id="shared", kind="INSTALLMENT", monthly_payment="700")
        self.assertEqual(reconcile_monthly_debt((debt,), (debt,), Decimal(".03")), Decimal("700"))

    def test_conflicting_duplicates_are_not_silently_combined(self):
        debt = DebtObligation(liability_id="shared", kind="INSTALLMENT", monthly_payment="700")
        with self.assertRaises(FinancialInputError):
            reconcile_monthly_debt((debt,), (changed_model(debt, monthly_payment="100"),), Decimal(".03"))

    def test_same_amount_different_liability_ids_are_not_deduplicated(self):
        debt = DebtObligation(liability_id="one", kind="INSTALLMENT", monthly_payment="700")
        self.assertEqual(reconcile_monthly_debt((debt,), (changed_model(debt, liability_id="two"),), Decimal(".03")), Decimal("1400"))

    def test_dti_exact_boundary_and_one_cent_over(self):
        for debt, expected in [("1999.99", True), ("2000", True), ("2000.01", False)]:
            with self.subTest(debt=debt):
                self.assertEqual(within_dti_limit(Decimal(debt), Decimal("5000"), Decimal(".40")), expected)
        self.assertFalse(within_dti_limit(Decimal("0"), Decimal("0"), Decimal(".40")))

    def test_calculations_ignore_ambient_low_decimal_precision(self):
        scenario = changed_model(application().pricing_scenarios[0], principal_ron="50000", annual_interest_percent="5.55")
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(proposed_monthly_debt(scenario), Decimal("961.21"))
            self.assertFalse(within_dti_limit(Decimal("2000.01"), Decimal("5000"), Decimal(".40")))