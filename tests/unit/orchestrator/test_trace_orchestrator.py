"""Orchestrator decision trace: the events of spec §4.1 recorded per turn."""
import itertools
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from src.agent.orchestration.orchestrator import CustomerMessage, OfferSelected
from src.agent.orchestration.prompting import PROMPT_VERSION, load_system_prompt
from src.agent.orchestration.trace import FileTracer, InMemoryTracer, NullTracer
from src.core.errors import ModelUnavailable
from src.integrations.llm.chat import FakeChatModel
from src.models.knowledge import Product
from tests.unit.orchestrator.factories import call, make_verified_app, respond, seed_application

CUSTOMER = "cust-alex-morgan"
GREET = respond("Bună! Cu ce te pot ajuta?")


def counter_ids():
    c = itertools.count(1)
    return lambda: f"{next(c):032x}"


def last_turn(tracer: InMemoryTracer) -> list[dict]:
    turn_id = tracer.events[-1]["turn_id"]
    return [e for e in tracer.events if e["turn_id"] == turn_id]


def types(events) -> list[str]:
    return [e["type"] for e in events]


def of_type(events, kind) -> list[dict]:
    return [e for e in events if e["type"] == kind]


def test_tool_then_reply_event_sequence(orchestrator_factory):
    tracer = InMemoryTracer()
    orch, _, _ = orchestrator_factory([
        GREET,
        call("get_credit_products", intent="product_info"),
        respond("Avem trei produse.", intent="product_info"),
    ], tracer=tracer)
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("Ce credite aveți?"))

    events = last_turn(tracer)
    assert types(events) == [
        "turn_started", "model_call", "action_parsed", "tool_call", "model_call", "action_parsed", "turn_finished",
    ]
    assert all(e["session_id"] == sid for e in events)
    started = events[0]
    assert started["event"] == {"kind": "customer_message", "text": "Ce credite aveți?"}
    assert started["step"] is None and "needs" in started and "state_version" in started
    first_call = events[1]
    assert first_call["step"] == 1
    assert "needs" in first_call["context"] and "tools" in first_call["context"]
    assert first_call["context"]["prompt_version"] == PROMPT_VERSION
    assert first_call["history_messages"] == 3  # event, greeting, customer message
    assert first_call["error"] is None and first_call["usage"] is None
    assert isinstance(first_call["latency_ms"], (int, float))
    assert events[2]["action"] == {"type": "call_tool", "tool": "get_credit_products", "arguments": {}}
    assert events[2]["intent"] == "product_info"
    tool = events[3]
    assert (tool["tool"], tool["caller"], tool["ok"], tool["step"]) == ("get_credit_products", "model", True, 1)
    assert tool["error_code"] is None and isinstance(tool["output"], dict)
    assert events[4]["step"] == 2
    assert events[5]["action"]["type"] == "respond"
    finished = events[-1]
    assert finished["outcome"] == "replied"
    assert finished["reply"] == "Avem trei produse."
    assert finished["steps_used"] == 2
    assert finished["citations"] == []
    assert finished["saved"] is True
    assert finished["awaiting_kind"] == "text"
    assert "duration_ms" in finished and "stage_before" in finished and "stage_after" in finished


def test_session_started_has_prompt_once(orchestrator_factory):
    tracer = InMemoryTracer()
    orch, _, _ = orchestrator_factory([GREET, respond("Unu"), respond("Doi")], tracer=tracer)
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("salut"))
    orch.handle(sid, CUSTOMER, CustomerMessage("din nou"))

    started = of_type(tracer.events, "session_started")
    assert len(started) == 1
    assert tracer.events[0]["type"] == "session_started"
    assert started[0]["turn_id"] is None and started[0]["step"] is None
    assert started[0]["prompt_version"] == PROMPT_VERSION
    assert started[0]["system_prompt"] == load_system_prompt()
    assert started[0]["customer_id"] == CUSTOMER
    assert {"model", "temperature", "json_mode", "max_steps", "history_window"} <= started[0].keys()
    assert of_type(tracer.events, "system_prompt_changed") == []
    # greeting turn is traced too
    assert types(tracer.events)[1:5] == ["turn_started", "model_call", "action_parsed", "turn_finished"]
    assert tracer.events[1]["event"] == {"kind": "session_started"}
    assert len(of_type(tracer.events, "turn_finished")) == 3


