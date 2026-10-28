"""Live smoke test for Featherless API integration.

Skipped unless FEATHERLESS_API_KEY is set in the environment.
"""
import pytest

from src.agent.orchestration.actions import parse_model_output
from src.core.settings import load_orchestrator_settings
from src.integrations.llm.chat import ChatMessage, FeatherlessChatModel


@pytest.mark.live
def test_featherless_api_smoke():
    """Smoke test: send a simple request to Featherless and parse the response.

    This test verifies:
    1. Authentication works
    2. The model returns valid JSON
    3. The response can be parsed into a ModelAction
    """
    # Load settings (will read .env file)
    settings = load_orchestrator_settings()

    # Skip if no API key is configured
    if settings.featherless_api_key is None:
        pytest.skip("FEATHERLESS_API_KEY not set")

    # Create model
    model = FeatherlessChatModel(settings)

    # Send a simple credit request
    messages = [
        ChatMessage(
            role="system",
            content='Return only a JSON object with keys "intent" and "action". '
                    'The intent should be one of: product_info, credit_application, '
                    'application_status, human_help, other, unclear. '
                    'The action must have a "type" field that is either "respond" or "call_tool". '
                    'For respond actions, include a "message" field with your response.'
        ),
        ChatMessage(
            role="user",
            content="Vreau un credit"
        )
    ]

    # Call the API
    response = model.complete(messages)

    # Verify we got a non-empty response
    assert response, "Model returned empty response"

    # Verify we can parse it
    action = parse_model_output(response)

    # Basic validation
    assert action.intent is not None, "Parsed action has no intent"
    assert action.action is not None, "Parsed action has no action"

    print(f"\nLive test passed")
    print(f"  Intent: {action.intent}")
    print(f"  Action type: {action.action.type}")
    if hasattr(action.action, 'message'):
        print(f"  Message preview: {action.action.message[:100]}...")
