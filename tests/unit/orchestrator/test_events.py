"""Tests for code-handled events: uploads, offer selection, confirmation/submission."""
import json
import shutil
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from src.agent.orchestration.orchestrator import (
    EVENT_TEXTS,
    CustomerMessage,
    DocumentUploaded,
    OfferSelected,
)
from src.agent.orchestration.progress import NeedKind, next_needs
from src.agent.orchestration.state import DocumentStatus
from src.core.errors import InvalidUpload, SessionAccessDenied, ToolUnavailable
from src.models.knowledge import Product
from src.storage.secure_documents.local import LocalDocumentStorage, sanitize_filename
from tests.unit.orchestrator.factories import (
    call,
    make_collecting_app,
    make_verified_app,
    respond,
    seed_application,
    spy_tool,
)

CUSTOMER = "cust-alex-morgan"
GREET = respond("Bună! Cu ce te pot ajuta?")
PAYSLIP_LABEL = "Payslip (last 3 months)"


def upload(doc_type, filename=None, document_id=None, size_bytes=1024):
    return DocumentUploaded(
        document_id=document_id or f"up-{doc_type}",
        doc_type=doc_type,
        filename=filename or f"{doc_type}.pdf",
        size_bytes=size_bytes,
    )


def events(store, sid) -> list[str]:
    return [m.content for m in store.messages(sid) if m.role == "event"]


def block(resp, kind):
    return next((b for b in resp.blocks if b.type == kind), None)


def set_language(store, sid, language):
    state = store.get(sid)
    state.language = language
    store.save(state, state.version)


@pytest.fixture
def requirements(stub_data):
    return stub_data.requirements[Product.personal_loan]


@pytest.fixture
def collecting(orchestrator_factory, requirements):
    """A session in the documents stage: product set, customer income 7000."""
    def make(responses):
        orch, store, model = orchestrator_factory([GREET, *responses])
        sid = orch.start_session(CUSTOMER).session_id
        seed_application(store, sid, make_collecting_app(requirements, {
            "employment_type": "employed",
            "employment_months": 67,
            "monthly_net_income": Decimal("7000"),
            "employer_name": "FICTIV Employer's Studio 1",
            "existing_monthly_obligations": Decimal("0"),
        }))
        return orch, store, model, sid
    return make


@pytest.fixture
def at_offers(orchestrator_factory, requirements):
    """A verified session with three current offers and none selected."""
    def make(responses=()):
        orch, store, model = orchestrator_factory([
            GREET,
            call("run_eligibility_check"),
            call("calculate_loan_offer", {"term_options_months": [36, 60]}),
            respond("Iată ofertele.", intent="credit_application"),
            *responses,
        ])
        sid = orch.start_session(CUSTOMER).session_id
        seed_application(store, sid, make_verified_app(requirements))
        orch.handle(sid, CUSTOMER, CustomerMessage("Vreau ofertele"))
        return orch, store, model, sid
    return make


@pytest.fixture
def at_confirmation(at_offers):
    """A session awaiting confirmation of the summary for the first offer."""
    def make(responses=()):
        orch, store, model, sid = at_offers([respond("Confirmi?"), *responses])
        offer = store.get(sid).application.offers.offers[0]
        orch.handle(sid, CUSTOMER, OfferSelected(offer.offer_id))
        version = store.get(sid).application.summary.summary_version
        return orch, store, model, sid, version
    return make


# ---- uploads ----------------------------------------------------------------

def test_check_upload_rejects_unrequested(orchestrator_factory, requirements):
    orch, store, _ = orchestrator_factory([GREET])
    sid = orch.start_session(CUSTOMER).session_id

    with pytest.raises(InvalidUpload) as exc:
        orch.check_upload(sid, CUSTOMER, "payslip")
    assert exc.value.code == "document_not_requested"

    seed_application(store, sid, make_collecting_app(requirements))
    with pytest.raises(InvalidUpload) as exc:
        orch.check_upload(sid, CUSTOMER, "passport")
    assert exc.value.code == "document_not_requested"
    orch.check_upload(sid, CUSTOMER, "payslip")  # requested: no error

    with pytest.raises(SessionAccessDenied):
        orch.check_upload(sid, "cust-andrei-stan", "payslip")
    # handle() re-checks under the lock and records nothing.
    before = store.get(sid)
    with pytest.raises(InvalidUpload):
        orch.handle(sid, CUSTOMER, upload("passport"))
    assert store.get(sid) == before


