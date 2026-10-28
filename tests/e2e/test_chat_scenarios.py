"""End-to-end chat scenarios: real API, DemoChatModel (mock mode), file session store."""
import io
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.settings import OrchestratorSettings

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config" / "orchestrator"


@pytest.fixture
def work_dir():
    """A fresh gitignored directory (pytest tmp_path is not usable on this machine)."""
    path = Path(__file__).parent / ".test_tmp" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def make_settings(work_dir: Path) -> OrchestratorSettings:
    return OrchestratorSettings(
        model="fake",
        session_store="file",
        sessions_dir=work_dir / "sessions",
        uploads_dir=work_dir / "uploads",
        config_dir=CONFIG_DIR,
    )


@pytest.fixture
def client(work_dir):
    return TestClient(create_app(make_settings(work_dir)))


class Chat:
    """Small driver over the chat API for one customer."""

    def __init__(self, client: TestClient, customer_id: str):
        self.client = client
        self.headers = {"X-Customer-Id": customer_id}
        self.responses: list[dict] = []
        r = client.post("/chat/sessions", json={}, headers=self.headers)
        assert r.status_code == 201, r.text
        self.session_id = r.json()["session_id"]
        self.responses.append(r.json())

    def _ok(self, r) -> dict:
        assert r.status_code == 200, r.text
        body = r.json()
        self.responses.append(body)
        return body

    def say(self, text: str) -> dict:
        return self._ok(self.client.post(
            f"/chat/sessions/{self.session_id}/messages", json={"text": text}, headers=self.headers
        ))

    def upload(self, doc_type: str, filename: str | None = None) -> dict:
        files = {"file": (filename or f"{doc_type}.pdf", io.BytesIO(b"%PDF-1.4 synthetic"), "application/pdf")}
        return self._ok(self.client.post(
            f"/chat/sessions/{self.session_id}/documents",
            data={"doc_type": doc_type}, files=files, headers=self.headers,
        ))

    def select_offer(self, offer_id: str) -> dict:
        return self._ok(self.client.post(
            f"/chat/sessions/{self.session_id}/offer-selection", json={"offer_id": offer_id}, headers=self.headers
        ))

    def confirm(self, summary_version: str, decision: str = "confirm") -> dict:
        return self._ok(self.client.post(
            f"/chat/sessions/{self.session_id}/confirmation",
            json={"summary_version": summary_version, "decision": decision}, headers=self.headers,
        ))

    def view(self) -> dict:
        r = self.client.get(f"/chat/sessions/{self.session_id}", headers=self.headers)
        assert r.status_code == 200, r.text
        return r.json()


def stage(body: dict) -> str | None:
    return body["progress"]["stage"]


def block(body: dict, block_type: str) -> dict:
    found = [b for b in body["blocks"] if b["type"] == block_type]
    assert found, f"no {block_type} block in {[b['type'] for b in body['blocks']]}"
    return found[0]


def answer_discovery(chat: Chat) -> None:
    assert stage(chat.say("Vreau un credit")) == "discovery"
    assert stage(chat.say("pentru renovare")) == "discovery"
    assert stage(chat.say("30000 lei")) == "discovery"
    assert stage(chat.say("60 luni")) == "collecting_information"


