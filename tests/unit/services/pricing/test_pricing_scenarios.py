"""Unit tests for loan pricing simulation scenarios and boundary validation.

Compatible with both unittest and pytest test runners.
"""

from datetime import date
from decimal import Decimal as D
import json
from pathlib import Path
import unittest

from src.services.pricing.models import (
    EarlyRepaymentRequest,
    ExistingLoan,
    LoanOfferRequest,
    RefinancingRequest,
)
from src.services.pricing.service import (
    calculate_loan_offer,
    compare_refinancing_options,
    simulate_early_repayment,
)


class PricingScenariosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_dir = Path("data/test_samples_pricing")
        cls.ref_date = date(2026, 10, 28)

    def test_scenario_01_personal_loan_standard_offer(self):
        json_path = self.base_dir / "01_personal_loan_standard_offer.json"
        self.assertTrue(json_path.exists())
        data = json.loads(json_path.read_text(encoding="utf-8"))

        req = LoanOfferRequest.model_validate(data["request"])
        res = calculate_loan_offer(req)

        exp = data["expected_results"]
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.first_monthly_payment, D(exp["first_monthly_payment"]))
        self.assertEqual(res.dae, D(exp["dae"]))
        self.assertEqual(res.rate.rate_periods[0].annual_rate, D(exp["annual_rate"]))
        self.assertLessEqual(abs(res.totals.total_payable - D(exp["total_payable"])), D("0.05"))
        self.assertIsNotNone(res.affordability)
        self.assertTrue(res.affordability.within_limit)
        self.assertEqual(res.affordability.debt_service_ratio, D(exp["debt_service_ratio"]))

    def test_scenario_02_mortgage_casa_ta_simulation(self):
        json_path = self.base_dir / "02_mortgage_casa_ta_simulation.json"
        self.assertTrue(json_path.exists())
        data = json.loads(json_path.read_text(encoding="utf-8"))

        req = LoanOfferRequest.model_validate(data["request"])
        res = calculate_loan_offer(req)

        exp = data["expected_results"]
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.first_monthly_payment, D(exp["first_monthly_payment"]))
        self.assertEqual(res.monthly_payment_after_fixed_period, D(exp["monthly_payment_after_fixed_period"]))
        self.assertEqual(res.rate.rate_periods[0].annual_rate, D(exp["fixed_annual_rate"]))
        self.assertEqual(res.loan_to_value_percent, D(exp["loan_to_value_percent"]))
        self.assertTrue(res.affordability.within_limit)
        self.assertEqual(res.affordability.limit, D(exp["affordability_limit"]))

    def test_scenario_03_early_repayment_prepayment(self):
        json_path = self.base_dir / "03_early_repayment_prepayment.json"
        self.assertTrue(json_path.exists())
        data = json.loads(json_path.read_text(encoding="utf-8"))

        loan_req = LoanOfferRequest.model_validate(data["loan_request"])

        # Reduce term
        req_term = EarlyRepaymentRequest(
            loan=loan_req,
            after_month=data["simulation_parameters"]["after_month"],
            amount=D(data["simulation_parameters"]["repayment_amount"]),
            option="reduce_term",
        )
        res_term = simulate_early_repayment(req_term)
        exp_term = data["expected_results"]["reduce_term_option"]

        self.assertEqual(res_term.status, "ok")
        self.assertEqual(res_term.early_repayment_fee, D(exp_term["early_repayment_fee"]))
        self.assertEqual(res_term.new_last_month, exp_term["new_last_month"])
        self.assertEqual(res_term.interest_saved, D(exp_term["interest_saved"]))
        self.assertEqual(res_term.net_saving, D(exp_term["net_saving"]))

        # Reduce installment
        req_inst = EarlyRepaymentRequest(
            loan=loan_req,
            after_month=data["simulation_parameters"]["after_month"],
            amount=D(data["simulation_parameters"]["repayment_amount"]),
            option="reduce_instalment",
        )
        res_inst = simulate_early_repayment(req_inst)
        exp_inst = data["expected_results"]["reduce_installment_option"]

        self.assertEqual(res_inst.status, "ok")
        self.assertEqual(res_inst.early_repayment_fee, D(exp_inst["early_repayment_fee"]))
        self.assertEqual(res_inst.new_monthly_payment, D(exp_inst["new_monthly_payment"]))
        self.assertEqual(res_inst.net_saving, D(exp_inst["net_saving"]))

    def test_scenario_04_refinancing_consolidation(self):
        json_path = self.base_dir / "04_refinancing_consolidation.json"
        self.assertTrue(json_path.exists())
        data = json.loads(json_path.read_text(encoding="utf-8"))

        req = RefinancingRequest.model_validate(data["request"])
        res = compare_refinancing_options(req)

        exp = data["expected_results"]
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.current_monthly_payment, D(exp["current_monthly_payment"]))
        self.assertEqual(res.new_monthly_payment, D(exp["new_monthly_payment"]))
        self.assertEqual(res.outcome, exp["outcome"])
        self.assertEqual(res.early_repayment_fees_on_current_loans, D(exp["early_repayment_fees_on_current_loans"]))

    def test_scenario_05_rejected_boundary_limits(self):
        json_path = self.base_dir / "05_rejected_boundary_limits.json"
        self.assertTrue(json_path.exists())
        data = json.loads(json_path.read_text(encoding="utf-8"))

        for c in data["cases"]:
            with self.subTest(case=c["test_case"]):
                c_type = c.get("type", "loan_offer")
                if c_type == "loan_offer":
                    res = calculate_loan_offer(LoanOfferRequest.model_validate(c["request"]))
                else:
                    loan_req = LoanOfferRequest.model_validate(c["loan_request"])
                    res = simulate_early_repayment(EarlyRepaymentRequest(
                        loan=loan_req,
                        after_month=c["after_month"],
                        amount=D(c["repayment_amount"]),
                    ))
                self.assertEqual(res.status, "invalid")
                self.assertTrue(any(e.code == c["expected_error_code"] and c["expected_message_substring"] in e.message for e in res.errors))


if __name__ == "__main__":
    unittest.main()
