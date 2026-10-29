"""Review store: one durable record per submission, and only allowed status moves."""
from datetime import UTC, datetime

import pytest

from src.services.human_review.models import InvalidTransition, NotFound, ReviewDocument, ReviewStatus, StaleVersion
from src.services.human_review.store import ReviewStore

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    return ReviewStore(tmp_path / "applications.sqlite3")


def doc(document_id="doc-1", doc_type="payslip", origin="chat"):
    return ReviewDocument(document_id=document_id, doc_type=doc_type, origin=origin, status="accepted",
                          extracted_fields={"monthly_net_income": "6200.00"}, uploaded_at=NOW)


def make(store, key="session-1:v1", customer="customer-alex"):
    return store.create(
        idempotency_key=key, customer_id=customer, session_id="session-1", product_code="personal_loan",
        snapshot={"application": {"fields": {}}}, documents=[doc()], now=NOW,
    )


def request_payslip(store, app):
    return store.transition(app.id, to=ReviewStatus.MORE_INFORMATION_REQUIRED, actor="reviewer",
                            reason="Newer payslip", expected_version=app.version, now=NOW, request_doc_type="payslip")


def test_create_is_idempotent_and_starts_pending(store):
    a, b = make(store), make(store)
    assert a.id == b.id
    assert a.status == ReviewStatus.PENDING_HUMAN_REVIEW
    assert len(a.history) == 1 and a.history[0].from_status is None
    assert a.current == {"application": {"fields": {}}}


def test_request_information_opens_one_request(store):
    app = request_payslip(store, make(store))
    assert app.status == ReviewStatus.MORE_INFORMATION_REQUIRED
    assert [r.status for r in app.requests] == ["open"] and app.requests[0].doc_type == "payslip"
    assert app.version == 2


def test_final_status_rejects_further_transitions(store):
    app = store.transition(make(store).id, to=ReviewStatus.APPROVED, actor="reviewer", reason="ok",
                           expected_version=1, now=NOW)
    with pytest.raises(InvalidTransition):
        store.transition(app.id, to=ReviewStatus.REJECTED, actor="reviewer", reason="no",
                         expected_version=app.version, now=NOW)


def test_stale_version_is_rejected(store):
    app = make(store)
    with pytest.raises(StaleVersion):
        store.transition(app.id, to=ReviewStatus.APPROVED, actor="reviewer", reason="ok", expected_version=99, now=NOW)
    assert store.get(app.id).status == ReviewStatus.PENDING_HUMAN_REVIEW


def test_pending_cannot_be_set_by_reviewer_from_more_info(store):
    app = request_payslip(store, make(store))
    with pytest.raises(InvalidTransition):
        store.transition(app.id, to=ReviewStatus.PENDING_HUMAN_REVIEW, actor="reviewer", reason="x",
                         expected_version=app.version, now=NOW)


def test_fulfil_request_supersedes_old_document_and_returns_to_pending(store):
    app = request_payslip(store, make(store))
    new_current = {"application": {"fields": {"monthly_net_income": "7500.00"}}}
    app = store.fulfil_request(app.id, app.requests[0].id, document=doc("doc-2", origin="information_request"),
                               current=new_current, now=NOW)
    assert app.status == ReviewStatus.PENDING_HUMAN_REVIEW
    old = next(d for d in app.documents if d.document_id == "doc-1")
    assert old.superseded_by == "doc-2"
    assert app.requests[0].status == "fulfilled" and app.requests[0].fulfilled_document_id == "doc-2"
    assert app.current == new_current
    assert app.history[-1].actor == "system"


def test_fulfilled_request_cannot_be_fulfilled_twice(store):
    app = request_payslip(store, make(store))
    rid = app.requests[0].id
    store.fulfil_request(app.id, rid, document=doc("doc-2", origin="information_request"), current={}, now=NOW)
    with pytest.raises(InvalidTransition):
        store.fulfil_request(app.id, rid, document=doc("doc-3", origin="information_request"), current={}, now=NOW)


def test_list_filters_by_customer(store):
    make(store, key="a", customer="customer-alex")
    make(store, key="b", customer="cust-001")
    assert [a.customer_id for a in store.list(customer_id="customer-alex")] == ["customer-alex"]
    with pytest.raises(NotFound):
        store.get("APP-MISSING")
