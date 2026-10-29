"""Deterministic trace checks over hand-built events and one recorded demo trace."""
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.eval.checks import CheckResult, load_events, run_check, run_checks

SID = "a" * 32


def ev(type: str, turn: str | None, step: int | None = None, **payload) -> dict:
    return {"ts": "2026-10-28T12:00:00+00:00", "session_id": SID, "turn_id": turn, "step": step,
            "type": type, **payload}


def greeting() -> list[dict]:
    return [
        ev("session_started", None, customer_id="cust-alex-morgan"),
        ev("turn_started", "t0", event={"kind": "session_started"}),
        ev("turn_finished", "t0", outcome="replied", reply="Buna!", citations=[]),
    ]


def say(turn: str, text: str = "hi") -> dict:
    return ev("turn_started", turn, event={"kind": "customer_message", "text": text})


def parsed(turn: str, step: int, intent: str = "credit_application", updates=()) -> dict:
    return ev("action_parsed", turn, step, intent=intent, field_updates=list(updates),
              action={"type": "reply", "message": "ok", "citation_ids": []})


def product(turn: str, step: int, code: str, accepted: bool = True) -> list[dict]:
    return [
        parsed(turn, step, updates=[{"field": "product_code", "value": code}]),
        ev("field_updates", turn, step, results=[
            {"field": "product_code", "accepted": accepted, "reason": None if accepted else "invalid_option"}]),
    ]


def tool(turn: str, step: int | None, name: str, caller: str = "model", ok: bool = True,
         error_code: str | None = None) -> dict:
    return ev("tool_call", turn, step, tool=name, caller=caller, arguments={}, ok=ok,
              error_code=error_code, error_message=None, output=None, duration_ms=1.0)


def finished(turn: str, outcome: str = "replied", reply: str | None = "ok", citations=()) -> dict:
    return ev("turn_finished", turn, outcome=outcome, reply=reply, citations=list(citations))


def check(spec: dict, events: list[dict], **kw) -> CheckResult:
    return run_check(spec, events, **kw)


# ---- intent_seen ---------------------------------------------------------

def test_intent_seen_pass_within_turns():
    events = greeting() + [say("t1"), parsed("t1", 1, "greeting"), finished("t1"),
                           say("t2"), parsed("t2", 1, "credit_application"), finished("t2")]
    r = check({"check": "intent_seen", "intent": "credit_application", "within_turns": 2}, events)
    assert r.status == "pass"
    assert any("turn 2 step 1" in e for e in r.evidence)


def test_intent_seen_fail_outside_window():
    events = greeting() + [say("t1"), parsed("t1", 1, "greeting"), finished("t1"),
                           say("t2"), parsed("t2", 1, "credit_application"), finished("t2")]
    r = check({"check": "intent_seen", "intent": "credit_application", "within_turns": 1}, events)
    assert r.status == "fail"


def test_greeting_turn_not_counted():
    events = greeting()[:2] + [parsed("t0", 1, "credit_application")] + greeting()[2:] + [
        say("t1"), parsed("t1", 1, "greeting"), finished("t1")]
    r = check({"check": "intent_seen", "intent": "credit_application", "within_turns": 1}, events)
    assert r.status == "fail"


# ---- tool_called / tool_not_called --------------------------------------

def test_tool_called_pass():
    events = greeting() + [say("t1"), tool("t1", 1, "run_eligibility_check"), finished("t1")]
    r = check({"check": "tool_called", "tool": "run_eligibility_check"}, events)
    assert r.status == "pass"
    assert r.evidence == ["turn 1 step 1: run_eligibility_check (model) ok"]
    assert r.params == {"tool": "run_eligibility_check", "caller": "model", "min": 1, "max": None}


def test_tool_called_fail_over_max():
    events = greeting() + [say("t1"), tool("t1", 1, "calculate_loan_offer"),
                           tool("t1", 2, "calculate_loan_offer"), finished("t1")]
    r = check({"check": "tool_called", "tool": "calculate_loan_offer", "max": 1}, events)
    assert r.status == "fail"


def test_code_call_does_not_satisfy_model_tool_called():
    events = greeting() + [say("t1"), tool("t1", None, "run_eligibility_check", caller="code"), finished("t1")]
    assert check({"check": "tool_called", "tool": "run_eligibility_check"}, events).status == "fail"
    assert check({"check": "tool_called", "tool": "run_eligibility_check", "caller": "code"},
                 events).status == "pass"


