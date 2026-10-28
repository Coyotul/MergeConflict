from decimal import Decimal

from tests.api_fixture import ApiFixture, request_key


class CapabilityApiTests(ApiFixture):
    def test_server_pricing_preliminary_screening_and_synthetic_sources(self):
        customer = self.login()
        products = self.call("GET", "/products", customer)
        self.assertEqual([item["id"] for item in products], ["personal", "mortgage", "car"])
        scenario = {"productId": "personal", "amount": "30000", "months": 36}
        quote = self.call("POST", "/calculations/loan-offer", customer, scenario)
        self.assertEqual(quote["annualRate"], "8.90")
        self.assertEqual(quote["fee"], "150.00")
        self.assertEqual(quote["schedule"][-1]["balance"], "0.00")
        self.assertTrue(quote["indicative"])
        self.call("POST", "/calculations/loan-offer", customer, {**scenario, "annualRate": "0"}, expected=400)
        self.call("POST", "/calculations/loan-offer", customer, {**scenario, "amount": "10"}, expected=400)
        self.call("POST", "/calculations/loan-offer", customer, {**scenario, "productId": "missing"}, expected=404)
        assessment = self.call("POST", "/calculations/affordability-preview", customer, scenario)
        self.assertEqual(assessment["status"], "PRELIMINARY_REQUIREMENTS_SATISFIED")
        self.assertTrue(assessment["humanReviewRequired"])
        self.assertEqual(assessment["scope"], "SYNTHETIC_AFFORDABILITY_PREVIEW_ONLY")
        self.assertIn("SYNTHETIC_UNVERIFIED_INPUTS", assessment["reasonCodes"])
        self.assertTrue(assessment["evidenceReferences"])
        policies = self.call("POST", "/policies/search", customer, {"query": "personal loan identity income", "productId": "personal"})
        self.assertEqual(policies["method"], "synthetic-keyword")
        self.assertEqual(policies["sources"][0]["id"], "personal-policy")
        self.assertTrue(all(source["version"] == "DEMO-2026.1" for source in policies["sources"]))
        empty = self.call("POST", "/policies/search", customer, {"query": "unmatchedvocabularyxyz"})
        self.assertEqual(empty["sources"], [])

    def test_document_metadata_is_never_presented_as_verified(self):
        customer = self.login()
        required = self.call("GET", "/products/personal/required-documents", customer)
        self.assertEqual(required["required"], ["identity", "income"])
        self.assertEqual(required["maxSizeBytes"], 10485760)
        result = self.call("POST", "/documents/validate", customer, {
            "kind": "income", "name": "synthetic.pdf", "mimeType": "application/pdf", "size": 1000, "syntheticConfirmed": True,
        })
        self.assertEqual(result["status"], "FORMAT_ACCEPTED")
        for field in ("authenticityVerified", "identityVerified", "incomeVerified"):
            self.assertFalse(result[field])
        self.assertTrue(result["metadataOnly"])

    def test_early_repayment_refinancing_and_owned_data_boundaries(self):
        customer = self.login()
        quote = self.call("POST", "/loans/loan-personal/early-repayment/simulate", customer, {"repayment": "5000"})
        self.assertEqual(quote["earlyFee"], "50.00")
        self.assertGreater(quote["monthsSaved"], 0)
        self.call("POST", "/loans/loan-personal/early-repayment/simulate", customer, {"repayment": "24750"}, expected=409)
        self.call("POST", "/loans/loan-personal/early-repayment/simulate", customer, {"repayment": "5000", "feePercent": "0"}, expected=400)
        refinance = self.call("POST", "/refinancing/compare", customer, {"loanIds": ["loan-personal", "loan-car"], "months": 60})
        self.assertEqual(refinance["principal"], "37550.00")
        self.assertGreater(Decimal(refinance["monthlySavings"]), 0)
        self.assertLess(Decimal(refinance["totalSavings"]), 0)
        self.call("POST", "/refinancing/compare", customer, {"loanIds": ["loan-personal"], "months": 600}, expected=400)
        loans = self.call("GET", "/customers/me/loans", customer)
        self.assertEqual(loans[0]["principal"], "24750.00")

    def test_notification_preferences_and_mandatory_workflow_updates(self):
        customer = self.login()
        original = self.call("POST", "/notifications", customer, {
            "title": "Demo reminder", "text": "Synthetic application reminder.", "idempotencyKey": request_key(),
        })
        self.assertFalse(original["mandatory"])
        self.call("PATCH", "/consent", customer, {"financialInsights": False, "notifications": False})
        self.call("POST", "/notifications", customer, {
            "title": "Not permitted", "text": "Optional notifications are disabled.", "idempotencyKey": request_key(),
        }, expected=403)
        application = self.ready_application(customer)
        self.submit(customer, application["id"])
        notifications = self.call("GET", "/notifications", customer)
        self.assertEqual(len(notifications), 2)
        self.assertTrue(notifications[0]["mandatory"])
        self.assertTrue(all(item["read"] for item in self.call("POST", "/notifications/read", customer, {})))

    def test_empty_assigned_reviewer_snapshot_does_not_leak_another_customer(self):
        reviewer = self.login("taylor@example.test", "reviewer")
        snapshot = self.call("GET", "/snapshot", reviewer)
        self.assertEqual(snapshot["applications"], [])
        self.assertEqual(snapshot["loans"], [])
        self.assertIsNone(snapshot["customer"])
        self.assertIsNone(snapshot["consent"])