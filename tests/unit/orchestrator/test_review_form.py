"""Documents first: no questions the documents answer, then one review form."""
import pytest

from src.agent.orchestration.events import ExtractedFieldsReviewed, InvalidFieldEdit
from src.agent.orchestration.orchestrator import CustomerMessage
from src.agent.orchestration.progress import NeedKind, next_needs
from tests.unit.orchestrator.factories import call, respond, seed_application
from tests.unit.orchestrator.test_events import CUSTOMER, upload

DOCS = ("id_card", "payslip", "bank_statement")


def model(messages):
    """Replies with the first need; never asks for anything the context does not need."""
    import json
    context = json.loads(messages[-1].content.removeprefix("CONTEXT_JSON:\n"))
    needs = context["needs"]
    if needs and needs[0]["kind"] == "run_eligibility":
        return call("run_eligibility_check")
    return respond("Next: " + (needs[0]["kind"] if needs else "none"), "credit_application")


@pytest.fixture
def at_documents(orchestrator_factory, stub_data):
    from src.models.knowledge import Product
    from tests.unit.orchestrator.factories import make_collecting_app
    orch, store, _ = orchestrator_factory(model)
    sid = orch.start_session(CUSTOMER).session_id
    seed_application(store, sid, make_collecting_app(stub_data.requirements[Product.personal_loan]))
    return orch, store, sid


def kinds(store, sid):
    return [n.kind for n in next_needs(store.get(sid))]


def upload_all(orch, sid):
    resp = None
    for doc in DOCS:
        resp = orch.handle(sid, CUSTOMER, upload(doc))
    return resp


def test_documents_requested_without_asking_document_fields(at_documents):
    orch, store, sid = at_documents
    assert set(kinds(store, sid)) == {NeedKind.document}


def test_pending_documents_are_the_only_needs(at_documents):
    orch, store, sid = at_documents
    orch.handle(sid, CUSTOMER, upload("id_card"))
    assert kinds(store, sid) == [NeedKind.document, NeedKind.document]


def test_form_offered_after_all_documents_accepted(at_documents):
    orch, store, sid = at_documents
    resp = upload_all(orch, sid)
    assert kinds(store, sid) == [NeedKind.review_extracted]
    assert resp.awaiting.kind == "review_form"
    form = next(b for b in resp.blocks if b.type == "extracted_fields")
    editable = {f.field for f in form.fields if f.editable}
    assert editable == {"full_name", "employer_name"}
    assert {"monthly_net_income", "existing_monthly_obligations"} <= {f.field for f in form.fields}


def test_review_confirms_values_and_applies_allowed_edit(at_documents):
    orch, store, sid = at_documents
    upload_all(orch, sid)
    orch.handle(sid, CUSTOMER, ExtractedFieldsReviewed(edits={"employer_name": "Northstar Studio SRL"}))
    app = store.get(sid).application
    assert all(v.confirmed for v in app.fields.values())
    assert app.fields["employer_name"].value == "Northstar Studio SRL"
    assert NeedKind.review_extracted not in kinds(store, sid)


def test_edit_to_read_only_field_is_refused(at_documents):
    orch, store, sid = at_documents
    upload_all(orch, sid)
    with pytest.raises(InvalidFieldEdit):
        orch.handle(sid, CUSTOMER, ExtractedFieldsReviewed(edits={"monthly_net_income": "20000"}))
    app = store.get(sid).application
    assert app.fields["monthly_net_income"].value == 8500
    assert not app.fields["monthly_net_income"].confirmed


def test_invalid_editable_value_is_refused(at_documents):
    orch, store, sid = at_documents
    upload_all(orch, sid)
    with pytest.raises(InvalidFieldEdit):
        orch.handle(sid, CUSTOMER, ExtractedFieldsReviewed(edits={"full_name": "  "}))


def test_review_before_documents_is_rejected(at_documents):
    orch, store, sid = at_documents
    orch.handle(sid, CUSTOMER, upload("id_card"))
    orch.handle(sid, CUSTOMER, ExtractedFieldsReviewed(edits={}))
    app = store.get(sid).application
    assert not any(v.confirmed for v in app.fields.values() if v.source.value == "document")


def test_reupload_after_review_reopens_form(at_documents):
    orch, store, sid = at_documents
    upload_all(orch, sid)
    orch.handle(sid, CUSTOMER, ExtractedFieldsReviewed(edits={}))
    orch.handle(sid, CUSTOMER, upload("payslip", document_id="up-payslip-2"))
    assert kinds(store, sid)[:1] == [NeedKind.review_extracted]


def test_model_cannot_confirm_or_set_document_values(at_documents):
    from datetime import UTC, datetime
    from src.agent.orchestration.blocks import all_specs
    from src.agent.orchestration.fields import FieldUpdate, apply_field_updates
    orch, store, sid = at_documents
    upload_all(orch, sid)
    app = store.get(sid).application
    results = apply_field_updates(app, [FieldUpdate(field="monthly_net_income", confirm=True),
                                        FieldUpdate(field="monthly_net_income", value="20000")],
                                  all_specs(app), offer_ids=set(), now=datetime.now(UTC))
    assert [r.reason for r in results] == ["review_form_only", "from_documents_only"]
    assert not app.fields["monthly_net_income"].confirmed and app.fields["monthly_net_income"].value == 8500