def test_rejected_call_does_not_satisfy_tool_called():
    events = greeting() + [say("t1"), tool("t1", 1, "run_eligibility_check", ok=False,
                                           error_code="precondition_failed"), finished("t1")]
    r = check({"check": "tool_called", "tool": "run_eligibility_check"}, events)
    assert r.status == "fail"
    assert r.evidence == ["turn 1 step 1: run_eligibility_check (model) error precondition_failed"]


def test_tool_not_called_pass():
    events = greeting() + [say("t1"), tool("t1", 1, "search_banking_policies"), finished("t1")]
    assert check({"check": "tool_not_called", "tool": "run_eligibility_check"}, events).status == "pass"


def test_tool_not_called_fail_any_caller():
    events = greeting() + [say("t1"), tool("t1", None, "run_eligibility_check", caller="code"), finished("t1")]
    r = check({"check": "tool_not_called", "tool": "run_eligibility_check"}, events)
    assert r.status == "fail"
    assert r.evidence == ["turn 1: run_eligibility_check (code) ok"]


# ---- tool_order -----------------------------------------------------------

def test_tool_order_pass():
    events = greeting() + [say("t1"), tool("t1", 1, "run_eligibility_check"), finished("t1"),
                           say("t2"), tool("t2", 1, "calculate_loan_offer"), finished("t2")]
    r = check({"check": "tool_order", "before": "run_eligibility_check", "after": "calculate_loan_offer"}, events)
    assert r.status == "pass"


def test_tool_order_fail():
    events = greeting() + [say("t1"), tool("t1", 1, "run_eligibility_check", ok=False, error_code="invalid_arguments"),
                           tool("t1", 2, "calculate_loan_offer"), tool("t1", 3, "run_eligibility_check"),
                           finished("t1")]
    r = check({"check": "tool_order", "before": "run_eligibility_check", "after": "calculate_loan_offer"}, events)
    assert r.status == "fail"


def test_tool_order_without_after_is_not_applicable():
    events = greeting() + [say("t1"), tool("t1", 1, "run_eligibility_check"), finished("t1")]
    r = check({"check": "tool_order", "before": "run_eligibility_check", "after": "calculate_loan_offer"}, events)
    assert r.status == "not_applicable"


# ---- product checks -------------------------------------------------------

def test_tool_before_product_pass():
    events = greeting() + [say("t1"), tool("t1", 1, "search_banking_policies"), *product("t1", 2, "personal_loan"),
                           finished("t1")]
    assert check({"check": "tool_before_product", "tools": ["search_banking_policies"]}, events).status == "pass"


def test_tool_before_product_fail():
    events = greeting() + [say("t1"), *product("t1", 1, "personal_loan"), tool("t1", 2, "search_banking_policies"),
                           finished("t1")]
    assert check({"check": "tool_before_product", "tools": ["search_banking_policies"]}, events).status == "fail"


def test_no_tool_before_product_pass():
    events = greeting() + [say("t1"), *product("t1", 1, "personal_loan"), tool("t1", 2, "calculate_loan_offer"),
                           finished("t1")]
    assert check({"check": "no_tool_before_product", "tool": "calculate_loan_offer"}, events).status == "pass"


def test_no_tool_before_product_fail():
    events = greeting() + [say("t1"), tool("t1", 1, "calculate_loan_offer"), *product("t1", 2, "personal_loan"),
                           finished("t1")]
    r = check({"check": "no_tool_before_product", "tool": "calculate_loan_offer"}, events)
    assert r.status == "fail"
    assert "turn 1 step 1: calculate_loan_offer (model) ok" in r.evidence


def test_clarifying_before_product_pass():
    events = greeting() + [say("t1"), finished("t1", reply="Pentru ce?"),
                           say("t2"), *product("t2", 1, "personal_loan"), finished("t2")]
    assert check({"check": "clarifying_before_product"}, events).status == "pass"


def test_clarifying_before_product_fail():
    events = greeting() + [say("t1"), *product("t1", 1, "personal_loan"), finished("t1")]
    r = check({"check": "clarifying_before_product"}, events)
    assert r.status == "fail"  # the greeting reply does not count
    assert r.params == {"min_replies": 1}


def test_product_final_pass_and_rejected_update_ignored():
    events = greeting() + [say("t1"), *product("t1", 1, "mortgage_casa_ta"), finished("t1"),
                           say("t2"), *product("t2", 1, "nonsense", accepted=False), finished("t2")]
    r = check({"check": "product_final", "product": "mortgage_casa_ta"}, events)
    assert r.status == "pass"


def test_product_final_fail():
    events = greeting() + [say("t1"), *product("t1", 1, "personal_loan"), finished("t1")]
    r = check({"check": "product_final", "products": ["mortgage_casa_ta", "mortgage_noua_casa"]}, events)
    assert r.status == "fail"
    assert any("personal_loan" in e for e in r.evidence)