def test_upload_accepted_merges_fields_and_conflict(collecting):
    orch, store, model, sid = collecting([respond("Am primit fluturașul.")])
    resp = orch.handle(sid, CUSTOMER, upload("payslip"))

    app = store.get(sid).application
    [record] = app.documents
    assert record.status == DocumentStatus.accepted
    assert record.document_id == "up-payslip"
    assert app.fields["monthly_net_income"].value == Decimal("8500")
    assert app.fields["monthly_net_income"].document_id == "up-payslip"
    [conflict] = app.conflicts
    assert conflict.field == "monthly_net_income"
    assert Decimal(conflict.customer_value) == Decimal("7000")
    assert conflict.document_id == "up-payslip"

    extracted = {f.field: f for f in block(resp, "extracted_fields").fields}
    assert Decimal(extracted["monthly_net_income"].conflict_with) == Decimal("7000")
    assert extracted["employer_name"].needs_confirmation is True
    assert events(store, sid) == ["SESSION_STARTED", "DOCUMENT_PROCESSED payslip: accepted"]
    assert "EVENT: DOCUMENT_PROCESSED payslip: accepted" in [m.content for m in model.calls[-1]]
    assert [m.text for m in resp.messages] == ["Am primit fluturașul."]
    assert resp.simulated is True


def test_upload_rejected_sets_reason(collecting):
    orch, store, _, sid = collecting([respond("Te rog încarcă din nou.")])
    resp = orch.handle(sid, CUSTOMER, upload("payslip", filename="reject_payslip.pdf"))

    state = store.get(sid)
    [record] = state.application.documents
    assert record.status == DocumentStatus.rejected
    reason = record.rejection_reason
    assert reason
    payslip_need = next(n for n in next_needs(state) if n.target == "payslip")
    assert payslip_need.kind == NeedKind.document and payslip_need.detail == reason
    item = next(i for i in block(resp, "document_checklist").items if i.doc_type == "payslip")
    assert item.status == "rejected" and item.rejection_reason == reason
    assert state.application.fields["monthly_net_income"].value == Decimal("7000")
    assert events(store, sid)[-1] == f"DOCUMENT_PROCESSED payslip: rejected {reason}"


def test_reupload_replaces_record(collecting):
    orch, store, _, sid = collecting([respond("a"), respond("b"), respond("c")])
    orch.handle(sid, CUSTOMER, upload("payslip", document_id="d1"))
    orch.handle(sid, CUSTOMER, upload("payslip", filename="reject_payslip.pdf", document_id="d2"))
    app = store.get(sid).application
    assert [(d.document_id, d.status) for d in app.documents] == [("d2", DocumentStatus.rejected)]

    orch.handle(sid, CUSTOMER, upload("payslip", document_id="d3"))
    app = store.get(sid).application
    assert [(d.document_id, d.status) for d in app.documents] == [("d3", DocumentStatus.accepted)]
    # Extraction and conflict detection re-ran against the new record.
    assert app.fields["monthly_net_income"].document_id == "d3"
    assert [(c.field, c.document_id) for c in app.conflicts] == [("monthly_net_income", "d3")]


def test_document_fallback_when_model_unavailable(collecting):
    orch, store, _, sid = collecting(["!unavailable", "!unavailable"])
    resp = orch.handle(sid, CUSTOMER, upload("payslip"))
    assert [m.text for m in resp.messages] == [f"Am primit documentul: {PAYSLIP_LABEL}."]
    assert store.get(sid).application.documents[0].status == DocumentStatus.accepted

    set_language(store, sid, "en")
    resp = orch.handle(sid, CUSTOMER, upload("payslip", filename="reject_x.pdf", document_id="d2"))
    reason = store.get(sid).application.documents[0].rejection_reason
    assert [m.text for m in resp.messages] == [f"We couldn't use your {PAYSLIP_LABEL}: {reason}"]
    assert store.messages(sid)[-1].content == resp.messages[0].text