def test_happy_path_cust_001(client):
    chat = Chat(client, "cust-001")
    assert chat.responses[0]["messages"], "greeting expected"

    answer_discovery(chat)
    assert stage(chat.say("employed")) == "collecting_information"
    assert stage(chat.say("48")) == "collecting_information"
    assert stage(chat.say("7000")) == "collecting_information"
    assert stage(chat.say("TechCorp SRL")) == "collecting_information"
    body = chat.say("400")
    assert stage(body) == "eligibility"

    body = chat.upload("id_card")
    assert stage(body) == "documents"
    assert block(body, "eligibility_result")["result"]["status"] == "satisfied"
    assert body["awaiting"]["kind"] == "document"
    chat.upload("payslip")
    body = chat.upload("bank_statement")
    assert stage(body) == "documents"
    income = next(f for f in block(body, "extracted_fields")["fields"] if f["field"] == "monthly_net_income")
    assert income["conflict_with"] == "7000.00"

    body = chat.say("da")
    assert stage(body) == "offer_selection"
    assert body["awaiting"]["kind"] == "offer_choice"
    offers = block(body, "offers")["offers"]
    assert len(offers) >= 2
    reply = body["messages"][-1]["text"]
    assert offers[0]["monthly_installment"]["amount"] in reply  # summarised from CONTEXT_JSON

    body = chat.select_offer(offers[0]["offer_id"])
    assert stage(body) == "awaiting_confirmation"
    assert body["awaiting"]["kind"] == "confirmation"
    version = body["awaiting"]["summary_version"]
    assert block(body, "application_summary")["summary"]["summary_version"] == version

    body = chat.confirm(version)
    assert stage(body) == "submitted"
    assert body["awaiting"]["kind"] == "none"
    submitted = block(body, "application_submitted")
    assert submitted["status"] == "PENDING_HUMAN_REVIEW"
    assert submitted["application_id"] in body["messages"][-1]["text"]
    assert body["simulated"] is True

    texts = [m["text"].lower() for r in chat.responses for m in r["messages"]]
    assert all("aprobat" not in t and "approved" not in t for t in texts)


def test_not_eligible_cust_002(client):
    chat = Chat(client, "cust-002")
    answer_discovery(chat)
    for text in ("employed", "24", "2100", "AutoService SA", "400"):
        chat.say(text)
    body = chat.say("ok")
    assert stage(body) == "not_eligible"
    assert body["awaiting"]["kind"] == "text"
    assert block(body, "eligibility_result")["result"]["status"] == "not_satisfied"
    assert "2100" in body["messages"][-1]["text"]  # reason text comes from the tool result


def test_manual_review_cust_003(client):
    chat = Chat(client, "cust-003")
    answer_discovery(chat)
    for text in ("self_employed", "36", "8000", "Dumitru Consulting PFA", "1000"):
        chat.say(text)
    body = chat.say("ok")
    assert stage(body) == "manual_review"
    assert block(body, "eligibility_result")["result"]["status"] == "manual_review"


def test_product_question_has_citations(client):
    chat = Chat(client, "cust-001")
    body = chat.say("Ce documente îmi trebuie?")
    assert body["progress"]["flow"] == "product_info"
    citations = body["messages"][-1]["citations"]
    assert citations
    assert all(c["publisher"] == "Synthetic stub" for c in citations)
    assert body["simulated"] is True


def test_resume_after_restart(work_dir):
    first = TestClient(create_app(make_settings(work_dir)))
    chat = Chat(first, "cust-001")
    answer_discovery(chat)
    before = chat.view()

    restarted = TestClient(create_app(make_settings(work_dir)))
    chat.client = restarted
    after = chat.view()
    assert stage(after["latest"]) == stage(before["latest"]) == "collecting_information"
    assert after["messages"] == before["messages"]
    assert len(after["messages"]) == 9  # greeting + 4 customer/assistant pairs
    assert stage(chat.say("employed")) == "collecting_information"


def test_side_question_mid_application(client):
    chat = Chat(client, "cust-001")
    answer_discovery(chat)
    body = chat.say("Ce documente îmi trebuie?")
    assert stage(body) == "collecting_information"
    assert body["progress"]["flow"] == "credit_application"
    assert body["messages"][-1]["citations"]
    assert "Employment Type" in body["messages"][-1]["text"]  # back to the application

    body = chat.say("employed")
    fields = chat.view()["latest"]
    assert stage(body) == "collecting_information"
    assert stage(fields) == "collecting_information"
    assert "Employment Duration (months)" in body["messages"][-1]["text"]


def test_rejected_upload_asks_again(client):
    chat = Chat(client, "cust-001")
    answer_discovery(chat)
    body = chat.upload("id_card", filename="reject_id.pdf")
    checklist = {i["doc_type"]: i for i in block(body, "document_checklist")["items"]}
    assert checklist["id_card"]["status"] == "rejected"
    assert checklist["id_card"]["rejection_reason"] in body["messages"][-1]["text"]
