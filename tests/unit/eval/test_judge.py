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


def _by_id(n_general: int, n_scenario: int, *, turns=(1, 2), scenario_pass=True) -> dict:
    return {
        "replies": [{"turn": t, "scores": {f"g{i}": {"pass": True, "reason": "ok"} for i in range(1, n_general + 1)}}
                    for t in turns],
        "scenario": {f"s{i}": {"pass": scenario_pass, "reason": "ok"} for i in range(1, n_scenario + 1)},
    }


def test_judge_keys_results_by_our_criteria_from_ids():
    rubric = ["Explains the outcome.", "Presents the offers."]
    result = judge_conversation(FakeChatModel([json.dumps(_by_id(4, 2))]), TRANSCRIPT, rubric)
    assert list(result.replies[0].scores) == GENERAL_RUBRIC
    assert list(result.scenario) == rubric


def test_judge_maps_echoed_names_by_normalised_match():
    rubric = ["Explains the outcome."]
    out = {
        "replies": [{"turn": t, "scores": {c.rstrip(".").upper() + "  ": {"pass": True, "reason": "ok"}
                                           for c in GENERAL_RUBRIC}} for t in (1, 2)],
        "scenario": {"explains   the outcome": {"pass": False, "reason": "no"}},
    }
    result = judge_conversation(FakeChatModel([json.dumps(out)]), TRANSCRIPT, rubric)
    assert list(result.replies[1].scores) == GENERAL_RUBRIC
    assert list(result.scenario) == rubric


@pytest.mark.parametrize("broken", [
    lambda o: o["scenario"].update({"s9": {"pass": True, "reason": "?"}}),    # unknown criterion
    lambda o: o["scenario"].pop("s1"),                                        # missing scenario criterion
    lambda o: o["replies"][0]["scores"].pop("g2"),                            # missing reply criterion
    lambda o: o["replies"].pop(),                                             # a reply not graded
    lambda o: o["replies"].append({"turn": 7, "scores": o["replies"][0]["scores"]}),  # unknown turn
])
def test_judge_unknown_or_missing_criteria_are_judge_errors(broken):
    out = _by_id(4, 1)
    broken(out)
    model = FakeChatModel([json.dumps(out)] * 2)
    with pytest.raises(EvalModelError):
        judge_conversation(model, TRANSCRIPT, ["Explains the outcome."])
    assert len(model.calls) == 2


def test_judge_scenario_criterion_may_be_not_applicable():
    out = _by_id(4, 1)
    out["scenario"]["s1"] = {"pass": None, "reason": "offers were never shown"}
    result = judge_conversation(FakeChatModel([json.dumps(out)]), TRANSCRIPT, ["Presents the offers."])
    assert result.scenario["Presents the offers."].pass_ is None
    assert result.model_dump(by_alias=True)["scenario"]["Presents the offers."]["pass"] is None


def test_judge_prompt_shows_blocks_and_ids():
    seen = []
    transcript = [dict(TRANSCRIPT[1], blocks=["eligibility_result: eligible",
                                              "offers: 2 offers (48m 512.30 RON/month, 60m 430.10 RON/month)"])]

    def respond(messages):
        seen.append(messages)
        return json.dumps(_by_id(4, 1, turns=(2,)))

    judge_conversation(FakeChatModel(respond), transcript, ["Presents the offers."])
    text = "\n".join(m.content for m in seen[0])
    assert "Shown to the customer: eligibility_result: eligible; offers: 2 offers (48m 512.30 RON/month" in text
    assert "g1: " + GENERAL_RUBRIC[0] in text and "s1: Presents the offers." in text
    assert '"pass": null' in text  # the judge may mark a criterion not applicable


def test_judge_romanian_reply_must_fail_english_criterion():
    seen = []
    transcript = [{"turn": 1, "customer": "I want a loan.", "agent": "Bună ziua! Vă rog să-mi spuneți suma dorită.",
                   "awaiting_before": [], "tool_results": []}]

    def respond(messages):
        seen.append(messages)
        return json.dumps(_by_id(4, 1, turns=(1,)))

    judge_conversation(FakeChatModel(respond), transcript, ["r"])
    english = next(c for c in GENERAL_RUBRIC if "English" in c)
    assert "Romanian" in english and "fails" in english
    text = "\n".join(m.content for m in seen[0])
    assert english in text
    assert "Bună ziua! Vă rog să-mi spuneți suma dorită." in text
