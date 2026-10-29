"""Tests for the orchestrator turn loop (customer messages) and response blocks."""
import hashlib
import json
import logging
from datetime import datetime, UTC
from decimal import Decimal

import pytest

from src.agent.orchestration.blocks import build_turn_response
from src.agent.orchestration.orchestrator import (
    CustomerMessage,
    FALLBACK_GREETING,
    FALLBACK_REPLY,
    detect_language,
)
from src.agent.orchestration.progress import (
    MAIN_STAGES,
    Stage,
    derive_stage,
    eligibility_input_names,
    fingerprint,
)
from src.agent.orchestration.state import (
    EligibilityRecord,
    FieldSource,
    Flow,
    SessionState,
)
from src.core.errors import (
    ModelUnavailable,
    SessionAccessDenied,
    SessionBusy,
    SessionNotFound,
)
from src.models.credit import EligibilityResult, EligibilityStatus, ReasonItem
from src.models.knowledge import Product
from tests.unit.orchestrator.factories import call, make_verified_app, respond, seed_application

CUSTOMER = "cust-001"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


# ---- scripted model output helpers ----------------------------------------

GREET = respond("Bună! Cu ce te pot ajuta?")
DISCOVERY_UPDATES = [
    {"field": "purpose", "value": "renovation"},
    {"field": "amount", "value": "30000"},
    {"field": "term_months", "value": 48},
]


def joined(messages) -> str:
    return "\n".join(m.content for m in messages)


def turn_calls(model, before: int):
    return model.calls[before:]


# ---- start_session --------------------------------------------------------

def test_start_session_greets(orchestrator_factory):
    orch, store, model = orchestrator_factory([GREET])
    resp = orch.start_session(CUSTOMER)

    assert resp.messages[0].role == "assistant"
    assert resp.messages[0].text == "Bună! Cu ce te pot ajuta?"
    assert resp.progress.flow == "none"
    assert resp.progress.stage is None
    assert resp.awaiting.kind == "text"
    assert "EVENT: SESSION_STARTED" in joined(model.calls[0])
    state = store.get(resp.session_id)
    assert state.customer_id == CUSTOMER
    assert resp.session_version == state.version
    roles = [m.role for m in store.messages(resp.session_id)]
    assert roles == ["event", "assistant"]


def test_start_session_falls_back_when_model_unavailable(orchestrator_factory):
    orch, store, _ = orchestrator_factory(["!unavailable"])
    resp = orch.start_session(CUSTOMER)
    assert resp.messages[0].text == FALLBACK_GREETING
    assert store.get(resp.session_id).customer_id == CUSTOMER


def test_start_session_falls_back_on_invalid_output(orchestrator_factory):
    orch, _, _ = orchestrator_factory(["not json"])
    resp = orch.start_session(CUSTOMER)
    assert resp.messages[0].text == FALLBACK_GREETING


# ---- customer messages ----------------------------------------------------

