"""Live Uvicorn loopback verification with isolated synthetic data and cleanup."""

import json
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import uvicorn
from fastapi import FastAPI

from src.api.gateway.app import create_app
from src.core.settings import Settings


@contextmanager
def running_server(settings: Settings) -> Iterator[tuple[str, FastAPI]]:
    app = create_app(settings)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        try:
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not server.started:
                raise RuntimeError("The loopback backend smoke server did not start.")
            yield f"http://127.0.0.1:{port}", app
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("The loopback backend smoke server did not stop cleanly.")


def smoke() -> dict:
    checks = 0

    def verify(condition: bool, label: str) -> None:
        nonlocal checks
        if not condition:
            raise AssertionError(label)
        checks += 1

    def call(base: str, method: str, path: str, payload=None, token=None, expected=200):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{base}{path}", method=method, headers=headers,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        )
        try:
            with urlopen(request, timeout=5) as response:
                status, body = response.status, json.load(response)
        except HTTPError as response:
            try:
                status, body = response.code, json.load(response)
            finally:
                response.close()
        if status != expected:
            raise AssertionError(f"Unexpected HTTP status for {method} {path}: {status}, expected {expected}")
        return body["data"] if expected == 200 and "data" in body else body

    def key() -> str:
        return str(uuid4())

    with TemporaryDirectory(prefix="backend-live-http-") as directory:
        settings = Settings(database_path=Path(directory) / "backend.sqlite3")
        with running_server(settings) as (base, app):
            health = call(base, "GET", "/health")
            verify(health["status"] == "ok" and health["dependencies"]["eligibilityStorage"] == "available", "Storage health")
            denied = call(base, "GET", "/api/v1/customers/me", expected=401)
            verify(denied["error"]["code"] == "UNAUTHORIZED", "Authentication gate")
            customer = call(base, "POST", "/api/v1/session", {"role": "customer", "email": "alex@example.test", "password": "ClientDemo123!"})
            token = customer["token"]
            verify(call(base, "GET", "/api/v1/customers/me", token=token)["id"] == "customer-alex", "Owned profile")
            schema = call(base, "GET", "/openapi.json")
            tools = [operation["operationId"] for item in schema["paths"].values() for operation in item.values()
                     if isinstance(operation, dict) and operation.get("x-orchestrator-tool")]
            verify(len(tools) == 14, "Machine-readable scoped tools")
            scenario = {"productId": "personal", "amount": "30000.00", "months": 36}
            quote = call(base, "POST", "/api/v1/calculations/loan-offer", scenario, token)
            verify(quote["annualRate"] == "8.90" and quote["schedule"][-1]["balance"] == "0.00", "Deterministic pricing")
            creation = {**scenario, "idempotencyKey": key()}
            application = call(base, "POST", "/api/v1/applications", creation, token)
            application_id = application["id"]
            verify(application["status"] == "AWAITING_DOCUMENTS", "Draft is not submitted")
            verify(call(base, "POST", "/api/v1/applications", creation, token) == application, "Creation retry")
            assessment = call(base, "POST", "/api/v1/eligibility/check", {
                "applicationId": application_id, "pricingScenarioId": application["pricingScenarioId"], "idempotencyKey": key(),
            }, token)
            verify(assessment["human_review_required"] and not assessment["final_credit_decision"]
                   and assessment["status"] in {"ADDITIONAL_INFORMATION_REQUIRED", "MANUAL_REVIEW_REQUIRED"}, "Missing evidence is not fabricated")
            early = call(base, "POST", "/api/v1/loans/loan-personal/early-repayment/simulate", {"repayment": "5000"}, token)
            verify(early["earlyFee"] == "50.00" and early["monthsSaved"] > 0, "Partial repayment simulation")
            refinance = call(base, "POST", "/api/v1/refinancing/compare", {"loanIds": ["loan-personal", "loan-car"], "months": 60}, token)
            verify(refinance["principal"] == "37550.00" and refinance["totalSavings"].startswith("-"), "Refinance total-cost trade-off")
            reviewer = call(base, "POST", "/api/v1/session", {"role": "reviewer", "email": "jamie@example.test", "password": "AgentDemo123!"})["token"]
            blake = call(base, "POST", "/api/v1/session", {"role": "customer", "email": "blake@example.test", "password": "ClientDemo123!"})["token"]
            call(base, "GET", f"/api/v1/applications/{application_id}", token=blake, expected=404)
            verify(True, "Customer isolation")
            review = {"action": "approve", "reason": "Independent synthetic evidence inspection by the human reviewer.", "evidenceReviewed": True, "idempotencyKey": key()}
            call(base, "POST", f"/api/v1/applications/{application_id}/review", review, token, expected=403)
            verify(True, "Customers cannot approve")

            def upload(kind):
                return call(base, "POST", f"/api/v1/applications/{application_id}/documents", {
                    "kind": kind, "name": f"synthetic-{kind}.pdf", "mimeType": "application/pdf", "size": 1000,
                    "syntheticConfirmed": True, "idempotencyKey": key(),
                }, token)

            upload("identity")
            ready = upload("income")
            verify(ready["status"] == "READY_FOR_SUBMISSION", "Metadata checklist")
            submission = {"confirmed": True, "idempotencyKey": key()}
            submitted = call(base, "POST", f"/api/v1/applications/{application_id}/submit", submission, token)
            verify(submitted["status"] == "PENDING_HUMAN_REVIEW", "Explicit submission")
            verify(call(base, "POST", f"/api/v1/applications/{application_id}/submit", submission, token) == submitted, "Submission retry")
            requested = call(base, "POST", f"/api/v1/applications/{application_id}/review", {
                "action": "request-information", "reason": "Please provide the synthetic statement metadata.",
                "requestedDocument": "statement", "evidenceReviewed": True, "idempotencyKey": key(),
            }, reviewer)
            verify(requested["status"] == "MORE_INFORMATION_REQUIRED", "Human information request")
            verify(upload("statement")["status"] == "READY_FOR_SUBMISSION", "Resume after requested metadata")
            call(base, "POST", f"/api/v1/applications/{application_id}/submit", {"confirmed": True, "idempotencyKey": key()}, token)
            approved = call(base, "POST", f"/api/v1/applications/{application_id}/review", review, reviewer)
            verify(approved["status"] == "APPROVED", "Assigned human outcome")
            state = call(base, "GET", f"/api/v1/applications/{application_id}/status", token=token)
            verify(not state["signed"] and not state["funded"] and len(state["history"]) == 8, "No signing or funding and full history")
            chat = call(base, "POST", "/api/v1/chat", {"text": "hello"}, token, expected=501)
            verify(chat["error"]["code"] == "ORCHESTRATOR_NOT_CONFIGURED", "No fake AI response")
            call(base, "POST", "/api/v1/session/logout", {}, token)
            call(base, "GET", "/api/v1/customers/me", token=token, expected=401)
            verify(True, "Revoked logout")
        with running_server(settings) as (base, app):
            renewed = call(base, "POST", "/api/v1/session", {"role": "customer", "email": "alex@example.test", "password": "ClientDemo123!"})["token"]
            saved = call(base, "GET", f"/api/v1/applications/{application_id}/status", token=renewed)
            verify(saved["status"] == "APPROVED" and len(saved["history"]) == 8, "Durable state after real server restart")
    return {"status": "ok", "transport": "live-loopback-http", "checks": checks,
            "simulated": True, "workflowOutcome": "APPROVED", "signed": False, "funded": False}


if __name__ == "__main__":
    print(json.dumps(smoke(), indent=2))