def test_system_prompt_changed_when_version_differs(orchestrator_factory):
    tracer = InMemoryTracer()
    orch, _, _ = orchestrator_factory([GREET, respond("Unu")], tracer=tracer)
    sid = orch.start_session(CUSTOMER).session_id
    tracer._prompt_versions[sid] = "older-version"
    orch.handle(sid, CUSTOMER, CustomerMessage("salut"))

    events = last_turn(tracer)
    assert types(events)[:3] == ["turn_started", "system_prompt_changed", "model_call"]
    assert events[1]["prompt_version"] == PROMPT_VERSION and events[1]["system_prompt"]


def test_invalid_json_traced_then_fallback(orchestrator_factory):
    tracer = InMemoryTracer()
    orch, _, _ = orchestrator_factory([GREET, "garbage", "garbage"], tracer=tracer)
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("salut"))

    events = last_turn(tracer)
    invalid = of_type(events, "action_invalid")
    assert [e["will_retry"] for e in invalid] == [True, False]
    assert all(e["error"] for e in invalid)
    second_call = of_type(events, "model_call")[1]
    assert any("INVALID_ACTION" in n for n in second_call["notices"])
    assert second_call["raw_output"] == "garbage"
    finished = events[-1]
    assert finished["outcome"] == "fallback"
    assert finished["saved"] is False


def test_step_cap_outcome(orchestrator_factory):
    tracer = InMemoryTracer()
    orch, _, _ = orchestrator_factory(
        [GREET] + [call("get_credit_products", intent="product_info")] * 4, tracer=tracer
    )
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("I want a loan"))
    assert last_turn(tracer)[-1]["outcome"] == "step_cap"
    assert last_turn(tracer)[-1]["steps_used"] == 4


def test_rejected_field_update_traced(orchestrator_factory):
    tracer = InMemoryTracer()
    orch, _, _ = orchestrator_factory([
        GREET,
        respond("Am notat.", intent="credit_application", updates=[{"field": "amount", "value": "500"}]),
        respond("Suma minimă este 1000 lei. Ce sumă dorești?", intent="credit_application"),
    ], tracer=tracer)
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("vreau 500 lei"))

    events = last_turn(tracer)
    updates = of_type(events, "field_updates")
    assert len(updates) == 1  # only the step that proposed updates
    [result] = updates[0]["results"]
    assert result["field"] == "amount" and result["accepted"] is False
    assert result["reason"].startswith("invalid_value")
    assert of_type(events, "action_parsed")[0]["field_updates"] == [{"field": "amount", "value": "500"}]


def test_citations_filtered_traced(orchestrator_factory):
    tracer = InMemoryTracer()
    orch, _, _ = orchestrator_factory([
        GREET,
        call("search_banking_policies", {"text": "early repayment"}, intent="product_info"),
        respond("Poți rambursa anticipat.", intent="product_info", citations=["c1", "c9"]),
    ], tracer=tracer)
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("Pot rambursa anticipat?"))

    events = last_turn(tracer)
    [filtered] = of_type(events, "citations_filtered")
    assert (filtered["kept"], filtered["dropped"]) == (["c1"], ["c9"])
    assert events[-1]["citations"] == ["c1"]


@pytest.fixture
def at_confirmation(orchestrator_factory, stub_data):
    def make(responses=(), tracer=None):
        tracer = tracer or InMemoryTracer()
        orch, store, model = orchestrator_factory([
            GREET,
            call("run_eligibility_check"),
            call("calculate_loan_offer", {"term_options_months": [36, 60]}),
            respond("Iată ofertele.", intent="credit_application"),
            respond("Confirmi?"),
            *responses,
        ], tracer=tracer)
        sid = orch.start_session(CUSTOMER).session_id
        seed_application(store, sid, make_verified_app(stub_data.requirements[Product.personal_loan]))
        orch.handle(sid, CUSTOMER, CustomerMessage("Vreau ofertele"))
        offer = store.get(sid).application.offers.offers[0]
        orch.handle(sid, CUSTOMER, OfferSelected(offer.offer_id))
        version = store.get(sid).application.summary.summary_version
        return orch, store, tracer, sid, version
    return make


def test_offer_selection_traces_code_event(at_confirmation):
    _, _, tracer, _, _ = at_confirmation()
    events = last_turn(tracer)
    assert events[0]["event"]["kind"] == "offer_selected" and events[0]["event"]["offer_id"]
    [event] = of_type(events, "code_event")
    assert (event["kind"], event["outcome"]) == ("offer", "selected")
    code_tools = [e["tool"] for e in of_type(events, "tool_call") if e["caller"] == "code"]
    assert "create_loan_application" in code_tools


