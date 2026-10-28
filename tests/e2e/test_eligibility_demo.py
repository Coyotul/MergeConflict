import unittest

from scripts.eligibility_demo import run_demo


class EligibilityDemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_synthetic_journeys_have_expected_preliminary_outcomes(self):
        results = await run_demo()
        expected = {
            "demo-app-eligible": "PRELIMINARY_REQUIREMENTS_SATISFIED",
            "demo-app-high-dti": "PRELIMINARY_REQUIREMENTS_NOT_SATISFIED",
            "demo-app-missing-id": "ADDITIONAL_INFORMATION_REQUIRED",
            "demo-app-adverse-history": "PRELIMINARY_REQUIREMENTS_NOT_SATISFIED",
            "demo-app-bureau-unavailable": "MANUAL_REVIEW_REQUIRED",
            "demo-app-missing-consent": "ADDITIONAL_INFORMATION_REQUIRED",
        }
        self.assertEqual({item["application"]: item["status"] for item in results}, expected)
        for item in results:
            self.assertTrue(item["simulated"])
            self.assertTrue(item["human_review_required"])
            self.assertFalse(item["final_credit_decision"])
        self.assertEqual(results[0]["financial_assessment"]["existing_monthly_debt_ron"], "1000.00")
        self.assertEqual(results[0]["financial_assessment"]["proposed_monthly_debt_ron"], "646.66")