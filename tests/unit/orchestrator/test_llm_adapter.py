"""Tests for LLM chat adapter."""
from unittest.mock import Mock
import pytest
import httpx
import openai

from src.core.errors import ConfigurationError, ModelUnavailable
from src.core.settings import OrchestratorSettings
from src.integrations.llm.chat import (
    ChatMessage,
    ChatModel,
    FakeChatModel,
    FeatherlessChatModel,
)


def test_featherless_sends_model_and_json_mode():
    """FeatherlessChatModel sends correct model name and response_format."""
    settings = OrchestratorSettings(
        featherless_api_key="test-key",
        model="openai/gpt-oss-120b",
        json_mode=True,
        temperature=0.2,
        request_timeout_s=60.0
    )

    # Create mock client
    mock_client = Mock()
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message = Mock()
    mock_response.choices[0].message.content = "test response"
    mock_client.chat.completions.create.return_value = mock_response

    # Create model and call
    model = FeatherlessChatModel(settings, client=mock_client)
    messages = [ChatMessage(role="user", content="hello")]
    result = model.complete(messages)

    assert result == "test response"
    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs

    assert call_kwargs["model"] == "openai/gpt-oss-120b"
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["timeout"] == 60.0
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert len(call_kwargs["messages"]) == 1
    assert call_kwargs["messages"][0]["role"] == "user"
    assert call_kwargs["messages"][0]["content"] == "hello"


def test_featherless_omits_response_format_when_disabled():
    """FeatherlessChatModel omits response_format when json_mode is False."""
    settings = OrchestratorSettings(
        featherless_api_key="test-key",
        json_mode=False
    )

    mock_client = Mock()
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message = Mock()
    mock_response.choices[0].message.content = "test"
    mock_client.chat.completions.create.return_value = mock_response

    model = FeatherlessChatModel(settings, client=mock_client)
    messages = [ChatMessage(role="user", content="hello")]
    model.complete(messages)

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert "response_format" not in call_kwargs


def test_featherless_maps_timeout_to_model_unavailable():
    """FeatherlessChatModel retries timeout once, then raises ModelUnavailable."""
    settings = OrchestratorSettings(featherless_api_key="test-key")

    mock_client = Mock()
    # Create a proper httpx.Request for the APITimeoutError
    request = httpx.Request("POST", "https://api.featherless.ai/v1/chat/completions")
    mock_client.chat.completions.create.side_effect = openai.APITimeoutError(request=request)

    model = FeatherlessChatModel(settings, client=mock_client)
    messages = [ChatMessage(role="user", content="hello")]

    with pytest.raises(ModelUnavailable):
        model.complete(messages)

    # Should be called twice (initial + 1 retry)
    assert mock_client.chat.completions.create.call_count == 2


def test_featherless_maps_connection_error():
    """FeatherlessChatModel retries connection errors once, then raises ModelUnavailable."""
    settings = OrchestratorSettings(featherless_api_key="test-key")

    mock_client = Mock()
    request = httpx.Request("POST", "https://api.featherless.ai/v1/chat/completions")
    mock_client.chat.completions.create.side_effect = openai.APIConnectionError(request=request)

    model = FeatherlessChatModel(settings, client=mock_client)
    messages = [ChatMessage(role="user", content="hello")]

    with pytest.raises(ModelUnavailable):
        model.complete(messages)

    assert mock_client.chat.completions.create.call_count == 2


def test_featherless_maps_rate_limit():
    """FeatherlessChatModel maps RateLimitError to ModelUnavailable without retry."""
    settings = OrchestratorSettings(featherless_api_key="test-key")

    mock_client = Mock()
    response = Mock()
    response.status_code = 429
    request = httpx.Request("POST", "https://api.featherless.ai/v1/chat/completions")
    mock_client.chat.completions.create.side_effect = openai.RateLimitError(
        "rate limit", response=response, body=None
    )

    model = FeatherlessChatModel(settings, client=mock_client)
    messages = [ChatMessage(role="user", content="hello")]

    with pytest.raises(ModelUnavailable):
        model.complete(messages)

    # Rate limits are not retried
    assert mock_client.chat.completions.create.call_count == 1