def test_model_unavailable_traced(orchestrator_factory):
    tracer = InMemoryTracer()
    orch, _, _ = orchestrator_factory([GREET, "!unavailable"], tracer=tracer)
    sid = orch.start_session(CUSTOMER).session_id
    with pytest.raises(ModelUnavailable):
        orch.handle(sid, CUSTOMER, CustomerMessage("salut"))

    events = last_turn(tracer)
    assert types(events) == ["turn_started", "model_call", "turn_finished"]
    assert events[1]["error"]["code"] == "model_unavailable"
    assert events[1]["error"]["message"]
    assert events[1]["raw_output"] is None
    assert events[-1]["outcome"] == "model_unavailable"
    assert events[-1]["saved"] is False and events[-1]["reply"] is None
    assert events[-1]["error"] == {"type": "ModelUnavailable", "message": "Fake model unavailable"}


def test_turn_finished_error_field(orchestrator_factory):
    tracer = InMemoryTracer()

    def responder(messages):
        if len(responder.calls) == 0:
            responder.calls.append(1)
            return GREET
        raise RuntimeError("boom " + "x" * 2000)
    responder.calls = []

    orch, _, _ = orchestrator_factory(responder, tracer=tracer)
    sid = orch.start_session(CUSTOMER).session_id
    assert of_type(tracer.events, "turn_finished")[0]["error"] is None  # replied
    with pytest.raises(RuntimeError):
        orch.handle(sid, CUSTOMER, CustomerMessage("salut"))

    finished = last_turn(tracer)[-1]
    assert finished["outcome"] == "error"
    assert finished["error"]["type"] == "RuntimeError"
    assert finished["error"]["message"].startswith("boom ") and len(finished["error"]["message"]) == 500


def test_first_parse_failure_on_last_step_does_not_retry(orchestrator_factory):
    tracer = InMemoryTracer()
    orch, _, _ = orchestrator_factory(
        [GREET, call("get_credit_products", intent="product_info"), "garbage"], tracer=tracer, max_steps=2
    )
    sid = orch.start_session(CUSTOMER).session_id
    orch.handle(sid, CUSTOMER, CustomerMessage("salut"))

    events = last_turn(tracer)
    [invalid] = of_type(events, "action_invalid")
    assert (invalid["step"], invalid["will_retry"]) == (2, False)
    assert events[-1]["outcome"] == "step_cap"


class BrokenUsageModel(FakeChatModel):
    @property
    def last_usage(self):
        raise RuntimeError("usage unavailable")


def test_broken_last_usage_does_not_break_turn(orchestrator_factory):
    tracer = InMemoryTracer()
    orch, _, _ = orchestrator_factory([], tracer=tracer)
    orch._model = BrokenUsageModel([GREET, respond("Bine")])
    sid = orch.start_session(CUSTOMER).session_id
    resp = orch.handle(sid, CUSTOMER, CustomerMessage("salut"))

    assert resp.messages[0].text == "Bine"
    assert [e["usage"] for e in of_type(tracer.events, "model_call")] == [None, None]


class ExplodingTracer:
    def record(self, *args, **kwargs):
        raise RuntimeError("disk full")

    def needs_system_prompt(self, *args, **kwargs):
        raise RuntimeError("disk full")


def test_tracer_failure_does_not_break_turn(orchestrator_factory):
    script = [
        GREET,
        call("get_credit_products", intent="product_info"),
        respond("Am notat.", intent="credit_application", updates=[{"field": "amount", "value": "500"}]),
        respond("Ce sumă dorești?", intent="credit_application", citations=["c9"]),
    ]

    def run(tracer):
        orch, _, _ = orchestrator_factory(list(script), tracer=tracer, new_id=counter_ids())
        greeting = orch.start_session(CUSTOMER)
        resp = orch.handle(greeting.session_id, CUSTOMER, CustomerMessage("vreau 500 lei"))
        return [
            (r.messages[0].text, r.progress.stage, [b.model_dump() for b in r.blocks], r.session_version)
            for r in (greeting, resp)
        ]

    assert run(ExplodingTracer()) == run(NullTracer())


@pytest.fixture
def trace_dir():
    path = Path(__file__).parent / ".test_tmp" / uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