def test_product_final_without_product_is_not_applicable():
    events = greeting() + [say("t1"), *product("t1", 1, "x", accepted=False), finished("t1")]
    assert check({"check": "product_final", "product": "personal_loan"}, events).status == "not_applicable"


def test_product_value_matched_within_same_step():
    # Other fields accepted in the same step do not count; the product_code result decides.
    events = greeting() + [
        say("t1"),
        parsed("t1", 1, updates=[{"field": "loan_purpose", "value": "car"}, {"field": "product_code", "value": "personal_loan"}]),
        ev("field_updates", "t1", 1, results=[{"field": "product_code", "accepted": False, "reason": "invalid"},
                                               {"field": "loan_purpose", "accepted": True, "reason": None}]),
        finished("t1"),
    ]
    assert check({"check": "product_final", "product": "personal_loan"}, events).status == "not_applicable"


def test_product_changed_pass():
    events = greeting() + [say("t1"), *product("t1", 1, "personal_loan"), finished("t1"),
                           say("t2"), *product("t2", 1, "mortgage_casa_ta"), finished("t2")]
    r = check({"check": "product_changed", "from": "personal_loan", "to": "mortgage_casa_ta"}, events)
    assert r.status == "pass"


def test_product_changed_fail():
    events = greeting() + [say("t1"), *product("t1", 1, "personal_loan"), finished("t1")]
    r = check({"check": "product_changed", "from": "personal_loan", "to": "mortgage_casa_ta"}, events)
    assert r.status == "fail"


# ---- switch ---------------------------------------------------------------

def switch_events(tool_in_window: bool) -> list[dict]:
    window = [tool("t2", 1, "run_eligibility_check")] if tool_in_window else []
    return greeting() + [
        say("t1"), *product("t1", 1, "personal_loan"), tool("t1", 2, "calculate_loan_offer"), finished("t1"),
        say("t2", "de fapt vreau o casa"), *window, finished("t2"),
        say("t3"), *product("t3", 1, "mortgage_casa_ta"), tool("t3", 2, "run_eligibility_check"), finished("t3"),
    ]


TOOLS = ["run_eligibility_check", "calculate_loan_offer"]


def test_no_tool_after_switch_pass():
    r = check({"check": "no_tool_after_switch", "tools": TOOLS}, switch_events(False), switch_turn_ids=["t2"])
    assert r.status == "pass"


def test_no_tool_after_switch_fail():
    r = check({"check": "no_tool_after_switch", "tools": TOOLS}, switch_events(True), switch_turn_ids=["t2"])
    assert r.status == "fail"
    assert r.evidence[-1] == "turn 2 step 1: run_eligibility_check (model) ok"


def test_no_switch_marked_is_not_applicable():
    r = check({"check": "no_tool_after_switch", "tools": TOOLS}, switch_events(True))
    assert r.status == "not_applicable"


# ---- search / citations ---------------------------------------------------

def test_search_per_question_pass():
    events = greeting() + [say("t1"), tool("t1", 1, "search_banking_policies"), finished("t1"),
                           say("t2"), tool("t2", 1, "search_banking_policies"), finished("t2")]
    assert check({"check": "search_per_question", "min": 2}, events).status == "pass"


def test_search_per_question_fail():
    events = greeting() + [say("t1"), tool("t1", 1, "search_banking_policies"),
                           tool("t1", 2, "search_banking_policies", caller="code"), finished("t1")]
    assert check({"check": "search_per_question", "min": 2}, events).status == "fail"


def test_cited_answers_pass():
    events = greeting() + [say("t1"), finished("t1", citations=["c1"]), say("t2"), finished("t2", citations=["c2"])]
    assert check({"check": "cited_answers", "min": 2}, events).status == "pass"


def test_cited_answers_fail():
    events = greeting() + [say("t1"), finished("t1", citations=["c1"]), say("t2"), finished("t2")]
    assert check({"check": "cited_answers", "min": 2}, events).status == "fail"


# ---- rejections / failed turns -------------------------------------------

def test_no_model_tool_rejections_pass():
    events = greeting() + [say("t1"), tool("t1", 1, "run_eligibility_check"),
                           tool("t1", None, "process_document", caller="code", ok=False, error_code="invalid_arguments"),
                           finished("t1")]
    assert check({"check": "no_model_tool_rejections"}, events).status == "pass"


