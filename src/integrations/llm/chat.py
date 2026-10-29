"""LLM chat adapter for Featherless and testing."""
import logging
import threading
from typing import Callable, Literal, Protocol

import openai
from pydantic import BaseModel

from src.core.errors import ConfigurationError, ModelUnavailable
from src.core.settings import OrchestratorSettings


logger = logging.getLogger("src.integrations.llm")


class ThreadLocalUsage:
    """Thread-local storage for token usage with a simple attribute interface.

    Stores usage per thread while exposing it as a single `value` attribute
    that the orchestrator can read with getattr.
    """

    def __init__(self):
        self._local = threading.local()

    @property
    def value(self) -> dict[str, int] | None:
        """Get the usage for the current thread."""
        return getattr(self._local, "usage", None)

    @value.setter
    def value(self, usage: dict[str, int] | None) -> None:
        """Set the usage for the current thread."""
        self._local.usage = usage


class ChatMessage(BaseModel):
    """A single chat message."""
    role: Literal["system", "user", "assistant"]
    content: str


class ChatModel(Protocol):
    """Protocol for chat model implementations."""

    def complete(self, messages: list[ChatMessage]) -> str:
        """Generate a completion for the given messages.

        Args:
            messages: Conversation history

        Returns:
            Model's response text

        Raises:
            ModelUnavailable: Model is unavailable or request failed
        """
        ...


class FeatherlessChatModel:
    """Chat model using Featherless API (OpenAI-compatible)."""

    def __init__(
        self,
        settings: OrchestratorSettings,
        client: openai.OpenAI | None = None
    ):
        """Initialize the Featherless chat model.

        Args:
            settings: Orchestrator settings
            client: Optional OpenAI client (for testing)

        Raises:
            ConfigurationError: If API key is missing
        """
        if settings.featherless_api_key is None:
            raise ConfigurationError("Featherless API key is required")

        self.settings = settings

        if client is None:
            self.client = openai.OpenAI(
                api_key=settings.featherless_api_key.get_secret_value(),
                base_url=settings.featherless_base_url
            )
        else:
            self.client = client
        # Token usage stored per thread, accessed via last_usage attribute
        self._usage_storage = ThreadLocalUsage()

    @property
    def last_usage(self) -> dict[str, int] | None:
        """Get token usage of the last completed request for the current thread."""
        return self._usage_storage.value

    @last_usage.setter
    def last_usage(self, value: dict[str, int] | None) -> None:
        """Set token usage for the current thread."""
        self._usage_storage.value = value

    def complete(self, messages: list[ChatMessage]) -> str:
        """Generate a completion using Featherless API.

        Retries once on timeout and connection errors.
        Maps various API errors to ModelUnavailable.

        Args:
            messages: Conversation history

        Returns:
            Model's response text

        Raises:
            ModelUnavailable: Model is unavailable or request failed
        """
        # Convert to OpenAI format
        openai_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

        # Build kwargs
        kwargs = {
            "model": self.settings.model,
            "messages": openai_messages,
            "temperature": self.settings.temperature,
            "timeout": self.settings.request_timeout_s,
        }

        # Add response_format only if json_mode is enabled
        if self.settings.json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        self.last_usage = None
        # Try with one retry for transient errors
        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(**kwargs)
                self.last_usage = _usage_dict(getattr(response, "usage", None))
                return response.choices[0].message.content or ""

            except (openai.APITimeoutError, openai.APIConnectionError) as e:
                if attempt == 0:
                    # Retry once
                    logger.warning(f"Transient error, retrying: {e}")
                    continue
                else:
                    # Second failure
                    logger.error(f"Model unavailable after retry: {e}")
                    raise ModelUnavailable(f"Model request timed out or connection failed: {e}")

            except openai.RateLimitError as e:
                # Don't retry rate limits
                logger.error(f"Rate limit exceeded: {e}")
                raise ModelUnavailable(f"Model rate limit exceeded: {e}")

            except openai.APIStatusError as e:
                # Map 5xx and other 4xx to ModelUnavailable
                if e.response.status_code >= 500:
                    logger.error(f"Model server error: {e}")
                    raise ModelUnavailable(f"Model server error: {e}")
                else:
                    # Other 4xx errors
                    logger.error(f"Model request failed: {e}")
                    raise ModelUnavailable(f"Model request failed: {e}")

        # Should not reach here
        raise ModelUnavailable("Model request failed")


def _usage_dict(usage) -> dict[str, int] | None:
    """Token counts from an OpenAI-style usage object (None when absent)."""
    if usage is None:
        return None
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


class FakeChatModel:
    """Fake chat model for testing.

    Can return predefined responses or use a callable to generate them.
    """

    def __init__(self, responses: list[str] | Callable[[list[ChatMessage]], str]):
        """Initialize the fake model.

        Args:
            responses: Either a list of responses to return in order,
                      or a callable that takes messages and returns a response
        """
        self.responses = responses
        self.calls: list[list[ChatMessage]] = []
        self._index = 0

    def complete(self, messages: list[ChatMessage]) -> str:
        """Return the next response or call the generator.

        Args:
            messages: Conversation history (recorded but may be ignored)

        Returns:
            Next response

        Raises:
            ModelUnavailable: If response is "!unavailable"
            AssertionError: If response list is exhausted
        """
        # Record the call
        self.calls.append(messages)

        # Get response
        if callable(self.responses):
            response = self.responses(messages)
        else:
            if self._index >= len(self.responses):
                raise AssertionError("FakeChatModel: response list exhausted")
            response = self.responses[self._index]
            self._index += 1

        # Check for unavailable marker
        if response == "!unavailable":
            raise ModelUnavailable("Fake model unavailable")

        return response