def test_upload_tool_failure_marks_rejected(collecting):
    orch, store, _, sid = collecting(["!unavailable"])
    spy_tool(orch._registry, "process_document", fail=ToolUnavailable("extractor down"))
    resp = orch.handle(sid, CUSTOMER, upload("payslip"))
    [record] = store.get(sid).application.documents
    assert record.status == DocumentStatus.rejected
    assert record.rejection_reason
    assert resp.messages[0].text == f"Nu am putut folosi documentul {PAYSLIP_LABEL}: {record.rejection_reason}"


# ---- offer selection ----------------------------------------------------------


def test_offer_fallback_on_invalid_output(at_offers):
    orch, store, _, sid = at_offers(["garbage", "garbage"])
    set_language(store, sid, "en")
    chosen = store.get(sid).application.offers.offers[1]
    resp = orch.handle(sid, CUSTOMER, OfferSelected(chosen.offer_id))
    assert [m.text for m in resp.messages] == [f"You chose the {chosen.term_months}-month option."]
    assert store.get(sid).application.selected_offer_id == chosen.offer_id


def test_offer_fallback_romanian_month_phrase(at_offers):
    orch, store, _, sid = at_offers(["!unavailable"])
    chosen = store.get(sid).application.offers.offers[0]
    assert chosen.term_months == 48
    resp = orch.handle(sid, CUSTOMER, OfferSelected(chosen.offer_id))
    assert resp.messages[0].text == "Ai ales varianta pe 48 de luni."


# ---- confirmation ---------------------------------------------------------------


# ---- happy path ------------------------------------------------------------------

STATED = [
    {"field": "employment_type", "value": "employed"},
    {"field": "employment_months", "value": 67},
    {"field": "monthly_net_income", "value": "8500 lei"},
    {"field": "employer_name", "value": "FICTIV Employer's Studio 1"},
    {"field": "existing_monthly_obligations", "value": "0"},
]


AGREEMENT_OVERRIDE: dict[str, str] = {}


def scripted_model(messages):
    """A model that reacts to CONTEXT_JSON needs and the latest message."""
    context = json.loads(messages[-1].content.removeprefix("CONTEXT_JSON:\n"))
    last = next(m.content for m in reversed(messages) if m.role != "system")
    from_customer = not last.startswith(("EVENT:", "TOOL_"))
    needs = context["needs"]
    first = needs[0]["kind"] if needs else None

    if context["stage"] is None:
        if from_customer and last != "EVENT: SESSION_STARTED":
            return respond("Ce produs?", "credit_application", [
                {"field": "purpose", "value": "renovare"},
                {"field": "amount", "value": "30.000 lei"},
                {"field": "term_months", "value": 48},
            ])
        return respond("Bună!")
    if first == "choose_product":
        return respond("Notat.", "credit_application", [{"field": "product_code", "value": "personal_loan"}])
    if first == "missing_field":
        return respond("Mulțumesc.", "credit_application", STATED)
    if first == "run_eligibility":
        return call("run_eligibility_check")
    if first == "run_offers":
        return call("calculate_loan_offer", {"term_options_months": [36, 60]})
    if first == "confirm_submission" and from_customer and last.startswith(("Da", "Yes")):
        agreement = AGREEMENT_OVERRIDE.get("text") or last
        return call("submit_application", {"customer_agreement": agreement})
    if first == "confirm_extracted" and from_customer:
        return respond("Confirmat.", "credit_application",
                       [{"field": n["target"], "confirm": True} for n in needs if n["kind"] == "confirm_extracted"])
    return respond(f"Pasul următor: {first}", "credit_application")


