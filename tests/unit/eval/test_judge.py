"""Tests for the wording judge."""
import json

import pytest

from scripts.eval.judge import GENERAL_RUBRIC, JudgeResult, judge_conversation
from scripts.eval.models import EvalModelError
from src.integrations.llm.chat import FakeChatModel


TRANSCRIPT = [
    {
        "turn": 1,
        "customer": "I want a personal loan for a car.",
        "agent": "Sure. How much would you like to borrow, and over how many months?",
        "awaiting_before": [],
        "tool_results": [],
    },
    {
        "turn": 2,
        "customer": "20,000 RON over 48 months.",
        "agent": "You are eligible. Your monthly payment would be 512 RON.",
        "awaiting_before": ["amount", "term_months"],
        "tool_results": ["calculate_loan_offer: monthly_installment=512.30"],
    },
]


def _grades(criteria, ok=True):
    return {c: {"pass": ok, "reason": "because"} for c in criteria}


def _valid_output(scenario_rubric):
    return json.dumps({
        "replies": [
            {"turn": 1, "scores": _grades(GENERAL_RUBRIC)},
            {"turn": 2, "scores": _grades(GENERAL_RUBRIC, ok=False)},
        ],
        "scenario": _grades(scenario_rubric),
    })


def test_general_rubric_has_four_criteria():
    assert len(GENERAL_RUBRIC) == 4


def test_judge_parses_grades():
    rubric = ["Explains the eligibility outcome in plain words."]
    model = FakeChatModel([_valid_output(rubric)])
    result = judge_conversation(model, TRANSCRIPT, rubric)
    assert isinstance(result, JudgeResult)
    assert [r.turn for r in result.replies] == [1, 2]
    assert result.replies[0].scores[GENERAL_RUBRIC[0]].pass_ is True
    assert result.replies[1].scores[GENERAL_RUBRIC[0]].pass_ is False
    assert result.scenario[rubric[0]].reason == "because"
    # Serialises back with the "pass" key.
    dumped = result.model_dump(by_alias=True)
    assert "pass" in dumped["scenario"][rubric[0]]


def test_judge_retry_then_error():
    model = FakeChatModel(["not json", json.dumps({"replies": "x"})])
    with pytest.raises(EvalModelError):
        judge_conversation(model, TRANSCRIPT, ["r"])
    assert len(model.calls) == 2


def test_judge_retry_recovers():
    model = FakeChatModel(["not json", _valid_output(["r"])])
    result = judge_conversation(model, TRANSCRIPT, ["r"])
    assert result.scenario["r"].pass_ is True


def test_judge_prompt_lists_general_and_scenario_rubric():
    seen = []
    rubric = ["Never re-asks the amount.", "Explains the outcome before offers."]

    def respond(messages):
        seen.append(messages)
        return _valid_output(rubric)

    judge_conversation(FakeChatModel(respond), TRANSCRIPT, rubric)
    text = "\n".join(m.content for m in seen[0])
    for criterion in GENERAL_RUBRIC + rubric:
        assert criterion in text
    assert "20,000 RON over 48 months." in text
    assert "term_months" in text
    assert "monthly_installment=512.30" in text
