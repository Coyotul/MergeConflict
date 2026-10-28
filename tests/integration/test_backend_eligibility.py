from datetime import timedelta

from fastapi.testclient import TestClient

from src.api.gateway.app import create_app
from src.core.eligibility_demo import load_reference_fixture
from src.storage.application_db.eligibility_bridge import WorkflowEligibilityRepository
from tests.api_fixture import ApiFixture, request_key


class BackendEligibilityTests(ApiFixture):
    def setUp(self):
        super().setUp()
        # Match the upstream reproducible reference-policy clock, not machine time.
        self.reference_time = load_reference_fixture().reference_time + timedelta(days=1)
        self.app.state.container.evidence_eligibility.service.clock = lambda: self.reference_time

    def assessment_input(self, application, key=None):
        return {"applicationId": application["id"], "pricingScenarioId": application["pricingScenarioId"], "idempotencyKey": key or request_key()}

    def test_shared_service_ids_only_missing_evidence_no_provider_call_and_audit(self):
        customer = self.login()
        application = self.create_application(customer)
        input = self.assessment_input(application)
        correlation = request_key()
        result = self.call("POST", "/eligibility/check", {**customer, "X-Correlation-ID": correlation}, input)
        self.assertEqual(result["status"], "ADDITIONAL_INFORMATION_REQUIRED")
        self.assertFalse(result["final_credit_decision"])
        self.assertTrue(result["human_review_required"])
        self.assertTrue(result["simulated"])
        self.assertIsNone(result["financial_assessment"])
        self.assertEqual(result["correlation_id"], correlation)
        codes = {check["reason_code"] for check in result["checks"]}
        self.assertIn("MISSING_EVIDENCE", codes)
        self.assertIn("ANAF_AUTHORIZATION_REQUIRED", codes)
        self.assertTrue(all(provider.calls == 0 for provider in self.app.state.container.evidence_eligibility.service.providers.values()))
        self.assertEqual(self.call("POST", "/eligibility/check", customer, input), result)
        self.assertEqual(self.call("GET", f"/eligibility/assessments/{result['assessment_id']}", customer), result)
        unchanged = self.call("GET", f"/applications/{application['id']}", customer)
        self.assertEqual(unchanged["status"], "AWAITING_DOCUMENTS")
        self.assertEqual(unchanged["revision"], application["revision"])
        audit = self.call("GET", "/audit", customer)
        checks = [event for event in audit if event["action"] == "PRELIMINARY_ELIGIBILITY_CHECKED"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["correlationId"], correlation)

    def test_metadata_never_becomes_verified_and_pricing_is_server_owned(self):
        customer = self.login()
        application = self.ready_application(customer)
        snapshot = WorkflowEligibilityRepository(self.app.state.container.repository).get_application(application["id"])
        self.assertEqual(snapshot.identity_document.status.value, "UNVERIFIED")
        self.assertIsNone(snapshot.profile_evidence)
        self.assertEqual(snapshot.authorizations, ())
        self.assertEqual(str(snapshot.pricing_scenarios[0].annual_interest_percent), "8.90")
        self.assertEqual(snapshot.pricing_scenarios[0].financed_costs_ron, 0)
        result = self.call("POST", "/eligibility/check", customer, self.assessment_input(application))
        self.assertEqual(result["status"], "MANUAL_REVIEW_REQUIRED")
        self.assertIn("IDENTITY_VALIDITY_REQUIRED", {check["reason_code"] for check in result["checks"]})
        identity = next(item for item in result["evidence"] if item["source"] == "DOCUMENT")
        self.assertEqual(identity["status"], "UNVERIFIED")
        self.assertEqual(self.call("GET", f"/applications/{application['id']}", customer)["status"], "READY_FOR_SUBMISSION")

    def test_no_evidence_income_or_consent_injection_and_role_assignment(self):
        customer = self.login()
        blake = self.login("blake@example.test")
        jamie = self.login("jamie@example.test", "reviewer")
        taylor = self.login("taylor@example.test", "reviewer")
        application = self.create_application(customer)
        input = self.assessment_input(application)
        for field in ("income", "role", "consent", "evidence", "annualRate", "profile"):
            self.call("POST", "/eligibility/check", customer, {**input, field: "injected"}, expected=400)
        for actor in (blake, taylor):
            denied = self.call("POST", "/eligibility/check", actor, input, expected=403)
            self.assertEqual(denied.json()["error"]["code"], "ACCESS_DENIED")
        result = self.call("POST", "/eligibility/check", jamie, input)
        self.call("GET", f"/eligibility/assessments/{result['assessment_id']}", blake, expected=403)
        self.call("GET", f"/eligibility/assessments/{result['assessment_id']}", taylor, expected=403)
        self.assertEqual(self.call("GET", f"/eligibility/assessments/{result['assessment_id']}", customer)["application_id"], application["id"])

    def test_reference_replay_snapshot_change_restart_and_terminal_state(self):
        customer = self.login()
        application = self.create_application(customer)
        input = self.assessment_input(application)
        first = self.call("POST", "/eligibility/check", customer, input)
        with TestClient(create_app(self.settings)) as restarted:
            login = restarted.post("/api/v1/session", json={"role": "customer", "email": "alex@example.test", "password": "ClientDemo123!"})
            renewed = {"Authorization": "Bearer " + login.json()["data"]["token"]}
            restarted.app.state.container.evidence_eligibility.service.clock = lambda: self.reference_time
            self.assertEqual(restarted.post("/api/v1/eligibility/check", headers=renewed, json=input).json()["data"], first)
        self.upload(customer, application["id"], "identity")
        self.call("POST", "/eligibility/check", customer, input, expected=409)
        self.assertEqual(self.call("GET", f"/eligibility/assessments/{first['assessment_id']}", customer), first)
        self.call("POST", f"/applications/{application['id']}/cancel", customer, {"reason": "Cancel this synthetic draft.", "idempotencyKey": request_key()})
        denied = self.call("POST", "/eligibility/check", customer, self.assessment_input(application), expected=409)
        self.assertEqual(denied.json()["error"]["code"], "INVALID_WORKFLOW_STATE")
        self.assertEqual(self.call("GET", f"/eligibility/assessments/{first['assessment_id']}", customer), first)

    def test_unsupported_product_and_expired_reference_policy_require_review(self):
        customer = self.login()
        application = self.create_application(customer, productId="mortgage", amount="300000.00", months=120)
        unsupported = self.call("POST", "/eligibility/check", customer, self.assessment_input(application))
        self.assertEqual(unsupported["status"], "MANUAL_REVIEW_REQUIRED")
        self.assertIn("UNSUPPORTED_PRODUCT", {check["reason_code"] for check in unsupported["checks"]})
        personal = self.create_application(customer)
        self.app.state.container.evidence_eligibility.service.clock = lambda: self.reference_time + timedelta(days=100)
        expired = self.call("POST", "/eligibility/check", customer, self.assessment_input(personal))
        self.assertEqual(expired["status"], "MANUAL_REVIEW_REQUIRED")
        self.assertIn("POLICY_NOT_EFFECTIVE", {check["reason_code"] for check in expired["checks"]})