def test_rejections_listed_as_evidence():
    events = greeting() + [say("t1"), tool("t1", 1, "submit_application", ok=False, error_code="not_model_callable"),
                           tool("t1", 2, "calculate_loan_offer", ok=False, error_code="precondition_failed"),
                           finished("t1")]
    r = check({"check": "no_model_tool_rejections"}, events)
    assert r.status == "fail"
    assert r.evidence == ["turn 1 step 1: submit_application (model) error not_model_callable",
                          "turn 1 step 2: calculate_loan_offer (model) error precondition_failed"]


def test_no_failed_turns_pass():
    assert check({"check": "no_failed_turns"}, greeting() + [say("t1"), finished("t1")]).status == "pass"


def test_no_failed_turns_fail():
    events = greeting() + [say("t1"), finished("t1", outcome="model_unavailable", reply=None)]
    r = check({"check": "no_failed_turns"}, events)
    assert r.status == "fail"
    assert r.evidence == ["turn 1: outcome model_unavailable"]


# ---- general --------------------------------------------------------------

ALL_SPECS = [
    {"check": "intent_seen", "intent": "credit_application"},
    {"check": "tool_called", "tool": "run_eligibility_check"},
    {"check": "tool_not_called", "tool": "run_eligibility_check"},
    {"check": "tool_order", "before": "run_eligibility_check", "after": "calculate_loan_offer"},
    {"check": "tool_before_product", "tools": ["search_banking_policies"]},
    {"check": "no_tool_before_product", "tool": "calculate_loan_offer"},
    {"check": "clarifying_before_product"},
    {"check": "product_final", "product": "personal_loan"},
    {"check": "product_changed", "from": "personal_loan", "to": "mortgage_casa_ta"},
    {"check": "no_tool_after_switch", "tools": TOOLS},
    {"check": "search_per_question", "min": 1},
    {"check": "cited_answers", "min": 1},
    {"check": "no_model_tool_rejections"},
    {"check": "no_failed_turns"},
]


def test_empty_events_all_not_applicable():
    results = run_checks(ALL_SPECS, [], switch_turn_ids=["t1"])
    assert [r.check for r in results] == [s["check"] for s in ALL_SPECS]
    assert all(r.status == "not_applicable" and r.evidence == ["no trace"] for r in results)


def test_missing_trace_file_loads_as_empty(work_dir):
    assert load_events(work_dir / "missing.jsonl") == []
    empty = work_dir / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert load_events(empty) == []


def test_unknown_check_raises():
    with pytest.raises(ValueError):
        run_check({"check": "nope"}, greeting())


def test_missing_required_param_raises():
    with pytest.raises(ValueError):
        run_check({"check": "tool_called"}, greeting())


# ---- recorded demo trace --------------------------------------------------

@pytest.fixture
def work_dir():
    path = Path(__file__).parent / ".test_tmp" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_checks_on_recorded_demo_trace(work_dir):
    from fastapi.testclient import TestClient

    from scripts.credit_sources.setup import create_database
    from src.api.app import create_app
    from tests.e2e.test_chat_scenarios import Chat, answer_discovery, block, make_settings

    db = create_database(work_dir / "credit_sources.db")
    settings = make_settings(work_dir, db).model_copy(update={"trace": "file", "traces_dir": work_dir / "traces"})
    app = create_app(settings)
    app.state.orchestrator._clock = lambda: datetime(2026, 10, 28, 12, tzinfo=UTC)
    chat = Chat(TestClient(app), "cust-alex-morgan")
    answer_discovery(chat)
    for text in ("employed", "67", "7000", "FICTIV Employer's Studio 1", "0"):
        chat.say(text)
    for doc_type in ("id_card", "payslip", "bank_statement"):
        chat.upload(doc_type)
    body = chat.say("da")
    body = chat.select_offer(block(body, "offers")["offers"][0]["offer_id"])
    assert body["awaiting"]["kind"] == "confirmation"

    events = load_events(work_dir / "traces" / f"{chat.session_id}.jsonl")
    assert events, "trace file expected"
    results = {r.check: r for r in run_checks(ALL_SPECS, events)}
    assert results["tool_order"].status == "pass", results["tool_order"].evidence
    assert results["no_failed_turns"].status == "pass", results["no_failed_turns"].evidence
    assert results["intent_seen"].status == "pass"
    assert results["product_final"].status == "pass"  # personal_loan, accepted in customer turn 4
    assert results["tool_called"].status == "pass"
    assert results["no_model_tool_rejections"].status == "pass"
    assert results["no_tool_after_switch"].status == "not_applicable"
    json.dumps([r.model_dump() for r in results.values()])  # serialisable for the report
