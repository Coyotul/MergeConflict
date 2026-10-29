"""Reviewer actions and requested uploads: only the requested, valid document moves the case on."""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.agent.tools.stubs import StubData
from src.models.knowledge import Product
from src.services.document_processing.service import DocumentProcessingService
from src.services.human_review.models import InvalidTransition, NotFound, ReviewStatus
from src.services.human_review.service import ReviewService
from src.services.human_review.store import ReviewStore
from src.storage.secure_documents.store import SecureDocumentStore
from tests.fixtures.documents import identity_text, income_text, pdf_bytes
from tests.unit.orchestrator.factories import make_verified_app

CONFIG = Path(__file__).resolve().parents[3] / "config" / "orchestrator"
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.fixture
def service(tmp_path):
    data = StubData.load(CONFIG)
    store = ReviewStore(tmp_path / "applications.sqlite3")
    documents = DocumentProcessingService(SecureDocumentStore(tmp_path / "uploads"))
    return ReviewService(store, documents, data, clock=lambda: NOW)


def submitted(service):
    app = make_verified_app(service.stub_data.requirements[Product.personal_loan])
    app.product_code = Product.personal_loan
    snapshot = {"customer_id": "cust-001", "profile": service.stub_data.customers["cust-001"]["profile"],
                "application": app.model_dump(mode="json")}
    return service.store.create(idempotency_key="k", customer_id="cust-001", session_id="session-1",
                                product_code="personal_loan", snapshot=snapshot, documents=[], now=NOW)


def with_payslip_request(service):
    app = submitted(service)
    return service.request_document(app.id, doc_type="payslip", reason="Please send a newer payslip", version=app.version)


def upload(service, app, text, customer="cust-001"):
    return service.upload_requested(app.id, app.open_request.id, customer_id=customer, filename="payslip.pdf",
                                    content=pdf_bytes(text), mime_type="application/pdf")


def test_valid_payslip_fulfils_request_and_returns_to_pending(service):
    app, outcome = upload(service, with_payslip_request(service), income_text(net="7.500,00"))
    assert outcome.accepted, outcome.reasons
    assert app.status == ReviewStatus.PENDING_HUMAN_REVIEW
    assert app.requests[0].status == "fulfilled"
    assert app.current["application"]["fields"]["monthly_net_income"]["value"] == "7500.00"
    assert [d.origin for d in app.documents] == ["information_request"]


def test_accepted_upload_recalculates_eligibility_and_offer(service):
    app, outcome = upload(service, with_payslip_request(service), income_text(net="2.500,00"))
    assert outcome.accepted, outcome.reasons
    assert app.current["eligibility"] is not None
    assert app.current["eligibility"]["status"] != "satisfied"
    assert app.current["offer"] is None or app.current["offer"]["term_months"] == 48


def test_id_card_uploaded_for_payslip_request_is_rejected(service):
    app, outcome = upload(service, with_payslip_request(service), identity_text())
    assert not outcome.accepted
    assert outcome.reasons[0].startswith("This doesn't look like the requested payslip")
    assert app.status == ReviewStatus.MORE_INFORMATION_REQUIRED and app.open_request is not None


def test_fixed_term_payslip_needing_human_review_is_rejected_to_customer(service):
    app, outcome = upload(service, with_payslip_request(service), income_text(contract="DETERMINATA"))
    assert not outcome.accepted and outcome.reasons
    assert app.status == ReviewStatus.MORE_INFORMATION_REQUIRED


def test_upload_without_open_request_conflicts(service):
    app = with_payslip_request(service)
    request_id = app.open_request.id
    upload(service, app, income_text())
    with pytest.raises(InvalidTransition):
        service.upload_requested(app.id, request_id, customer_id="cust-001", filename="p.pdf",
                                 content=pdf_bytes(income_text()), mime_type="application/pdf")


def test_other_customer_cannot_upload(service):
    with pytest.raises(NotFound):
        upload(service, with_payslip_request(service), income_text(), customer="cust-002")


def test_request_type_not_in_requirements_is_refused(service):
    app = submitted(service)
    with pytest.raises(ValueError):
        service.request_document(app.id, doc_type="property_valuation", reason="x", version=app.version)
    with pytest.raises(ValueError):
        service.request_document(app.id, doc_type="payslip", reason="  ", version=app.version)


def test_decide_requires_reason_and_records_it(service):
    app = submitted(service)
    with pytest.raises(ValueError):
        service.decide(app.id, action="approve", reason="", version=app.version)
    app = service.decide(app.id, action="approve", reason="Income verified", version=app.version)
    assert app.status == ReviewStatus.APPROVED and app.history[-1].reason == "Income verified"