def test_full_happy_path_with_scripted_model(orchestrator_factory):
    orch, store, _ = orchestrator_factory(scripted_model)
    start = orch.start_session(CUSTOMER)
    sid = start.session_id
    assert start.awaiting.kind == "text"

    def say(text):
        return orch.handle(sid, CUSTOMER, CustomerMessage(text))

    resp = say("Vreau un credit de 30.000 lei pe 48 de luni pentru renovare")
    assert (resp.progress.stage, resp.awaiting.kind) == ("discovery", "text")

    resp = say("Un credit de nevoi personale")
    assert (resp.progress.stage, resp.awaiting.kind) == ("collecting_information", "text")
    assert store.get(sid).application.fields["full_name"].value == "Alex Morgan"

    # The last stated field completes the inputs: code runs eligibility in the same turn.
    resp = say("Sunt angajată de 4 ani la FICTIV Employer's Studio 1, câștig 8500 lei, fără rate")
    assert (resp.progress.stage, resp.awaiting.kind) == ("documents", "document")
    assert resp.awaiting.document_types == ["id_card", "payslip", "bank_statement"]
    assert store.get(sid).application.eligibility is not None

    resp = orch.handle(sid, CUSTOMER, upload("id_card"))
    assert resp.awaiting.document_types == ["payslip", "bank_statement"]
    resp = orch.handle(sid, CUSTOMER, upload("payslip"))
    assert resp.awaiting.document_types == ["bank_statement"]
    resp = orch.handle(sid, CUSTOMER, upload("bank_statement"))
    assert (resp.progress.stage, resp.awaiting.kind) == ("documents", "text")
    assert store.get(sid).application.conflicts == []

    # Confirming makes eligibility stale; code re-runs it on verified inputs, then the model prices.
    resp = say("Datele sunt corecte")
    assert (resp.progress.stage, resp.awaiting.kind) == ("offer_selection", "offer_choice")
    app = store.get(sid).application
    assert app.eligibility.verified_inputs is True
    assert len(app.offers.offers) == 3

    resp = orch.handle(sid, CUSTOMER, OfferSelected(app.offers.offers[0].offer_id))
    assert (resp.progress.stage, resp.awaiting.kind) == ("awaiting_confirmation", "text")
    assert not [b for b in resp.blocks if b.type == "application_summary"]

    resp = say("Da, trimite cererea")
    assert (resp.progress.stage, resp.awaiting.kind) == ("submitted", "none")
    app = store.get(sid).application
    assert block(resp, "application_submitted").application_id == app.application_id
    assert [s.status for s in resp.progress.steps] == ["done"] * 6 + ["current"]
    assert resp.simulated is True


# ---- local document storage -------------------------------------------------------

def test_sanitize_filename():
    assert sanitize_filename("my payslip (1).pdf") == "mypayslip1.pdf"
    assert sanitize_filename("fluturaș_salariu-2026.PDF") == "flutura_salariu-2026.PDF"
    assert sanitize_filename("a" * 150 + ".pdf") == "a" * 100
    assert sanitize_filename("///") == "upload"
    assert sanitize_filename("..") == "upload"
    assert sanitize_filename("") == "upload"


@pytest.fixture
def tmp_dir():
    """A fresh directory inside the worktree (the system temp dir is not writable here)."""
    path = Path(__file__).parent / ".test_tmp" / f"events-{uuid4().hex}"
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_local_storage_writes_under_root(tmp_dir):
    storage = LocalDocumentStorage(tmp_dir / "uploads")
    path = storage.save("sess1", "doc1", "../../etc/pass wd.pdf", b"%PDF-1.4")
    assert path == tmp_dir / "uploads" / "sess1" / "doc1-....etcpasswd.pdf"
    assert path.read_bytes() == b"%PDF-1.4"
    assert storage.save("sess1", "doc2", "", b"x").name == "doc2-upload"


@pytest.mark.parametrize("session_id,document_id", [("../x", "doc"), ("s", "../d"), ("", "d"), ("s", "a/b")])
def test_local_storage_rejects_unsafe_ids(tmp_dir, session_id, document_id):
    storage = LocalDocumentStorage(tmp_dir)
    with pytest.raises(ValueError):
        storage.save(session_id, document_id, "f.pdf", b"x")
    assert list(tmp_dir.iterdir()) == []


# ---- submission by explicit agreement in chat ---------------------------------

