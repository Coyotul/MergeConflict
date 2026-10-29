"""Tests for the simulated customer and the eval model factory."""
import json

import pytest
from pydantic import SecretStr, ValidationError

from scripts.eval.customer import CustomerAction, CustomerView, SimulatedCustomer
from scripts.eval.models import DEFAULT_JUDGE_MODEL, EvalModelError, build_eval_model
from src.core.settings import OrchestratorSettings
from src.integrations.llm.chat import FakeChatModel, FeatherlessChatModel


def _view(**overrides) -> CustomerView:
    data = {
        "transcript": [("agent", "Hello, how can I help?")],
        "awaiting_kind": "fields",
        "document_types": [],
        "offers": [],
        "feedback": None,
    }
    data.update(overrides)
    return CustomerView(**data)


def test_customer_parses_say_with_switch():
    model = FakeChatModel([json.dumps({"type": "say", "text": "Actually, a flat.", "switch": True})])
    action = SimulatedCustomer(model, "brief").next_action(_view())
    assert action.type == "say"
    assert action.text == "Actually, a flat."
    assert action.switch is True


def test_customer_accepts_json_in_code_fence():
    model = FakeChatModel(['```json\n{"type": "done", "reason": "offers shown"}\n```'])
    action = SimulatedCustomer(model, "brief").next_action(_view())
    assert action.type == "done"
    assert action.reason == "offers shown"


def test_customer_retries_once_then_raises():
    model = FakeChatModel(["nope", "nope"])
    with pytest.raises(EvalModelError):
        SimulatedCustomer(model, "brief").next_action(_view())
    assert len(model.calls) == 2
    # The retry tells the model what was wrong.
    assert "invalid" in model.calls[1][-1].content.lower()


def test_customer_retry_recovers():
    model = FakeChatModel(["nope", json.dumps({"type": "say", "text": "Hi"})])
    action = SimulatedCustomer(model, "brief").next_action(_view())
    assert action.text == "Hi"


def test_customer_rejects_upload_without_doc_type():
    with pytest.raises(ValidationError):
        CustomerAction(type="upload")
    with pytest.raises(ValidationError):
        CustomerAction(type="say")
    with pytest.raises(ValidationError):
        CustomerAction(type="choose_offer")
    with pytest.raises(ValidationError):
        CustomerAction(type="done")
    model = FakeChatModel([json.dumps({"type": "upload"}), json.dumps({"type": "dance"})])
    with pytest.raises(EvalModelError):
        SimulatedCustomer(model, "brief").next_action(_view())


def test_customer_prompt_contains_brief_and_awaiting():
    seen = []

    def respond(messages):
        seen.append(messages)
        return json.dumps({"type": "upload", "doc_type": "payslip"})

    model = FakeChatModel(respond)
    view = _view(
        transcript=[("customer", "I want a loan"), ("agent", "Please upload your payslip.")],
        awaiting_kind="documents",
        document_types=["payslip"],
        offers=[{"offer_id": "off-1", "term_months": 48, "monthly_installment": 512.3}],
        feedback="You chose an unknown offer.",
    )
    action = SimulatedCustomer(model, "You are Elena Popa.").next_action(view)
    assert action.doc_type == "payslip"
    text = "\n".join(m.content for m in seen[0])
    assert seen[0][0].role == "system"
    assert "You are Elena Popa." in text
    assert "documents" in text
    assert "payslip" in text
    assert "off-1" in text
    assert "I want a loan" in text
    assert "Please upload your payslip." in text
    assert "You chose an unknown offer." in text
    system = seen[0][0].content
    assert "switch" in system and "JSON" in system and "English" in system


def _settings() -> OrchestratorSettings:
    return OrchestratorSettings(featherless_api_key=SecretStr("k"), model="agent/model")


def test_build_eval_model_judge_default(monkeypatch):
    monkeypatch.delenv("EVAL_JUDGE_MODEL", raising=False)
    judge = build_eval_model("judge", _settings())
    assert judge.settings.model == DEFAULT_JUDGE_MODEL
    assert DEFAULT_JUDGE_MODEL.split("/")[0] != "openai"  # not the agent's family


def test_build_eval_model_judge_and_customer(monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "judge/model")
    monkeypatch.delenv("EVAL_CUSTOMER_MODEL", raising=False)
    base = _settings()
    judge = build_eval_model("judge", base)
    assert isinstance(judge, FeatherlessChatModel)
    assert judge.settings.model == "judge/model"
    assert judge.settings.temperature == 0.0
    assert judge.settings.featherless_api_key.get_secret_value() == "k"
    customer = build_eval_model("customer", base)
    assert customer.settings.model == "agent/model"
    assert customer.settings.temperature == 0.7
    monkeypatch.setenv("EVAL_CUSTOMER_MODEL", "cust/model")
    assert build_eval_model("customer", base).settings.model == "cust/model"
    # The base settings are not mutated.
    assert base.model == "agent/model" and base.temperature == 0.2
