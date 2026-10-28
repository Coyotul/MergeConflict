import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.agent.tools.eligibility import run_eligibility_check
from src.api.gateway.eligibility_demo import create_app
from src.core.eligibility_demo import build_demo_service, load_reference_fixture
from src.core.eligibility_errors import StorageUnavailable
from tests.fixtures.eligibility import CUSTOMER, request


async def asgi_request(app, method, path, body=None, token=None):
    """Small stdlib ASGI transport; no httpx/TestClient dependency is necessary."""
    data = json.dumps(body).encode() if body is not None else b""
    headers = [(b"host", b"testserver"), (b"content-type", b"application/json")]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    headers.append((b"content-length", str(len(data)).encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": headers, "client": ("127.0.0.1", 12345),
             "server": ("testserver", 80), "root_path": ""}
    messages = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": data, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    try:
        await app(scope, receive, send)
    except Exception:
        # ServerErrorMiddleware sends the registered safe response before re-raising.
        if not any(m["type"] == "http.response.start" for m in messages):
            raise
    start = next(m for m in messages if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], json.loads(payload)


class EligibilityApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="eligibility-api-")
        self.addCleanup(self.directory.cleanup)
        self.service = build_demo_service(Path(self.directory.name) / "api.sqlite3",
                                          lambda: load_reference_fixture().reference_time)
        self.app = create_app(self.service)

    async def call(self, body=None, token="demo-customer-key", method="POST", path="/api/eligibility/assessments"):
        return await asgi_request(self.app, method, path, body or request().model_dump(mode="json"), token)

    async def test_http_assessment_and_authenticated_fetch(self):
        status, body = await self.call()
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["status"], "PRELIMINARY_REQUIREMENTS_SATISFIED")
        self.assertFalse(body["data"]["final_credit_decision"])
        self.assertTrue(body["data"]["human_review_required"])
        assessment_id = body["data"]["assessment_id"]
        status, fetched = await self.call(method="GET", path=f"/api/eligibility/assessments/{assessment_id}")
        self.assertEqual(status, 200)
        self.assertEqual(body, fetched)

    async def test_missing_and_invalid_demo_credentials_return_401(self):
        for token in (None, "wrong-key", "demo-customer-key" * 30):
            status, body = await self.call(token=token)
            self.assertEqual(status, 401)
            self.assertEqual(body["error"]["code"], "UNAUTHORIZED")
            self.assertNotIn("wrong-key", json.dumps(body))

    async def test_customer_cannot_access_another_demo_case(self):
        body = {"application_id": "demo-app-high-dti", "pricing_scenario_id": "demo-quote-high-dti", "idempotency_key": "cross-key-0001"}
        status, result = await self.call(body)
        self.assertEqual(status, 403)
        self.assertEqual(result["error"]["code"], "ACCESS_DENIED")

    async def test_reviewer_can_run_assigned_demo_case(self):
        body = {"application_id": "demo-app-high-dti", "pricing_scenario_id": "demo-quote-high-dti", "idempotency_key": "review-key-0001"}
        status, result = await self.call(body, token="demo-reviewer-key")
        self.assertEqual(status, 200)
        self.assertEqual(result["data"]["status"], "PRELIMINARY_REQUIREMENTS_NOT_SATISFIED")

    async def test_http_rejects_evidence_injection_without_echoing_values(self):
        body = request().model_dump(mode="json")
        body["consent"] = "private injected instruction"
        status, result = await self.call(body)
        self.assertEqual(status, 422)
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")
        self.assertNotIn("private injected instruction", json.dumps(result))

    async def test_http_idempotency_replay_and_conflict(self):
        status, first = await self.call()
        status, replay = await self.call()
        self.assertEqual(first, replay)
        status, conflict = await self.call(request(scenario=False).model_dump(mode="json"))
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error"]["code"], "IDEMPOTENCY_CONFLICT")

    async def test_read_cross_customer_assessment_denied(self):
        body = {"application_id": "demo-app-high-dti", "pricing_scenario_id": "demo-quote-high-dti", "idempotency_key": "review-key-0001"}
        status, result = await self.call(body, token="demo-reviewer-key")
        assessment_id = result["data"]["assessment_id"]
        status, denied = await self.call(method="GET", path=f"/api/eligibility/assessments/{assessment_id}")
        self.assertEqual(status, 403)
        self.assertEqual(denied["error"]["code"], "ACCESS_DENIED")

    async def test_missing_assessment_and_bad_identifier(self):
        status, result = await self.call(method="GET", path="/api/eligibility/assessments/nonexistent")
        self.assertEqual(status, 404)
        status, result = await self.call(method="GET", path="/api/eligibility/assessments/" + "x" * 129)
        self.assertEqual(status, 422)

    async def test_storage_failure_returns_safe_503(self):
        with patch.object(self.service.assessments, "save_run", side_effect=StorageUnavailable()):
            status, result = await self.call()
        self.assertEqual(status, 503)
        self.assertEqual(result["error"]["code"], "STORAGE_UNAVAILABLE")
        self.assertNotIn("data", result)

    async def test_unexpected_failure_returns_safe_500(self):
        with patch.object(self.service, "assess", side_effect=RuntimeError("secret internal detail")):
            status, result = await self.call()
        self.assertEqual(status, 500)
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")

    async def test_health_checks_storage_availability(self):
        status, result = await asgi_request(self.app, "GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(result["mode"], "synthetic-demo")
        with patch.object(self.service.assessments, "healthcheck", return_value=False):
            status, result = await asgi_request(self.app, "GET", "/health")
        self.assertEqual(status, 503)
        self.assertFalse(result["storageAvailable"])

    async def test_tool_and_api_use_the_same_authorized_service(self):
        args = request().model_dump(mode="json")
        result = await run_eligibility_check(args, service=self.service, actor=CUSTOMER)
        self.assertEqual(result["data"]["status"], "PRELIMINARY_REQUIREMENTS_SATISFIED")
        invalid = await run_eligibility_check({**args, "role": "admin"}, service=self.service, actor=CUSTOMER)
        self.assertEqual(invalid["error"]["code"], "VALIDATION_ERROR")

    def test_openapi_exposes_only_narrow_routes_and_bearer_auth(self):
        schema = self.app.openapi()
        self.assertEqual(set(schema["paths"]), {"/health", "/api/eligibility/assessments", "/api/eligibility/assessments/{assessment_id}"})
        operation = schema["paths"]["/api/eligibility/assessments"]["post"]
        self.assertTrue(operation["security"])
        fields = schema["components"]["schemas"]["EligibilityCheckRequest"]["properties"]
        self.assertEqual(set(fields), {"application_id", "pricing_scenario_id", "idempotency_key"})