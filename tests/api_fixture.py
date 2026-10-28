import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.gateway.app import create_app
from src.core.settings import Settings


def request_key() -> str:
    return str(uuid4())


class ApiFixture(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="luma-backend-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "backend.sqlite3"
        self.settings = Settings(database_path=self.path, requests_per_minute=10000, logins_per_minute=1000)
        self.app = create_app(self.settings)
        self.client = self.enterContext(TestClient(self.app))

    def login(self, email="alex@example.test", role="customer") -> dict[str, str]:
        password = "ClientDemo123!" if role == "customer" else "AgentDemo123!"
        response = self.client.post("/api/v1/session", json={"role": role, "email": email, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['data']['token']}"}

    def call(self, method: str, path: str, headers=None, payload=None, expected=200):
        response = self.client.request(method, f"/api/v1{path}", headers=headers, **({"json": payload} if payload is not None else {}))
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()["data"] if expected == 200 else response

    def create_application(self, headers, **changes):
        return self.call("POST", "/applications", headers, {
            "productId": "personal", "amount": "30000.00", "months": 36, "idempotencyKey": request_key(), **changes,
        })

    def upload(self, headers, application_id, kind):
        return self.call("POST", f"/applications/{application_id}/documents", headers, {
            "kind": kind, "name": f"synthetic-{kind}.pdf", "mimeType": "application/pdf", "size": 1000,
            "syntheticConfirmed": True, "idempotencyKey": request_key(),
        })

    def ready_application(self, headers):
        application = self.create_application(headers)
        self.upload(headers, application["id"], "identity")
        return self.upload(headers, application["id"], "income")

    def submit(self, headers, application_id, key=None):
        return self.call("POST", f"/applications/{application_id}/submit", headers, {
            "confirmed": True, "idempotencyKey": key or request_key(),
        })