from fastapi.testclient import TestClient

from src.api.gateway.app import create_app
from tests.api_fixture import ApiFixture, request_key


class WorkflowApiTests(ApiFixture):
    def test_complete_request_information_resubmit_human_decision_journey(self):
        customer = self.login()
        reviewer = self.login("jamie@example.test", "reviewer")
        application = self.ready_application(customer)
        application_id = application["id"]
        self.assertEqual(application["status"], "READY_FOR_SUBMISSION")
        submitted = self.submit(customer, application_id)
        self.assertEqual(submitted["status"], "PENDING_HUMAN_REVIEW")
        queue = self.call("GET", "/reviews/queue", reviewer)
        self.assertEqual([app["id"] for app in queue], [application_id])
        self.call("POST", f"/applications/{application_id}/notes", reviewer, {
            "text": "Private staff-only assessment.", "idempotencyKey": request_key(),
        })
        review = {"action": "request-information", "reason": "Please provide synthetic statement metadata for independent review.",
                  "evidenceReviewed": True, "requestedDocument": "statement", "idempotencyKey": request_key()}
        requested = self.call("POST", f"/applications/{application_id}/review", reviewer, review)
        self.assertEqual(requested["status"], "MORE_INFORMATION_REQUIRED")
        self.assertEqual(requested["requestedDocument"], "statement")
        self.assertEqual(self.call("POST", f"/applications/{application_id}/review", reviewer, review), requested)
        customer_view = self.call("GET", f"/applications/{application_id}", customer)
        self.assertTrue(all(not note["internal"] for note in customer_view["notes"]))
        self.assertNotIn("Private staff-only assessment", str(customer_view))
        audit = self.call("GET", "/audit", customer)
        self.assertNotIn("INTERNAL_NOTE_ADDED", [event["action"] for event in audit])
        self.call("POST", f"/applications/{application_id}/submit", customer,
                  {"confirmed": True, "idempotencyKey": request_key()}, expected=409)
        with TestClient(create_app(self.settings)) as restarted:
            self.assertEqual(restarted.get(f"/api/v1/applications/{application_id}", headers=customer).status_code, 401)
            login = restarted.post("/api/v1/session", json={"role": "customer", "email": "alex@example.test", "password": "ClientDemo123!"})
            renewed = {"Authorization": "Bearer " + login.json()["data"]["token"]}
            self.assertEqual(restarted.get(f"/api/v1/applications/{application_id}", headers=renewed).json()["data"]["status"], "MORE_INFORMATION_REQUIRED")
        ready = self.upload(customer, application_id, "statement")
        self.assertEqual(ready["status"], "READY_FOR_SUBMISSION")
        self.submit(customer, application_id)
        decision = {"action": "approve", "reason": "I independently inspected the synthetic evidence and accept this demo scenario.",
                    "evidenceReviewed": True, "idempotencyKey": request_key()}
        approved = self.call("POST", f"/applications/{application_id}/review", reviewer, decision)
        self.assertEqual(approved["status"], "APPROVED")
        self.assertEqual(self.call("POST", f"/applications/{application_id}/review", reviewer, decision), approved)
        state = self.call("GET", f"/applications/{application_id}/status", customer)
        self.assertFalse(state["signed"])
        self.assertFalse(state["funded"])
        self.assertEqual([entry["status"] for entry in state["history"]], [
            "DRAFT", "AWAITING_DOCUMENTS", "READY_FOR_SUBMISSION", "PENDING_HUMAN_REVIEW",
            "MORE_INFORMATION_REQUIRED", "READY_FOR_SUBMISSION", "PENDING_HUMAN_REVIEW", "APPROVED",
        ])
        self.assertTrue(all(entry["correlationId"] for entry in state["history"]))
        notifications = self.call("GET", "/notifications", customer)
        self.assertEqual(len(notifications), 4)
        self.assertTrue(all(item["mandatory"] for item in notifications))

    def test_customer_and_assignment_isolation(self):
        alex = self.login()
        blake = self.login("blake@example.test")
        jamie = self.login("jamie@example.test", "reviewer")
        taylor = self.login("taylor@example.test", "reviewer")
        application = self.create_application(alex)
        for actor in (blake, taylor):
            for suffix in ("", "/status", "/documents"):
                self.call("GET", f"/applications/{application['id']}{suffix}", actor, expected=404)
        self.assertEqual(self.call("GET", "/applications", blake), [])
        self.assertEqual(self.call("GET", "/applications", taylor), [])
        self.assertEqual(len(self.call("GET", "/applications", jamie)), 1)
        self.call("GET", "/customers/me", jamie, expected=403)
        self.call("GET", "/loans/loan-personal", blake, expected=404)
        self.call("POST", "/refinancing/compare", blake, {"loanIds": ["loan-personal"], "months": 36}, expected=404)
        self.call("POST", f"/applications/{application['id']}/review", alex, {
            "action": "approve", "reason": "A customer cannot approve an application.", "evidenceReviewed": True, "idempotencyKey": request_key(),
        }, expected=403)

    def test_confirmation_evidence_and_terminal_state_gates(self):
        customer = self.login()
        reviewer = self.login("jamie@example.test", "reviewer")
        application = self.create_application(customer)
        application_id = application["id"]
        for confirmed, expected in ((False, 400), (1, 400), (True, 409)):
            self.call("POST", f"/applications/{application_id}/submit", customer,
                      {"confirmed": confirmed, "idempotencyKey": request_key()}, expected=expected)
        self.call("POST", f"/applications/{application_id}/review", reviewer, {
            "action": "approve", "reason": "A draft cannot receive a final decision.", "evidenceReviewed": True, "idempotencyKey": request_key(),
        }, expected=409)
        self.upload(customer, application_id, "identity")
        self.upload(customer, application_id, "income")
        self.submit(customer, application_id)
        self.call("POST", f"/applications/{application_id}/review", reviewer, {
            "action": "reject", "reason": "Synthetic scenario rejected after independent evidence inspection.",
            "evidenceReviewed": True, "idempotencyKey": request_key(),
        })
        self.call("POST", f"/applications/{application_id}/submit", customer,
                  {"confirmed": True, "idempotencyKey": request_key()}, expected=409)
        self.call("POST", f"/applications/{application_id}/cancel", customer,
                  {"reason": "Cannot cancel a final human outcome.", "idempotencyKey": request_key()}, expected=409)

    def test_idempotent_response_is_original_snapshot_not_latest_application(self):
        customer = self.login()
        key = request_key()
        input = {"productId": "personal", "amount": "30000", "months": 36, "idempotencyKey": key}
        original = self.call("POST", "/applications", customer, input)
        self.upload(customer, original["id"], "identity")
        self.upload(customer, original["id"], "income")
        current = self.call("GET", f"/applications/{original['id']}", customer)
        self.assertEqual(current["status"], "READY_FOR_SUBMISSION")
        self.assertEqual(self.call("POST", "/applications", customer, input), original)
        self.call("POST", "/applications", customer, {**input, "amount": "40000"}, expected=409)
        self.call("POST", f"/applications/{original['id']}/submit", customer,
                  {"confirmed": True, "idempotencyKey": key}, expected=409)
        self.assertEqual(len(self.call("GET", "/applications", customer)), 1)

    def test_conversation_reset_and_support_never_change_workflow(self):
        customer = self.login()
        application = self.create_application(customer)
        self.call("POST", "/conversations/messages", customer, {"text": "I need help with my documents.", "idempotencyKey": request_key()})
        request = self.call("POST", "/support", customer, {
            "message": "Please request human assistance.", "applicationId": application["id"], "idempotencyKey": request_key(),
        })
        self.assertTrue(request["simulated"])
        self.assertEqual(len(request["messageIds"]), 1)
        self.call("POST", "/conversations/reset", customer, {})
        self.assertEqual(self.call("GET", "/conversations/messages", customer), [])
        self.assertEqual(self.call("GET", f"/applications/{application['id']}", customer)["status"], "AWAITING_DOCUMENTS")