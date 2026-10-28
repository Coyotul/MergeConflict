import unittest
from decimal import Decimal

from src.core.catalogue import Catalogue
from src.core.errors import DomainError
from src.core.settings import ROOT
from src.rules.eligibility.affordability import assess_affordability
from src.services.financial_calculations.engine import calculate_loan, compare_refinancing, simulate_repayment


class FinancialCalculationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue = Catalogue.load(ROOT)

    def test_known_annuity(self):
        quote = calculate_loan("12000", "12", 12)
        self.assertEqual(quote.installment, Decimal("1066.19"))
        self.assertEqual(len(quote.schedule), 12)
        self.assertEqual(quote.schedule[0].interest, Decimal("120.00"))
        self.assertEqual(quote.schedule[0].principal, Decimal("946.19"))
        self.assertEqual(quote.schedule[-1].balance, Decimal("0"))
        self.assertEqual(sum(row.principal for row in quote.schedule), Decimal("12000"))
        self.assertEqual(quote.total_cost - quote.amount, quote.interest_cost)

    def test_zero_interest_insurance_and_last_cents(self):
        quote = calculate_loan("1000", "0", 3, "10", "2")
        self.assertEqual(quote.installment, Decimal("333.33"))
        self.assertEqual(quote.monthly_payment, Decimal("335.33"))
        self.assertEqual(quote.schedule[-1].payment, Decimal("333.34"))
        self.assertEqual(quote.interest_cost, Decimal("0"))
        self.assertEqual(quote.total_cost, Decimal("1016.00"))

    def test_invalid_financial_inputs(self):
        for amount in ("0", "-1", "NaN", "Infinity", "1.001", "1e3", "hello", 1000.0, True, Decimal("NaN")):
            with self.subTest(amount=amount), self.assertRaises(DomainError):
                calculate_loan(amount, "8", 36)
        for months in (0, -1, 1.2, 601, True):
            with self.subTest(months=months), self.assertRaises(DomainError):
                calculate_loan("10000", "8", months)
        with self.assertRaises(DomainError):
            calculate_loan("10000", "101", 36)

    def test_schedule_conserves_principal_and_cash(self):
        for amount, rate, months in (("30000", "8.90", 36), ("1500000", "6.50", 360), ("200000", "7.90", 84)):
            with self.subTest(amount=amount):
                quote = calculate_loan(amount, rate, months, "150", "15")
                self.assertEqual(sum(row.principal for row in quote.schedule), Decimal(amount))
                self.assertEqual(quote.schedule[-1].balance, Decimal("0"))
                self.assertTrue(all(row.balance >= 0 for row in quote.schedule))
                self.assertTrue(all(row.payment == row.principal + row.interest for row in quote.schedule))
                self.assertEqual(quote.total_cost, sum(row.payment for row in quote.schedule) + Decimal("150") + Decimal("15") * len(quote.schedule))

    def test_partial_repayment_and_full_payoff_boundary(self):
        loan = self.catalogue.fixtures.loans[0]
        quote = simulate_repayment(loan, "5000", Decimal("1"), "TEST")
        self.assertEqual(quote.new_principal, Decimal("19750.00"))
        self.assertEqual(quote.early_fee, Decimal("50.00"))
        self.assertLess(quote.reduced_payment.monthly_payment, quote.current.monthly_payment)
        self.assertGreater(quote.months_saved, 0)
        self.assertGreater(quote.interest_savings, 0)
        self.assertEqual(quote.reduced_term.schedule[-1].balance, Decimal("0"))
        with self.assertRaises(DomainError) as raised:
            simulate_repayment(loan, str(loan.principal), Decimal("1"), "TEST")
        self.assertEqual(raised.exception.code, "SETTLEMENT_QUOTE_REQUIRED")

    def test_refinancing_does_not_equate_lower_payment_with_savings(self):
        quote = compare_refinancing(self.catalogue.fixtures.loans, Decimal("7.50"), 60, Decimal("250"), "TEST")
        self.assertEqual(quote.principal, Decimal("37550.00"))
        self.assertGreater(quote.monthly_savings, 0)
        self.assertLess(quote.total_savings, 0)

    def test_affordability_always_requires_human_review(self):
        quote = calculate_loan("30000", "8.90", 36)
        for income, expected in (("8500", "PRELIMINARY_REQUIREMENTS_SATISFIED"), ("2000", "MANUAL_REVIEW_REQUIRED")):
            result = assess_affordability(Decimal(income), Decimal("1000"), quote, Decimal("40"), "TEST", ["fixture"])
            self.assertEqual(result.status, expected)
            self.assertTrue(result.human_review_required)
            self.assertIn("HUMAN_REVIEW_REQUIRED", result.reason_codes)

    def test_decimal_wire_format(self):
        quote = calculate_loan("12000", "12", 12).model_dump(mode="json", by_alias=True)
        self.assertEqual(quote["amount"], "12000.00")
        self.assertEqual(quote["annualRate"], "12.00")
        self.assertIsInstance(quote["schedule"][0]["payment"], str)