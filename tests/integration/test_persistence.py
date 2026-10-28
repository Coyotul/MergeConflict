import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.gateway.app import create_app
from src.storage.application_db.repository import Repository, UnitOfWork
from tests.api_fixture import ApiFixture, request_key


class PersistenceTests(ApiFixture):
    def test_failed_notification_rolls_back_state_history_audit_and_idempotency(self):
        customer = self.login()
        application = self.ready_application(customer)
        before = self.call("GET", "/audit", customer)
        payload = {"confirmed": True, "idempotencyKey": request_key()}
        with patch.object(UnitOfWork, "save_notification", side_effect=sqlite3.OperationalError("private database detail")):
            response = self.call("POST", f"/applications/{application['id']}/submit", customer, payload, expected=503)
        self.assertNotIn("private database detail", response.text)
        unchanged = self.call("GET", f"/applications/{application['id']}", customer)
        self.assertEqual(unchanged["status"], "READY_FOR_SUBMISSION")
        self.assertEqual(unchanged["history"], application["history"])
        self.assertEqual(self.call("GET", "/audit", customer), before)
        result = self.call("POST", f"/applications/{application['id']}/submit", customer, payload)
        self.assertEqual(result["status"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(len(self.call("GET", "/notifications", customer)), 1)

    def test_concurrent_retries_create_one_application(self):
        customer = self.login()
        input = {"productId": "personal", "amount": "30000", "months": 36, "idempotencyKey": request_key()}
        def create(_):
            response = self.client.post("/api/v1/applications", headers=customer, json=input)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()["data"]
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(create, range(5)))
        self.assertTrue(all(item == results[0] for item in results))
        self.assertEqual(len(self.call("GET", "/applications", customer)), 1)

    def test_persisted_records_exclude_credentials_and_sessions(self):
        customer = self.login()
        self.create_application(customer)
        connection = sqlite3.connect(self.path)
        try:
            persisted = "\n".join(connection.iterdump())
        finally:
            connection.close()
        self.assertNotIn("ClientDemo123!", persisted)
        self.assertNotIn("AgentDemo123!", persisted)
        self.assertNotIn(customer["Authorization"].split()[1], persisted)

    def test_corrupt_database_fails_startup_and_is_not_reset(self):
        corrupt = self.path.parent / "corrupt.sqlite3"
        corrupt.write_bytes(b"not-a-sqlite-database")
        settings = self.settings.model_copy(update={"database_path": corrupt})
        with self.assertRaises(sqlite3.DatabaseError):
            with TestClient(create_app(settings)):
                self.fail("Corrupt database must not accept requests")
        self.assertEqual(corrupt.read_bytes(), b"not-a-sqlite-database")

    def test_typed_payload_corruption_fails_startup(self):
        with self.app.state.container.repository.transaction() as unit:
            unit.connection.execute("UPDATE customers SET payload = '{}' WHERE id = 'customer-blake'")
        with self.assertRaises(ValueError):
            Repository(self.path).initialize(self.app.state.container.catalogue.fixtures)

    def test_unversioned_database_is_not_overwritten(self):
        unknown = self.path.parent / "unversioned.sqlite3"
        connection = sqlite3.connect(unknown)
        try:
            connection.execute("CREATE TABLE existing_data(value TEXT)")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ValueError):
            Repository(unknown).initialize(self.app.state.container.catalogue.fixtures)