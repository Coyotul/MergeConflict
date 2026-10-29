"""Tests for model action parsing."""
import pytest

from src.agent.orchestration.actions import (
    ActionParseError,
    CallTool,
    Intent,
    ModelAction,
    Respond,
    parse_model_output,
)


@pytest.mark.parametrize("text", [
    '{"intent":"other","action":{"type":"respond","message":"hi"}}',
    '```json\n{"intent":"other","action":{"type":"respond","message":"hi"}}\n```',
    'Sure! {"intent":"other","action":{"type":"respond","message":"hi {x}"}} trailing',
    'analysis: thinking...\n{"intent":"other","field_updates":[],"action":{"type":"respond","message":"hi"}}',
])
def test_parse_model_output_variants(text):
    """Parser tolerates various formats: plain JSON, fenced, with prefix/suffix."""
    result = parse_model_output(text)
    assert isinstance(result.action, Respond)
    assert result.action.message == "hi" or result.action.message == "hi {x}"
    assert result.intent in Intent


def test_parse_rejects_garbage_and_bad_type():
    """Parser rejects non-JSON and unknown action types."""
    for bad in ["no json here", '{"intent":"other","action":{"type":"dance"}}', "{"]:
        with pytest.raises(ActionParseError):
            parse_model_output(bad)


def test_call_tool_parsed():
    """Tool name and arguments are preserved."""
    text = '{"intent":"credit_application","action":{"type":"call_tool","tool":"search_banking_policies","arguments":{"text":"credit requirements"}}}'
    result = parse_model_output(text)
    assert isinstance(result.action, CallTool)
    assert result.action.tool == "search_banking_policies"
    assert result.action.arguments == {"text": "credit requirements"}


def test_respond_with_citations():
    """Respond action preserves citation IDs."""
    text = '{"intent":"product_info","action":{"type":"respond","message":"The rate is 5%","citation_ids":["c1","c2"]}}'
    result = parse_model_output(text)
    assert isinstance(result.action, Respond)
    assert result.action.message == "The rate is 5%"
    assert result.action.citation_ids == ["c1", "c2"]


def test_field_updates_parsed():
    """Field updates are preserved in model action."""
    text = '{"intent":"credit_application","field_updates":[{"field":"amount","value":"30000"},{"field":"employer_name","confirm":true}],"action":{"type":"respond","message":"Got it"}}'
    result = parse_model_output(text)
    assert len(result.field_updates) == 2
    assert result.field_updates[0].field == "amount"
    assert result.field_updates[0].value == "30000"
    assert result.field_updates[1].field == "employer_name"
    assert result.field_updates[1].confirm is True


def test_model_action_ignores_extra_fields():
    """Model action ignores unexpected fields (extra='ignore')."""
    text = '{"intent":"other","action":{"type":"respond","message":"hi"},"unexpected":"field","another":123}'
    result = parse_model_output(text)
    assert isinstance(result.action, Respond)
    assert result.intent == Intent.other


def test_all_intent_values_accepted():
    """All defined intent values are accepted."""
    for intent in ["product_info", "credit_application", "application_status", "human_help", "other", "unclear"]:
        text = f'{{"intent":"{intent}","action":{{"type":"respond","message":"test"}}}}'
        result = parse_model_output(text)
        assert result.intent.value == intent


def test_unknown_intent_keeps_the_action_as_other():
    """An invented intent label (e.g. "choose_offer") must not discard a valid reply."""
    text = '{"intent":"choose_offer","action":{"type":"respond","message":"Here are your offers."}}'
    result = parse_model_output(text)
    assert result.intent == Intent.other
    assert result.action.message == "Here are your offers."


@pytest.mark.parametrize("label", ["Credit_Application", "credit application", "credit-application"])
def test_near_miss_intent_is_normalised_not_dropped(label):
    """A near-miss label must still start the credit flow, not fall back to "other"."""
    text = f'{{"intent":"{label}","action":{{"type":"respond","message":"ok"}}}}'
    assert parse_model_output(text).intent == Intent.credit_application


def test_parse_requires_intent():
    """Parser still rejects output without an intent."""
    text = '{"action":{"type":"respond","message":"test"}}'
    with pytest.raises(ActionParseError):
        parse_model_output(text)


def test_parse_requires_action():
    """Parser rejects JSON without action field."""
    text = '{"intent":"other","field_updates":[]}'
    with pytest.raises(ActionParseError):
        parse_model_output(text)


def test_respond_message_length():
    """Respond message must be between 1 and 4000 characters."""
    # Empty message
    text = '{"intent":"other","action":{"type":"respond","message":""}}'
    with pytest.raises(ActionParseError):
        parse_model_output(text)

    # Message at max length (4000 chars) should pass
    long_msg = "a" * 4000
    text = f'{{"intent":"other","action":{{"type":"respond","message":"{long_msg}"}}}}'
    result = parse_model_output(text)
    assert len(result.action.message) == 4000

    # Message over limit
    text = f'{{"intent":"other","action":{{"type":"respond","message":"{"a" * 4001}"}}}}'
    with pytest.raises(ActionParseError):
        parse_model_output(text)