def to_confirmation(orchestrator_factory):
    orch, store, model = orchestrator_factory(scripted_model)
    sid = orch.start_session(CUSTOMER).session_id
    say = lambda text: orch.handle(sid, CUSTOMER, CustomerMessage(text))
    for text in ("Vreau un credit de 30.000 lei pe 48 de luni pentru renovare", "Un credit de nevoi personale",
                 "Sunt angajată de 4 ani la TechCorp SRL, câștig 6200 lei, rate 400 lei", "Verifică eligibilitatea"):
        say(text)
    for doc in ("id_card", "payslip", "bank_statement"):
        orch.handle(sid, CUSTOMER, upload(doc))
    say("Datele sunt corecte")
    resp = say("Vreau ofertele")
    resp = orch.handle(sid, CUSTOMER, OfferSelected(resp.blocks[[b.type for b in resp.blocks].index("offers")].offers[0].offer_id))
    assert resp.progress.stage == "awaiting_confirmation"
    return orch, store, sid, say


def test_explicit_agreement_submits_with_fixed_reply(orchestrator_factory):
    orch, store, sid, say = to_confirmation(orchestrator_factory)
    resp = say("Da, trimite cererea")
    app = store.get(sid).application
    assert app.application_id and resp.progress.stage == "submitted"
    assert app.application_id in resp.messages[-1].text
    # The model quoted the customer's words; the code-side submission ran once.
    assert any('"customer_agreement": "Da, trimite cererea"' in m.content
               for m in store.messages(sid) if m.role == "action")


def test_agreement_not_in_customer_message_is_refused(orchestrator_factory):
    orch, store, sid, say = to_confirmation(orchestrator_factory)
    AGREEMENT_OVERRIDE["text"] = "I agree to submit"
    try:
        resp = say("Da, dar am o întrebare")
    finally:
        AGREEMENT_OVERRIDE.clear()
    assert store.get(sid).application.application_id is None
    assert resp.progress.stage == "awaiting_confirmation"


def test_tool_refused_on_non_customer_turn(orchestrator_factory):
    orch, store, sid, say = to_confirmation(orchestrator_factory)
    state = store.get(sid)
    turn = orch._begin_turn(state, upload("id_card"))
    outcome = orch._submit_from_model(turn, {"customer_agreement": "Da"})
    assert not outcome.ok and outcome.error_code == "precondition_failed"
    assert state.application.application_id is None


def test_tool_refused_when_not_at_confirmation(orchestrator_factory):
    orch, store, model = orchestrator_factory(scripted_model)
    sid = orch.start_session(CUSTOMER).session_id
    state = store.get(sid)
    turn = orch._begin_turn(state, CustomerMessage("Da"))
    turn.customer_text = "Da"
    outcome = orch._submit_from_model(turn, {"customer_agreement": "Da"})
    assert not outcome.ok and outcome.error_code == "precondition_failed"


def test_second_call_does_not_duplicate(orchestrator_factory):
    orch, store, sid, say = to_confirmation(orchestrator_factory)
    say("Da, trimite cererea")
    first = store.get(sid).application.application_id
    say("Da, trimite cererea")
    assert store.get(sid).application.application_id == first


def test_offer_selection_valid_and_invalid(at_offers):
    orch, store, model, sid = at_offers([respond("Nu există."), respond("Confirmi?")])

    resp = orch.handle(sid, CUSTOMER, OfferSelected("no-such-offer"))
    app = store.get(sid).application
    assert app.selected_offer_id is None
    assert events(store, sid)[-1] == "OFFER_SELECTION_REJECTED"
    assert resp.awaiting.kind == "offer_choice"

    chosen = app.offers.offers[1]
    resp = orch.handle(sid, CUSTOMER, OfferSelected(chosen.offer_id))
    app = store.get(sid).application
    assert app.selected_offer_id == chosen.offer_id
    assert events(store, sid)[-1] == f"OFFER_SELECTED {chosen.offer_id}"
    assert resp.awaiting.kind == "text"
    assert app.summary.offer.offer_id == chosen.offer_id
