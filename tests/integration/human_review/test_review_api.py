"""Customer and reviewer review API over the real app."""
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.settings import OrchestratorSettings
from src.models.knowledge import Product
from tests.fixtures import documents as _docs
from tests.fixtures.documents import image_bytes, pdf_bytes  # noqa: F401

# Documents for the demo customer cust-alex-morgan: the name matches the profile, the CNP is
# checksum-valid with Alex's birth date (1988-04-12, so 38 at the 2026-10-28 reference date).
CNP = _docs.cnp_for("188041241001")


def identity_text(**kw):
    return _docs.identity_text(**{"first_name": "ALEX", "last_name": "MORGAN", "cnp": CNP, **kw})


def income_text(**kw):
    return _docs.income_text(**{"name": "ALEX MORGAN", "cnp": CNP, **kw})


def statement_text(**kw):
    return _docs.statement_text(**{"holder": "ALEX MORGAN", **kw})
from tests.unit.orchestrator.factories import make_verified_app

CONFIG = Path(__file__).resolve().parents[3] / "config" / "orchestrator"
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
ALEX = {"X-Customer-Id": "cust-alex-morgan"}
OTHER = {"X-Customer-Id": "cust-andrei-stan"}
REVIEWER = {"X-Reviewer-Id": "reviewer-demo"}


@pytest.fixture
def client(tmp_path):
    settings = OrchestratorSettings(model="fake", session_store="memory", uploads_dir=tmp_path / "uploads",
                                    config_dir=CONFIG, review_db_path=tmp_path / "applications.sqlite3")
    app = create_app(settings)
    stub_data = app.state.review_service.stub_data
    application = make_verified_app(stub_data.requirements[Product.personal_loan])
    application.product_code = Product.personal_loan
    saved = app.state.review_store.create(
        idempotency_key="k", customer_id="cust-alex-morgan", session_id="session-1", product_code="personal_loan",
        snapshot={"customer_id": "cust-alex-morgan", "profile": stub_data.customers["cust-alex-morgan"]["profile"],
                  "application": application.model_dump(mode="json")},
        documents=[], now=NOW,
    )
    client = TestClient(app)
    client.app_id = saved.id
    return client


def decide(client, body, version=1):
    return client.post(f"/review/applications/{client.app_id}/decision", json={"version": version, **body}, headers=REVIEWER)


def test_customer_sees_only_their_applications(client):
    mine = client.get("/applications", headers=ALEX).json()["applications"]
    assert [a["id"] for a in mine] == [client.app_id]
    assert mine[0]["status_label"] == "Waiting for review"
    assert client.get("/applications", headers=OTHER).json()["applications"] == []
    assert client.get(f"/applications/{client.app_id}", headers=OTHER).status_code == 404


def test_reviewer_header_is_required(client):
    assert client.get("/review/applications").status_code == 403
    assert client.get("/review/applications", headers={"X-Reviewer-Id": "someone"}).status_code == 403
    queue = client.get("/review/applications", headers=REVIEWER).json()["applications"]
    assert queue[0]["customer_name"] == "Alex Morgan"


def test_stale_version_conflicts(client):
    assert decide(client, {"action": "approve", "reason": "ok"}, version=7).status_code == 409


def test_request_document_then_customer_uploads_and_reviewer_approves(client):
    response = decide(client, {"action": "request_document", "doc_type": "payslip", "reason": "Newer payslip"})
    assert response.status_code == 200
    view = client.get(f"/applications/{client.app_id}", headers=ALEX).json()
    assert view["status_label"] == "More information needed"
    assert view["open_request"]["doc_type"] == "payslip" and view["open_request"]["reason"] == "Newer payslip"

    url = f"/applications/{client.app_id}/requests/{view['open_request']['id']}/document"
    files = {"file": ("payslip.pdf", pdf_bytes(income_text(net="7.500,00")), "application/pdf")}
    assert client.post(url, files=files, headers=OTHER).status_code == 404
    uploaded = client.post(url, files=files, headers=ALEX).json()
    assert uploaded["accepted"] is True and uploaded["application"]["status_label"] == "Waiting for review"

    detail = client.get(f"/review/applications/{client.app_id}", headers=REVIEWER).json()
    assert {"field": "monthly_net_income", "before": "8500", "after": "7500.00"} in detail["changed_fields"]
    document_id = detail["documents"][0]["document_id"]
    file = client.get(f"/review/applications/{client.app_id}/documents/{document_id}", headers=REVIEWER)
    assert file.status_code == 200 and file.content.startswith(b"%PDF")

    approved = decide(client, {"action": "approve", "reason": "Income verified"}, version=detail["version"])
    assert approved.status_code == 200
    view = client.get(f"/applications/{client.app_id}", headers=ALEX).json()
    assert view["status_label"] == "Accepted" and view["history"][-1]["reason"] == "Income verified"


def test_wrong_document_is_rejected_with_reasons(client):
    decide(client, {"action": "request_document", "doc_type": "payslip", "reason": "Newer payslip"})
    view = client.get(f"/applications/{client.app_id}", headers=ALEX).json()
    url = f"/applications/{client.app_id}/requests/{view['open_request']['id']}/document"
    result = client.post(url, files={"file": ("x.pdf", pdf_bytes("Hello"), "application/pdf")}, headers=ALEX).json()
    assert result["accepted"] is False and result["reasons"]
    assert result["application"]["status_label"] == "More information needed"


def test_decision_requires_reason(client):
    assert decide(client, {"action": "reject", "reason": " "}).status_code == 422