def test_featherless_maps_5xx_errors():
    """FeatherlessChatModel maps 5xx errors to ModelUnavailable."""
    settings = OrchestratorSettings(featherless_api_key="test-key")

    mock_client = Mock()
    response = Mock()
    response.status_code = 503
    request = httpx.Request("POST", "https://api.featherless.ai/v1/chat/completions")
    mock_client.chat.completions.create.side_effect = openai.APIStatusError(
        "service unavailable", response=response, body=None
    )

    model = FeatherlessChatModel(settings, client=mock_client)
    messages = [ChatMessage(role="user", content="hello")]

    with pytest.raises(ModelUnavailable):
        model.complete(messages)


def test_featherless_maps_4xx_errors():
    """FeatherlessChatModel maps other 4xx errors to ModelUnavailable and logs."""
    settings = OrchestratorSettings(featherless_api_key="test-key")

    mock_client = Mock()
    response = Mock()
    response.status_code = 400
    request = httpx.Request("POST", "https://api.featherless.ai/v1/chat/completions")
    mock_client.chat.completions.create.side_effect = openai.APIStatusError(
        "bad request", response=response, body=None
    )

    model = FeatherlessChatModel(settings, client=mock_client)
    messages = [ChatMessage(role="user", content="hello")]

    with pytest.raises(ModelUnavailable) as exc_info:
        model.complete(messages)

    # Should include the original message
    assert "bad request" in str(exc_info.value)


def test_featherless_requires_key():
    """FeatherlessChatModel raises ConfigurationError when API key is missing."""
    settings = OrchestratorSettings(featherless_api_key=None)

    with pytest.raises(ConfigurationError) as exc_info:
        FeatherlessChatModel(settings)

    assert "API key" in str(exc_info.value)


def test_featherless_handles_empty_content():
    """FeatherlessChatModel returns empty string when content is None."""
    settings = OrchestratorSettings(featherless_api_key="test-key")

    mock_client = Mock()
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message = Mock()
    mock_response.choices[0].message.content = None
    mock_client.chat.completions.create.return_value = mock_response

    model = FeatherlessChatModel(settings, client=mock_client)
    messages = [ChatMessage(role="user", content="hello")]
    result = model.complete(messages)

    assert result == ""


def test_featherless_sets_last_usage():
    """complete() keeps the last response's token usage; None when absent."""
    settings = OrchestratorSettings(featherless_api_key="test-key")
    with_usage = Mock()
    with_usage.choices = [Mock()]
    with_usage.choices[0].message.content = "a"
    with_usage.usage = Mock(prompt_tokens=120, completion_tokens=30, total_tokens=150)
    without_usage = Mock()
    without_usage.choices = [Mock()]
    without_usage.choices[0].message.content = "b"
    without_usage.usage = None
    mock_client = Mock()
    mock_client.chat.completions.create.side_effect = [with_usage, without_usage]

    model = FeatherlessChatModel(settings, client=mock_client)
    assert model.last_usage is None
    model.complete([ChatMessage(role="user", content="hello")])
    assert model.last_usage == {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
    model.complete([ChatMessage(role="user", content="again")])
    assert model.last_usage is None


def test_fake_model_list_responses():
    """FakeChatModel returns responses from list in order."""
    fake = FakeChatModel(responses=["first", "second", "third"])

    messages = [ChatMessage(role="user", content="test")]
    assert fake.complete(messages) == "first"
    assert fake.complete(messages) == "second"
    assert fake.complete(messages) == "third"

    # Check that calls were recorded
    assert len(fake.calls) == 3
    assert all(len(call) == 1 and call[0].content == "test" for call in fake.calls)


def test_fake_model_callable_response():
    """FakeChatModel can use a callable to generate responses."""
    def responder(messages):
        return f"You said: {messages[-1].content}"

    fake = FakeChatModel(responses=responder)

    messages = [ChatMessage(role="user", content="hello")]
    assert fake.complete(messages) == "You said: hello"

    messages2 = [ChatMessage(role="user", content="goodbye")]
    assert fake.complete(messages2) == "You said: goodbye"


def test_fake_model_exhausted_list_raises():
    """FakeChatModel raises AssertionError when responses are exhausted."""
    fake = FakeChatModel(responses=["only one"])

    messages = [ChatMessage(role="user", content="test")]
    fake.complete(messages)

    with pytest.raises(AssertionError):
        fake.complete(messages)


def test_fake_model_unavailable_marker():
    """FakeChatModel raises ModelUnavailable for '!unavailable' response."""
    fake = FakeChatModel(responses=["!unavailable"])

    messages = [ChatMessage(role="user", content="test")]
    with pytest.raises(ModelUnavailable):
        fake.complete(messages)
