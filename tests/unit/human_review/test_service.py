"""Reviewer actions and requested uploads: only the requested, valid document moves the case on."""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.credit_sources.setup import create_database
from src.agent.tools.stubs import StubData
from src.core.composition import build_registry
from src.core.settings import OrchestratorSettings
from src.models.knowledge import Product
from src.services.document_processing.service import DocumentProcessingService
from src.services.human_review.models import InvalidTransition, NotFound, ReviewStatus
from src.services.human_review.service import NoPolicySearch, ReviewService
from src.services.human_review.store import ReviewStore
from src.storage.secure_documents.store import SecureDocumentStore
from tests.fixtures import documents as _docs
from tests.fixtures.documents import pdf_bytes
from tests.unit.orchestrator.factories import make_verified_app

# Documents for the demo customer cust-alex-morgan: the name matches the profile, the CNP is
# checksum-valid with Alex's birth date (1988-04-12, so 38 at the 2026-10-28 reference date).
CNP = _docs.cnp_for("188041241001")


def identity_text(**kw):
    return _docs.identity_text(**{"first_name": "ALEX", "last_name": "MORGAN", "cnp": CNP, **kw})


def income_text(**kw):
    return _docs.income_text(**{"name": "ALEX MORGAN", "cnp": CNP, **kw})


CONFIG = Path(__file__).resolve().parents[3] / "config" / "orchestrator"
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.fixture
def service(tmp_path):
    """The reviewer's recalculation uses the same tools as the chat: SQLite credit check included."""
    data = StubData.load(CONFIG)
    settings = OrchestratorSettings(
        config_dir=CONFIG, credit_sources_db=create_database(tmp_path / "credit_sources.db"),
        customer_bindings_path=CONFIG / "customer_bindings.yaml",
    )
    store = ReviewStore(tmp_path / "applications.sqlite3")
    documents = DocumentProcessingService(SecureDocumentStore(tmp_path / "uploads"))
    return ReviewService(store, documents, data, clock=lambda: NOW,
                         registry=build_registry(settings, data, NoPolicySearch()))


def submitted(service, *, selected_term=None):
    app = make_verified_app(service.stub_data.requirements[Product.personal_loan])
    app.product_code = Product.personal_loan
    if selected_term is not None:
        app.offers = price(service, app, selected_term)
        app.selected_offer_id = next(o.offer_id for o in app.offers.offers if o.term_months == selected_term)
    snapshot = {"customer_id": "cust-alex-morgan", "profile": service.stub_data.customers["cust-alex-morgan"]["profile"],
                "application": app.model_dump(mode="json")}
    return service.store.create(idempotency_key="k", customer_id="cust-alex-morgan", session_id="session-1",
                                product_code="personal_loan", snapshot=snapshot, documents=[], now=NOW)


def price(service, app, term):
    from src.agent.orchestration.state import Flow, OffersRecord, SessionState
    from src.agent.tools.contracts import CalculateOffersInput
    from src.agent.tools.pricing import calculate_offers
    from src.agent.tools.registry import ToolContext
    state = SessionState(session_id="s", customer_id="cust-alex-morgan", created_at=NOW, updated_at=NOW,
                         active_flow=Flow.credit_application, application=app)
    output = calculate_offers(CalculateOffersInput(term_options_months=[term]), ToolContext(state, NOW))
    return OffersRecord(offers=output.offers, input_fingerprint="test")


def with_payslip_request(service, **kwargs):
    app = submitted(service, **kwargs)
    return service.request_document(app.id, doc_type="payslip", reason="Please send a newer payslip", version=app.version)


def upload(service, app, text, customer="cust-alex-morgan"):
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
    """Reassessment uses the chat's credit check: ANAF (8,500) wins over the new payslip (2,500),
    and the gap is reported instead of silently changing the decision."""
    app, outcome = upload(service, with_payslip_request(service), income_text(net="2.500,00"))
    assert outcome.accepted, outcome.reasons
    assert app.current["eligibility"]["status"] == "satisfied"
    assert "income_gap" in {r["code"] for r in app.current["eligibility"]["reasons"]}
    assert app.current["offer"]["term_months"] == 48


def test_recalculation_keeps_the_term_the_customer_selected(service):
    app, outcome = upload(service, with_payslip_request(service, selected_term=36), income_text(net="7.500,00"))
    assert outcome.accepted, outcome.reasons
    assert app.current["offer"]["term_months"] == 36


def test_failed_processing_after_storing_leaves_no_file(service, monkeypatch):
    app = with_payslip_request(service)
    def boom(*args, **kwargs):
        raise ValueError("Missing field: employment_type")
    monkeypatch.setattr(service, "_recalculate", boom)
    with pytest.raises(ValueError):
        upload(service, app, income_text(net="7.500,00"))
    storage = service.documents.storage
    assert not [p for p in storage.root_dir.rglob("*") if p.is_file() and p.suffix in (".pdf", ".bin")]


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
        service.upload_requested(app.id, request_id, customer_id="cust-alex-morgan", filename="p.pdf",
                                 content=pdf_bytes(income_text()), mime_type="application/pdf")


def test_other_customer_cannot_upload(service):
    with pytest.raises(NotFound):
        upload(service, with_payslip_request(service), income_text(), customer="cust-andrei-stan")


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
