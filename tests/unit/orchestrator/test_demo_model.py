"""Unit tests for the deterministic demo model (mock mode)."""
import json

from src.agent.orchestration.actions import CallTool, Respond, parse_model_output
from src.agent.orchestration.demo_model import DemoChatModel
from src.integrations.llm.chat import ChatMessage


def context(**overrides) -> ChatMessage:
    ctx = {
        "language": "ro", "flow": "credit_application", "stage": "collecting_information", "needs": [],
        "fields": {}, "conflicts": [], "documents": [], "eligibility": None, "offers": [], "notices": [],
    }
    ctx.update(overrides)
    return ChatMessage(role="system", content="CONTEXT_JSON:\n" + json.dumps(ctx))


def need(kind, target=None, label=None, field_type=None, detail=None, options=None) -> dict:
    return {"kind": kind, "target": target, "detail": detail, "label": label or kind,
            "field_type": field_type, "options": options}


def run(*messages: ChatMessage):
    return parse_model_output(DemoChatModel().complete(list(messages)))


def test_same_input_same_output():
    messages = [ChatMessage(role="user", content="30000 lei"),
                context(needs=[need("missing_field", "amount", "Amount", "money")])]
    model = DemoChatModel()
    assert model.complete(messages) == model.complete(messages)


def test_enum_prefers_longest_option():
    action = run(ChatMessage(role="user", content="sunt self-employed"),
                 context(needs=[need("missing_field", "employment_type", "Employment Type", "enum",
                                       options=["employed", "self_employed", "retired"])]))
    assert [(u.field, u.value) for u in action.field_updates] == [("employment_type", "self_employed")]


def test_enum_options_come_from_context():
    action = run(ChatMessage(role="user", content="employed"),
                 context(needs=[need("missing_field", "employment_type", "Employment Type", "enum", options=["retired"])]))
    assert action.field_updates == []
    assert isinstance(action.action, Respond) and "retired" in action.action.message


def test_invalid_value_is_not_proposed():
    action = run(ChatMessage(role="user", content="50 lei"),
                 context(needs=[need("missing_field", "amount", "Amount", "money")]))
    assert action.field_updates == []
    assert isinstance(action.action, Respond) and "Amount" in action.action.message


def test_offer_summary_uses_context_values_only():
    offers = [{"offer_id": "o1", "term_months": 60, "monthly_installment": "630.06", "total_cost": "7803.60"}]
    action = run(
        ChatMessage(role="user", content="da"),
        ChatMessage(role="assistant", content="{}"),
        ChatMessage(role="user", content='TOOL_RESULT calculate_loan_offer: {"offers":[]}'),
        context(stage="offer_selection", needs=[need("choose_offer")], offers=offers),
    )
    assert isinstance(action.action, Respond)
    assert "630.06" in action.action.message and "7803.60" in action.action.message
    assert "simulate, pe baza condițiilor publice" in action.action.message


def test_tool_need_is_called_once_per_turn():
    first = run(ChatMessage(role="user", content="ok"),
                context(stage="eligibility", needs=[need("run_eligibility")]))
    assert isinstance(first.action, CallTool) and first.action.tool == "run_eligibility_check"
    again = run(ChatMessage(role="user", content="ok"),
                ChatMessage(role="assistant", content="{}"),
                ChatMessage(role="user", content="TOOL_REJECTED run_eligibility_check: precondition_failed: x"),
                context(stage="eligibility", needs=[need("run_eligibility")]))
    assert isinstance(again.action, Respond)


def test_pricing_disclosures_and_invalid_results_are_not_hidden():
    assumptions = ["DAE/APR: 9.58%", "Net amount paid out: 29800.00 RON", "Not an approval."]
    action = run(
        ChatMessage(role="user", content="offers"),
        ChatMessage(role="assistant", content="{}"),
        ChatMessage(role="user", content='TOOL_RESULT calculate_loan_offer: {"status":"ok","offers":[{}]}'),
        context(stage="offer_selection", needs=[need("choose_offer")], offers=[{
            "offer_id": "priced", "term_months": 60, "monthly_installment": "621.22", "total_cost": "7473.16",
            "assumptions": assumptions,
        }]),
    )
    assert all(text in action.action.message for text in assumptions)
    invalid = run(
        ChatMessage(role="user", content="offers"),
        ChatMessage(role="assistant", content="{}"),
        ChatMessage(role="user", content='TOOL_RESULT calculate_loan_offer: {"status":"invalid","offers":[],"errors":[{"code":"TERM_OUT_OF_RANGE","message":"Term must be 18-60 months"}]}'),
        context(stage="offer_selection", needs=[need("run_offers")]),
    )
    assert isinstance(invalid.action, Respond)
    assert "TERM_OUT_OF_RANGE" in invalid.action.message
