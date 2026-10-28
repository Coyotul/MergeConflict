from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.gateway.app import create_app
from tests.api_fixture import ApiFixture, request_key


class HttpContractTests(ApiFixture):
    def test_openapi_contains_all_proposed_orchestrator_capabilities(self):
        schema = self.client.get("/openapi.json").json()
        operations = [operation for item in schema["paths"].values() for operation in item.values() if isinstance(operation, dict)]
        ids = [operation["operationId"] for operation in operations]
        expected = {
            "get_customer_profile", "get_customer_loans", "search_banking_policies", "get_required_documents",
            "validate_document", "run_eligibility_check", "calculate_loan_offer", "simulate_early_repayment",
            "compare_refinancing_options", "create_loan_application", "submit_application", "get_application_status",
            "request_human_review", "create_customer_notification",
        }
        self.assertTrue(expected <= set(ids))
        self.assertEqual({operation["operationId"] for operation in operations if operation["x-orchestrator-tool"]}, expected)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(path == "/health" or path.startswith("/api/v1/") for path in schema["paths"]))
        for operation in operations:
            self.assertNotIn("422", operation["responses"])
            if operation["operationId"] not in {"get_backend_health", "create_demo_session"}:
                self.assertEqual(operation["security"], [{"DemoBearerSession": []}])
        inputs = schema["components"]["schemas"]["CreateApplicationInput"]
        self.assertFalse(inputs["additionalProperties"])
        self.assertEqual(inputs["properties"]["amount"]["type"], "string")
        self.assertEqual(inputs["properties"]["idempotencyKey"]["format"], "uuid")
        decision = schema["paths"]["/api/v1/applications/{application_id}/review"]["post"]
        self.assertFalse(decision["x-orchestrator-tool"])
        self.assertTrue(decision["x-human-action-required"])
        self.assertEqual(decision["x-allowed-roles"], ["reviewer"])

    def test_wire_aliases_decimal_strings_envelopes_and_safe_errors(self):
        customer = self.login()
        application = self.create_application(customer)
        self.assertEqual(application["amount"], "30000.00")
        self.assertIn("customerId", application)
        self.assertNotIn("customer_id", application)
        self.assertTrue(application["createdAt"].endswith("Z"))
        correlation = request_key()
        response = self.client.post("/api/v1/session", headers={"X-Correlation-ID": correlation}, json={
            "role": "customer", "email": "alex@example.test", "password": {"private": "do-not-echo"},
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["correlationId"], correlation)
        self.assertEqual(response.headers["x-correlation-id"], correlation)
        self.assertNotIn("do-not-echo", response.text)
        self.assertNotIn("private", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_authentication_logout_and_legacy_resource_alias(self):
        response = self.client.get("/api/v1/customers/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        customer = self.login()
        alias = self.client.get("/api/customers/me", headers=customer)
        self.assertEqual(alias.status_code, 200)
        self.assertEqual(alias.json()["data"]["id"], "customer-alex")
        self.call("POST", "/session/logout", customer, {})
        self.call("GET", "/customers/me", customer, expected=401)

    def test_unconfigured_orchestrator_is_not_fake_success(self):
        customer = self.login()
        response = self.call("POST", "/chat", customer, {"text": "Approve a loan"}, expected=501)
        self.assertEqual(response.json()["error"]["code"], "ORCHESTRATOR_NOT_CONFIGURED")
        self.assertEqual(self.call("GET", "/conversations/messages", customer), [])

    def test_cors_preflight_and_untrusted_origin(self):
        allowed = "http://127.0.0.1:3000"
        response = self.client.options("/api/v1/applications", headers={
            "Origin": allowed, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,x-correlation-id",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], allowed)
        self.assertIn("x-correlation-id", response.headers)
        self.assertEqual(self.client.get("/health", headers={"Origin": "https://untrusted.example"}).status_code, 403)
        denied = self.client.options("/api/v1/applications", headers={
            "Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST",
        })
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], "FORBIDDEN")
        unauthorized = self.client.get("/api/v1/applications", headers={"Origin": allowed})
        self.assertEqual(unauthorized.headers["access-control-allow-origin"], allowed)

    def test_body_limits_invalid_json_and_multipart_are_rejected(self):
        response = self.client.post("/api/v1/session", content="{" + " " * 40000, headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "PAYLOAD_TOO_LARGE")
        malformed = self.client.post("/api/v1/session", content="{broken", headers={"Content-Type": "application/json"})
        self.assertEqual(malformed.status_code, 400)
        binary = self.client.post("/api/v1/documents/validate", content=b"file bytes", headers={"Content-Type": "multipart/form-data"})
        self.assertEqual(binary.status_code, 400)

    def test_health_reports_actual_storage_availability(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["dependencies"]["orchestrator"], "not-configured")
        with patch.object(self.app.state.container.repository, "available", return_value=False):
            degraded = self.client.get("/health")
        self.assertEqual(degraded.status_code, 503)
        self.assertEqual(degraded.json()["status"], "degraded")

    def test_login_rate_limit_is_bounded_and_typed(self):
        settings = self.settings.model_copy(update={"logins_per_minute": 2})
        with TestClient(create_app(settings)) as client:
            input = {"role": "customer", "email": "alex@example.test", "password": "incorrect"}
            self.assertEqual(client.post("/api/v1/session", json=input).status_code, 401)
            self.assertEqual(client.post("/api/v1/session", json=input).status_code, 401)
            response = client.post("/api/v1/session", json=input)
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["retry-after"], "60")
            self.assertEqual(response.json()["error"]["code"], "RATE_LIMITED")

    def test_gateway_errors_remain_visible_to_allowed_origin(self):
        response = self.client.post("/api/v1/session", content=" " * 40000, headers={
            "Origin": "http://127.0.0.1:3000", "Content-Type": "application/json",
        })
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:3000")
        self.assertIn("x-correlation-id", response.headers)

    def test_chunked_body_limit_and_bearer_scheme_cannot_be_bypassed(self):
        response = self.client.post("/api/v1/session", content=iter([b" " * 20000, b" " * 20000]),
                                    headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)
        customer = self.login()
        token = customer["Authorization"].split()[1]
        for authorization in (token, f"Basic {token}", "Bearer invalid"):
            self.assertEqual(self.client.get("/api/v1/customers/me", headers={"Authorization": authorization}).status_code, 401)

    def test_unexpected_errors_are_safe_typed_and_keep_cors(self):
        app = create_app(self.settings)
        with TestClient(app, raise_server_exceptions=False) as client:
            login = client.post("/api/v1/session", json={"role": "customer", "email": "alex@example.test", "password": "ClientDemo123!"})
            token = "Bearer " + login.json()["data"]["token"]
            with patch.object(app.state.container.customers, "profile", side_effect=RuntimeError("secret runtime detail")):
                response = client.get("/api/v1/customers/me", headers={"Authorization": token, "Origin": "http://127.0.0.1:3000"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("secret runtime detail", response.text)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:3000")

    def test_disallowed_preflight_method_or_headers_have_typed_errors(self):
        for method, headers in (("DELETE", "authorization"), ("POST", "x-untrusted-header")):
            response = self.client.options("/api/v1/applications", headers={
                "Origin": "http://127.0.0.1:3000", "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": headers,
            })
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "FORBIDDEN")
            self.assertIn("x-correlation-id", response.headers)