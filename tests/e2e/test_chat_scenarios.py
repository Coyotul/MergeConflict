"""End-to-end chat scenarios: real API, DemoChatModel (mock mode), file session store."""
import io
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from scripts.credit_sources.setup import create_database
from src.api.app import create_app
from src.core.settings import OrchestratorSettings
from tests.fixtures.documents import cnp_for, document_bytes, pdf_bytes

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config" / "orchestrator"


@pytest.fixture(scope="session")
def credit_db():
    """The credit-source SQLite DB built once per session from the committed sample SQL."""
    path = Path(__file__).parent / ".test_tmp" / f"credit-{uuid4().hex}"
    path.mkdir(parents=True)
    yield create_database(path / "credit_sources.db")
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def work_dir():
    """A fresh gitignored directory (pytest tmp_path is not usable on this machine)."""
    path = Path(__file__).parent / ".test_tmp" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def make_settings(work_dir: Path, credit_db: Path) -> OrchestratorSettings:
    return OrchestratorSettings(
        model="fake",
        session_store="file",
        sessions_dir=work_dir / "sessions",
        uploads_dir=work_dir / "uploads",
        config_dir=CONFIG_DIR,
        credit_sources_db=credit_db,
        customer_bindings_path=CONFIG_DIR / "customer_bindings.yaml",
    )


def make_app(work_dir, credit_db):
    from datetime import datetime, UTC
    app = create_app(make_settings(work_dir, credit_db))
    app.state.orchestrator._clock = lambda: datetime(2026, 10, 28, 12, tzinfo=UTC)
    return app


@pytest.fixture
def client(work_dir, credit_db):
    return TestClient(make_app(work_dir, credit_db))


# Document identity per demo customer: the name must match the profile and the CNP must be
# checksum-valid (the dataset's CNPs deliberately are not), with a birth date matching the age.
DOCUMENT_PEOPLE = {
    "cust-alex-morgan": {"first_name": "ALEX", "last_name": "MORGAN", "cnp": cnp_for("188041241001")},
    "cust-andrei-stan": {"first_name": "ANDREI", "last_name": "STAN", "cnp": cnp_for("196062541001")},
    "cust-mihai-ilie": {"first_name": "MIHAI", "last_name": "ILIE", "cnp": cnp_for("186051841001")},
}


class Chat:
    """Small driver over the chat API for one customer."""

    def __init__(self, client: TestClient, customer_id: str):
        self.client = client
        self.headers = {"X-Customer-Id": customer_id}
        self.person = DOCUMENT_PEOPLE.get(customer_id, {})
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

    def upload(self, doc_type: str, filename: str | None = None, *, content: bytes | None = None) -> dict:
        files = {"file": (filename or f"{doc_type}.pdf", io.BytesIO(document_bytes(doc_type, **self.person) if content is None else content), "application/pdf")}
        return self._ok(self.client.post(
            f"/chat/sessions/{self.session_id}/documents",
            data={"doc_type": doc_type}, files=files, headers=self.headers,
        ))

    def select_offer(self, offer_id: str) -> dict:
        return self._ok(self.client.post(
            f"/chat/sessions/{self.session_id}/offer-selection", json={"offer_id": offer_id}, headers=self.headers
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


def test_happy_path_alex_morgan(client):
    chat = Chat(client, "cust-alex-morgan")
    assert chat.responses[0]["messages"], "greeting expected"

    answer_discovery(chat)
    assert stage(chat.say("employed")) == "collecting_information"
    assert stage(chat.say("67")) == "collecting_information"
    assert stage(chat.say("7000")) == "collecting_information"
    assert stage(chat.say("FICTIV Employer's Studio 1")) == "collecting_information"
    body = chat.say("0")  # the last required field: eligibility runs in this turn
    assert stage(body) == "documents"
    assert block(body, "eligibility_result")["result"]["status"] == "satisfied"

    body = chat.upload("id_card")
    assert stage(body) == "documents"
    result = block(body, "eligibility_result")["result"]
    assert result["status"] == "satisfied"
    assert "income_gap" in {r["code"] for r in result["reasons"]}  # ANAF 8500 vs declared 7000
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

    # Submission is by explicit agreement in chat: the agent asks, the customer agrees in words.
    body = chat.select_offer(offers[0]["offer_id"])
    assert stage(body) == "awaiting_confirmation"
    assert body["awaiting"]["kind"] == "text"

    body = chat.say("Da, trimite cererea")
    assert stage(body) == "submitted"
    assert body["awaiting"]["kind"] == "none"
    submitted = block(body, "application_submitted")
    assert submitted["status"] == "PENDING_HUMAN_REVIEW"
    assert submitted["application_id"] in body["messages"][-1]["text"]
    assert body["simulated"] is True

    texts = [m["text"].lower() for r in chat.responses for m in r["messages"]]
    assert all("aprobat" not in t and "approved" not in t for t in texts)


def test_not_eligible_andrei_stan(client):
    chat = Chat(client, "cust-andrei-stan")
    answer_discovery(chat)
    for text in ("employed", "67", "2300", "FICTIV Employer's Studio 1"):
        chat.say(text)
    body = chat.say("0")  # the last required field: eligibility runs and is explained in this turn
    assert stage(body) == "not_eligible"
    assert body["awaiting"]["kind"] == "text"
    assert block(body, "eligibility_result")["result"]["status"] == "not_satisfied"
    assert "2300" in body["messages"][-1]["text"]  # reason text comes from the tool result (ANAF income)


def test_manual_review_mihai_ilie(client):
    chat = Chat(client, "cust-mihai-ilie")
    answer_discovery(chat)
    for text in ("self_employed", "57", "7000", "Ilie Mihai PFA", "0"):
        chat.say(text)
    body = chat.say("ok")
    assert stage(body) == "manual_review"
    assert block(body, "eligibility_result")["result"]["status"] == "manual_review"


def test_product_question_has_citations(client):
    chat = Chat(client, "cust-alex-morgan")
    body = chat.say("Ce documente îmi trebuie?")
    assert body["progress"]["flow"] == "product_info"
    citations = body["messages"][-1]["citations"]
    assert citations
    assert all(c["publisher"] == "Synthetic stub" for c in citations)
    assert body["simulated"] is True


def test_resume_after_restart(work_dir, credit_db):
    first = TestClient(make_app(work_dir, credit_db))
    chat = Chat(first, "cust-alex-morgan")
    answer_discovery(chat)
    before = chat.view()

    restarted = TestClient(make_app(work_dir, credit_db))
    chat.client = restarted
    after = chat.view()
    assert stage(after["latest"]) == stage(before["latest"]) == "collecting_information"
    assert after["messages"] == before["messages"]
    assert len(after["messages"]) == 9  # greeting + 4 customer/assistant pairs
    assert stage(chat.say("employed")) == "collecting_information"


def test_side_question_mid_application(client):
    chat = Chat(client, "cust-alex-morgan")
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
    chat = Chat(client, "cust-alex-morgan")
    answer_discovery(chat)
    body = chat.upload("id_card", filename="unreadable.pdf", content=pdf_bytes("Unreadable identity document"))
    checklist = {i["doc_type"]: i for i in block(body, "document_checklist")["items"]}
    assert checklist["id_card"]["status"] == "rejected"
    assert checklist["id_card"]["rejection_reason"] in body["messages"][-1]["text"]