def test_credit_intent_starts_application_and_records_fields(orchestrator_factory):
    orch, store, _ = orchestrator_factory([
        GREET,
        respond("Ce perioadă dorești?", intent="credit_application",
                updates=[{"field": "amount", "value": "30.000 lei"}]),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    resp = orch.handle(sid, CUSTOMER, CustomerMessage("Vreau un credit de 30.000 lei"))

    state = store.get(sid)
    assert state.active_flow == Flow.credit_application
    assert state.application.fields["amount"].value == Decimal("30000")
    assert state.application.fields["amount"].source == FieldSource.customer
    assert resp.progress.flow == "credit_application"
    assert resp.progress.stage == "discovery"
    assert resp.awaiting.kind == "text"
    assert resp.messages[0].text == "Ce perioadă dorești?"
    assert resp.session_version == state.version


def test_product_code_triggers_requirements_and_profile(orchestrator_factory):
    orch, store, model = orchestrator_factory([
        GREET,
        respond("Ce tip de angajare ai?", intent="credit_application",
                updates=DISCOVERY_UPDATES + [{"field": "product_code", "value": "personal_loan"}]),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    resp = orch.handle(sid, CUSTOMER, CustomerMessage("Vreau un credit pentru renovare"))

    app = store.get(sid).application
    assert app.product_code == Product.personal_loan
    assert app.requirements is not None
    assert app.requirements.product_code == Product.personal_loan
    for name, value in (("full_name", "Ana Popescu"), ("age", 34)):
        assert app.fields[name].source == FieldSource.profile
        assert app.fields[name].confirmed is True
        assert app.fields[name].value == value
    assert resp.progress.stage == "collecting_information"
    checklist = [b for b in resp.blocks if b.type == "document_checklist"]
    assert [i.doc_type for i in checklist[0].items] == ["id_card", "payslip", "bank_statement"]
    assert all(i.status == "requested" for i in checklist[0].items)
    assert resp.simulated is True


def test_product_fields_in_same_batch_as_product_code_accepted(orchestrator_factory):
    """Product-specific fields listed before product_code in one batch are not unknown_field."""
    orch, store, model = orchestrator_factory([
        GREET,
        respond("Mulțumesc!", intent="credit_application", updates=DISCOVERY_UPDATES + [
            {"field": "monthly_net_income", "value": "6200 RON"},
            {"field": "product_code", "value": "personal_loan"},
        ]),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("Venitul meu net este 6200 lei"))

    app = store.get(sid).application
    assert app.product_code == Product.personal_loan
    assert app.fields["monthly_net_income"].value == Decimal("6200")
    assert "unknown_field" not in joined(model.calls[-1])
    assert len(model.calls) == 2  # no re-ask step was needed


def test_product_code_outside_catalog_rejected(orchestrator_factory):
    orch, store, model = orchestrator_factory([
        GREET,
        respond("x", intent="credit_application", updates=[{"field": "product_code", "value": "car_loan"}]),
        respond("Ce produs?", intent="credit_application"),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("credit auto"))
    assert store.get(sid).application.product_code is None
    assert "unknown_product" in joined(model.calls[-1])


def test_tool_result_fed_back_as_message(orchestrator_factory):
    orch, store, model = orchestrator_factory([
        GREET,
        call("get_credit_products", intent="product_info"),
        respond("Avem trei produse.", intent="product_info"),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    resp = orch.handle(sid, CUSTOMER, CustomerMessage("Ce credite aveți?"))

    calls = turn_calls(model, 1)
    assert len(calls) == 2
    assert "TOOL_RESULT get_credit_products:" in joined(calls[1])
    assert "TOOL_RESULT get_credit_products:" not in joined(calls[0])
    assert resp.messages[0].text == "Avem trei produse."
    assert resp.progress.flow == "product_info"
    assert resp.simulated is True
    roles = [m.role for m in store.messages(sid)]
    assert roles == ["event", "assistant", "customer", "action", "tool", "assistant"]


def test_customer_message_visible_to_model_in_same_turn(orchestrator_factory):
    orch, _, model = orchestrator_factory([GREET, respond("Salut")])
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("salutare tuturor"))
    user_msgs = [m.content for m in model.calls[1] if m.role == "user"]
    assert "salutare tuturor" in user_msgs


def test_model_cannot_submit(orchestrator_factory):
    orch, store, model = orchestrator_factory([
        GREET,
        call("submit_application", {"application_id": "APP-1", "idempotency_key": "k"}),
        respond("Nu pot trimite încă."),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("trimite cererea"))

    assert "TOOL_REJECTED submit_application: not_model_callable" in joined(model.calls[-1])
    assert store.get(sid).application.application_id is None


def test_offers_blocked_before_eligibility(orchestrator_factory):
    orch, store, model = orchestrator_factory([
        GREET,
        call("calculate_loan_offer"),
        respond("Mai întâi verificăm eligibilitatea."),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("vreau oferte"))

    assert "TOOL_REJECTED calculate_loan_offer: precondition_failed" in joined(model.calls[-1])
    assert store.get(sid).application.offers is None


def test_invalid_json_retry_then_fallback(orchestrator_factory):
    orch, store, model = orchestrator_factory([GREET, "garbage", "garbage"])
    sid = orch.start_session(CUSTOMER).session_id
    version_before = store.get(sid).version
    count_before = len(store.messages(sid))

    resp = orch.handle(sid, CUSTOMER, CustomerMessage("salut"))

    calls = turn_calls(model, 1)
    assert len(calls) == 2
    assert "INVALID_ACTION" in joined(calls[1])
    assert "Return exactly one JSON object matching the schema." in joined(calls[1])
    assert "INVALID_ACTION" not in joined(calls[0])
    assert resp.messages[0].text == FALLBACK_REPLY["ro"]
    assert store.get(sid).version == version_before
    assert resp.session_version == version_before
    new = store.messages(sid)[count_before:]
    assert [m.role for m in new] == ["customer", "assistant"]


def test_invalid_json_then_valid(orchestrator_factory):
    orch, _, _ = orchestrator_factory([GREET, "garbage", respond("Bine")])
    sid = orch.start_session(CUSTOMER).session_id
    resp = orch.handle(sid, CUSTOMER, CustomerMessage("hello"))
    assert resp.messages[0].text == "Bine"


def test_step_cap(orchestrator_factory):
    orch, _, model = orchestrator_factory([GREET] + [call("get_credit_products", intent="product_info")] * 4)
    sid = orch.start_session(CUSTOMER).session_id
    resp = orch.handle(sid, CUSTOMER, CustomerMessage("I want a loan"))
    assert len(turn_calls(model, 1)) == 4
    assert resp.messages[0].text == FALLBACK_REPLY["en"]


def test_unknown_citations_dropped(orchestrator_factory):
    orch, _, _ = orchestrator_factory([GREET, respond("Răspuns", citations=["c9"])])
    sid = orch.start_session(CUSTOMER).session_id
    resp = orch.handle(sid, CUSTOMER, CustomerMessage("întrebare"))
    assert resp.messages[0].citations == []


def test_known_citations_resolved(orchestrator_factory):
    orch, store, _ = orchestrator_factory([
        GREET,
        call("search_banking_policies", {"text": "early repayment"}, intent="product_info"),
        respond("Poți rambursa anticipat.", intent="product_info", citations=["c1", "c9"]),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    resp = orch.handle(sid, CUSTOMER, CustomerMessage("Pot rambursa anticipat?"))
    state = store.get(sid)
    assert "c1" in state.retrieved_sources
    assert [c.id for c in resp.messages[0].citations] == ["c1"]
    assert resp.messages[0].citations[0] == state.retrieved_sources["c1"]
    assert store.messages(sid)[-1].citations[0].id == "c1"


def test_rejected_field_update_forces_reask(orchestrator_factory):
    orch, store, model = orchestrator_factory([
        GREET,
        respond("Am notat.", intent="credit_application", updates=[{"field": "amount", "value": "500"}]),
        respond("Suma minimă este 1000 lei. Ce sumă dorești?", intent="credit_application"),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    resp = orch.handle(sid, CUSTOMER, CustomerMessage("vreau 500 lei"))

    calls = turn_calls(model, 1)
    assert len(calls) == 2
    assert "FIELD_UPDATES_REJECTED" in joined(calls[1])
    assert "amount" in joined(calls[1])
    assert resp.messages[0].text.startswith("Suma minimă")
    assert len(resp.messages) == 1
    assert "amount" not in store.get(sid).application.fields


def test_updates_without_application_rejected(orchestrator_factory):
    orch, store, model = orchestrator_factory([
        GREET,
        respond("x", intent="product_info", updates=[{"field": "amount", "value": "30000"}]),
        respond("Despre ce produs?", intent="product_info"),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("info"))
    assert store.get(sid).application is None
    assert "no_active_application" in joined(model.calls[-1])


def test_unknown_offer_selection_by_text_rejected(orchestrator_factory):
    orch, store, model = orchestrator_factory([
        GREET,
        respond("Bine", intent="credit_application",
                updates=[{"field": "selected_offer_id", "value": "personal_loan-48m-bogus"}]),
        respond("Nu găsesc această ofertă.", intent="credit_application"),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("o aleg pe cea de 48 luni"))

    assert "unknown_offer" in joined(model.calls[-1])
    assert store.get(sid).application.selected_offer_id is None


def test_side_question_keeps_application(orchestrator_factory):
    orch, store, _ = orchestrator_factory([
        GREET,
        respond("Ce produs?", intent="credit_application", updates=DISCOVERY_UPDATES),
        respond("Rambursarea anticipată este posibilă.", intent="product_info"),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    first = orch.handle(sid, CUSTOMER, CustomerMessage("Vreau un credit"))
    app_before = store.get(sid).application

    second = orch.handle(sid, CUSTOMER, CustomerMessage("Pot rambursa anticipat?"))

    state = store.get(sid)
    assert state.application == app_before
    assert state.active_flow == Flow.credit_application
    assert second.progress.stage == first.progress.stage == "discovery"


def test_full_offer_path_builds_summary(orchestrator_factory, stub_data):
    orch, store, model = orchestrator_factory([
        GREET,
        call("run_eligibility_check"),
        call("calculate_loan_offer", {"term_options_months": [36, 60]}),
        respond("Iată ofertele.", intent="credit_application"),
    ])
    sid = orch.start_session(CUSTOMER).session_id
    seed_application(store, sid, make_verified_app(stub_data.requirements[Product.personal_loan]))

    resp = orch.handle(sid, CUSTOMER, CustomerMessage("Vreau ofertele"))
    app = store.get(sid).application
    assert app.eligibility.result.status == EligibilityStatus.satisfied
    assert app.eligibility.verified_inputs is True
    assert app.eligibility.input_fingerprint == fingerprint(app, eligibility_input_names(app))
    assert len(app.offers.offers) == 3
    assert resp.progress.stage == "offer_selection"
    assert resp.awaiting.kind == "offer_choice"
    types = [b.type for b in resp.blocks]
    assert "eligibility_result" in types and "offers" in types
    assert "application_summary" not in types

    chosen = app.offers.offers[1].offer_id
    model.responses.append(respond("Confirmi?", intent="credit_application",
                                   updates=[{"field": "selected_offer_id", "value": chosen}]))
    resp = orch.handle(sid, CUSTOMER, CustomerMessage("Aleg varianta a doua"))

    app = store.get(sid).application
    assert app.selected_offer_id == chosen
    assert app.draft_application_id is not None
    summary = app.summary
    assert summary.offer.offer_id == chosen
    assert summary.application_id == app.draft_application_id
    assert summary.term_months == app.offers.offers[1].term_months
    payload = json.dumps(summary.model_dump(mode="json", exclude={"summary_version"}),
                         sort_keys=True, separators=(",", ":"))
    assert summary.summary_version == hashlib.sha256(payload.encode()).hexdigest()[:16]
    assert resp.progress.stage == "awaiting_confirmation"
    assert resp.awaiting.kind == "confirmation"
    assert resp.awaiting.summary_version == summary.summary_version
    summary_blocks = [b for b in resp.blocks if b.type == "application_summary"]
    assert summary_blocks[0].summary == summary
    assert app.application_id is None

    # A later turn with nothing changed keeps the same draft and summary.
    model.responses.append(respond("Aștept confirmarea."))
    orch.handle(sid, CUSTOMER, CustomerMessage("ok"))
    again = store.get(sid).application
    assert again.draft_application_id == app.draft_application_id
    assert again.summary.summary_version == summary.summary_version


def test_access_denied_and_busy(orchestrator_factory):
    orch, _, _ = orchestrator_factory([GREET])
    sid = orch.start_session(CUSTOMER).session_id

    with pytest.raises(SessionAccessDenied):
        orch.handle(sid, "cust-002", CustomerMessage("hi"))
    with pytest.raises(SessionAccessDenied):
        orch.view(sid, "cust-002")
    with pytest.raises(SessionNotFound):
        orch.handle("0" * 32, CUSTOMER, CustomerMessage("hi"))

    lock = orch._lock_for(sid)
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(SessionBusy):
            orch.handle(sid, CUSTOMER, CustomerMessage("hi"))
    finally:
        lock.release()


def test_model_unavailable_on_message_saves_nothing(orchestrator_factory):
    orch, store, _ = orchestrator_factory([GREET, "!unavailable"])
    sid = orch.start_session(CUSTOMER).session_id
    state_before = store.get(sid)
    count_before = len(store.messages(sid))

    with pytest.raises(ModelUnavailable):
        orch.handle(sid, CUSTOMER, CustomerMessage("I want a loan"))

    assert store.get(sid) == state_before
    assert len(store.messages(sid)) == count_before
    # The lock is released after the failure.
    assert orch._lock_for(sid).acquire(blocking=False)


def test_model_unavailable_after_tool_saves_nothing(orchestrator_factory):
    orch, store, _ = orchestrator_factory([GREET, call("get_credit_products", intent="product_info"), "!unavailable"])
    sid = orch.start_session(CUSTOMER).session_id
    state_before = store.get(sid)
    with pytest.raises(ModelUnavailable):
        orch.handle(sid, CUSTOMER, CustomerMessage("Ce credite aveți?"))
    assert store.get(sid) == state_before


@pytest.mark.parametrize("text,previous,expected", [
    ("I want a loan", "ro", "en"),
    ("How much can I borrow?", "ro", "en"),
    ("Vreau un credit", "en", "ro"),
    ("Cât costă?", "en", "ro"),
    ("da", "en", "ro"),
    ("împrumut", "en", "ro"),
    ("ok", "en", "en"),
    ("ok", "ro", "ro"),
    ("Danemarca", "en", "en"),
    ("I want a 30000 lei loan", "ro", "en"),
    ("Yes, I can pay 2000 lei per month, how?", "ro", "en"),
    ("Vreau un credit", "en", "ro"),
    ("Vreau un loan de 30000 lei", "en", "ro"),
])
def test_language_detection(text, previous, expected):
    assert detect_language(text, previous) == expected


def test_language_detected_per_message(orchestrator_factory):
    orch, store, _ = orchestrator_factory([GREET, respond("Sure"), respond("Sigur")])
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("I want a loan"))
    assert store.get(sid).language == "en"
    orch.handle(sid, CUSTOMER, CustomerMessage("Vreau un credit"))
    assert store.get(sid).language == "ro"


def test_view_returns_chat_messages_and_latest(orchestrator_factory):
    orch, store, _ = orchestrator_factory([GREET, call("get_credit_products", intent="product_info"), respond("Avem")])
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("Ce credite aveți?"))

    view = orch.view(sid, CUSTOMER)
    assert [m.role for m in view.messages] == ["assistant", "customer", "assistant"]
    assert view.latest.messages == []
    assert view.latest.session_version == store.get(sid).version
    assert view.latest.turn_id == store.messages(sid)[-1].turn_id
    assert view.latest.progress.flow == "product_info"


def test_step_logging(orchestrator_factory, caplog):
    orch, _, _ = orchestrator_factory([GREET, call("get_credit_products", intent="product_info"), respond("Avem")])
    sid = orch.start_session(CUSTOMER).session_id
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="src.agent.orchestration"):
        orch.handle(sid, CUSTOMER, CustomerMessage("Ce credite aveți?"))
    lines = [json.loads(r.getMessage().split(" ", 1)[1]) for r in caplog.records
             if r.name == "src.agent.orchestration" and r.getMessage().startswith("orchestrator_step ")]
    assert [(l["step"], l["action_type"], l["tool"], l["outcome"]) for l in lines] == [
        (1, "call_tool", "get_credit_products", "tool_ok"),
        (2, "respond", None, "responded"),
    ]
    assert all(l["session_id"] == sid and "latency_ms" in l and l["turn_id"] for l in lines)


# ---- blocks / build_turn_response -------------------------------------------

def make_state(app=None, **kw) -> SessionState:
    return SessionState(session_id="s1", customer_id=CUSTOMER, created_at=NOW, updated_at=NOW,
                        application=app, active_flow=Flow.credit_application if app else Flow.none, **kw)


def eligibility(app, status, verified=True):
    return EligibilityRecord(
        result=EligibilityResult(status=status, reasons=[ReasonItem(code="r", message="m")], rule_version="v1"),
        input_fingerprint=fingerprint(app, eligibility_input_names(app)),
        verified_inputs=verified,
    )


def test_blocks_for_document_stage(stub_data):
    app = make_verified_app(stub_data.requirements[Product.personal_loan])
    app.documents = []
    payslip_field = app.fields["monthly_net_income"]
    payslip_field.confirmed = False
    app.eligibility = eligibility(app, EligibilityStatus.satisfied, verified=False)
    state = make_state(app, used_stubs=True)

    resp = build_turn_response(state, [], "t1")

    assert derive_stage(state) == Stage.documents
    assert resp.awaiting.kind == "document"
    assert resp.awaiting.document_types == ["id_card", "payslip", "bank_statement"]
    assert resp.simulated is True
    statuses = {s.stage: s.status for s in resp.progress.steps}
    assert [s.stage for s in resp.progress.steps] == [s.value for s in MAIN_STAGES]
    assert statuses["discovery"] == statuses["collecting_information"] == statuses["eligibility"] == "done"
    assert statuses["documents"] == "current"
    assert statuses["offer_selection"] == statuses["submitted"] == "todo"
    extracted = next(b for b in resp.blocks if b.type == "extracted_fields")
    by_field = {f.field: f for f in extracted.fields}
    assert set(by_field) == {
        "monthly_net_income", "employer_name", "employment_type", "employment_months", "existing_monthly_obligations",
    }
    assert by_field["monthly_net_income"].needs_confirmation is True
    assert by_field["monthly_net_income"].value == "6200"
    assert by_field["employer_name"].needs_confirmation is False
    assert any(b.type == "eligibility_result" for b in resp.blocks)


def test_blocks_side_stage_progress(stub_data):
    app = make_verified_app(stub_data.requirements[Product.personal_loan])
    app.eligibility = eligibility(app, EligibilityStatus.not_satisfied)
    resp = build_turn_response(make_state(app), [], "t1")
    assert resp.progress.stage == "not_eligible"
    steps = [(s.stage, s.status) for s in resp.progress.steps]
    assert steps[:3] == [("discovery", "done"), ("collecting_information", "done"), ("not_eligible", "current")]
    assert all(status == "todo" for _, status in steps[3:])
    assert resp.awaiting.kind == "text"


def test_blocks_no_application():
    resp = build_turn_response(make_state(), [], "t1")
    assert resp.progress.flow == "none"
    assert resp.progress.stage is None
    assert resp.progress.steps == []
    assert resp.blocks == []
    assert resp.simulated is False


def test_blocks_submitted_and_escalation(stub_data):
    from src.agent.orchestration.state import EscalationRecord

    app = make_verified_app(stub_data.requirements[Product.personal_loan])
    app.application_id = "APP-1"
    state = make_state(app, escalation=EscalationRecord(ticket_id="HR-1", reason="r", created_at=NOW))
    resp = build_turn_response(state, [], "t1")
    assert resp.awaiting.kind == "none"
    assert resp.progress.stage == "submitted"
    submitted = next(b for b in resp.blocks if b.type == "application_submitted")
    assert submitted.application_id == "APP-1"
    assert submitted.status == "PENDING_HUMAN_REVIEW"
    escalation = next(b for b in resp.blocks if b.type == "escalation")
    assert escalation.ticket_id == "HR-1"
