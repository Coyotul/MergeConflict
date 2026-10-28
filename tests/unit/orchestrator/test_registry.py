"""Tests for the tool registry and validation."""
import json
from datetime import datetime, UTC
from pydantic import BaseModel

import pytest

from src.agent.orchestration.state import SessionState, Flow, ApplicationState
from src.agent.tools.registry import ToolRegistry, ToolSpec, ToolContext, ToolErrorCode
from src.core.errors import ToolUnavailable


# Fake input/output models for tests
class EchoInput(BaseModel):
    message: str


class EchoOutput(BaseModel):
    echoed: str


class FailingInput(BaseModel):
    should_fail: bool = True


class FailingOutput(BaseModel):
    status: str


# Fake handlers
def echo_handler(input: EchoInput, ctx: ToolContext) -> EchoOutput:
    return EchoOutput(echoed=input.message)


def failing_handler(input: FailingInput, ctx: ToolContext) -> FailingOutput:
    raise RuntimeError("Handler failed intentionally")


def unavailable_handler(input: EchoInput, ctx: ToolContext) -> EchoOutput:
    raise ToolUnavailable("Service is down")


def precondition_requires_application(state: SessionState) -> str | None:
    if state.application is None:
        return "Application must be active"
    return None


@pytest.fixture
def registry():
    """Create a fresh registry with test specs."""
    reg = ToolRegistry()

    # Model-callable tool in product_info flow
    reg.register(ToolSpec(
        name="echo",
        description="Echoes the message",
        input_model=EchoInput,
        output_model=EchoOutput,
        model_callable=True,
        flows=frozenset([Flow.product_info]),
        handler=echo_handler
    ))

    # Code-only tool
    reg.register(ToolSpec(
        name="code_only",
        description="Code-only tool",
        input_model=EchoInput,
        output_model=EchoOutput,
        model_callable=False,
        flows=frozenset([Flow.product_info, Flow.credit_application]),
        handler=echo_handler
    ))

    # Tool with precondition
    reg.register(ToolSpec(
        name="needs_application",
        description="Requires application",
        input_model=EchoInput,
        output_model=EchoOutput,
        model_callable=True,
        flows=frozenset([Flow.credit_application]),
        handler=echo_handler,
        precondition=precondition_requires_application
    ))

    # Tool that raises exception
    reg.register(ToolSpec(
        name="failing",
        description="Always fails",
        input_model=FailingInput,
        output_model=FailingOutput,
        model_callable=True,
        flows=frozenset([Flow.product_info]),
        handler=failing_handler
    ))

    # Tool that raises ToolUnavailable
    reg.register(ToolSpec(
        name="unavailable",
        description="Service unavailable",
        input_model=EchoInput,
        output_model=EchoOutput,
        model_callable=True,
        flows=frozenset([Flow.product_info]),
        handler=unavailable_handler
    ))

    # Tool in credit_application flow
    reg.register(ToolSpec(
        name="credit_tool",
        description="Credit application tool",
        input_model=EchoInput,
        output_model=EchoOutput,
        model_callable=True,
        flows=frozenset([Flow.credit_application]),
        handler=echo_handler
    ))

    return reg


@pytest.fixture
def state():
    """Create a test session state."""
    return SessionState(
        session_id="test-session",
        customer_id="test-customer",
        created_at=datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC),
        active_flow=Flow.product_info
    )


@pytest.fixture
def ctx(state):
    """Create a test tool context."""
    return ToolContext(
        state=state,
        now=datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
    )


def test_unknown_tool_rejected(registry, ctx):
    """Unknown tool name returns error without calling handler."""
    outcome, output = registry.execute("nonexistent", {}, ctx, caller="model")

    assert not outcome.ok
    assert outcome.error_code == ToolErrorCode.unknown_tool
    assert "nonexistent" in outcome.error_message
    assert output is None


def test_code_only_tool_rejected_for_model(registry, ctx):
    """Code-only tool rejected when called by model but works for code."""
    # Model call rejected
    outcome, output = registry.execute("code_only", {"message": "test"}, ctx, caller="model")

    assert not outcome.ok
    assert outcome.error_code == ToolErrorCode.not_model_callable
    assert "code_only" in outcome.error_message
    assert output is None

    # Code call works
    outcome, output = registry.execute("code_only", {"message": "test"}, ctx, caller="code")

    assert outcome.ok
    assert output is not None
    assert output.echoed == "test"


def test_flow_restriction(registry, state, ctx):
    """Tool not allowed in current flow returns error."""
    # credit_tool not in product_info flow
    state.active_flow = Flow.product_info

    outcome, output = registry.execute("credit_tool", {"message": "test"}, ctx, caller="model")

    assert not outcome.ok
    assert outcome.error_code == ToolErrorCode.not_allowed_in_flow
    assert "credit_tool" in outcome.error_message
    assert "product_info" in outcome.error_message
    assert output is None

    # But works in credit_application flow
    state.active_flow = Flow.credit_application
    outcome, output = registry.execute("credit_tool", {"message": "test"}, ctx, caller="model")

    assert outcome.ok
    assert output is not None


def test_precondition_reason_returned(registry, state, ctx):
    """Precondition failure returns the reason message."""
    state.active_flow = Flow.credit_application
    state.application = None  # Precondition requires application

    outcome, output = registry.execute("needs_application", {"message": "test"}, ctx, caller="model")

    assert not outcome.ok
    assert outcome.error_code == ToolErrorCode.precondition_failed
    assert outcome.error_message == "Application must be active"
    assert output is None

    # With application it works
    state.application = ApplicationState()
    outcome, output = registry.execute("needs_application", {"message": "test"}, ctx, caller="model")

    assert outcome.ok
    assert output is not None


def test_invalid_arguments(registry, ctx):
    """Invalid input arguments return validation error."""
    # Missing required field
    outcome, output = registry.execute("echo", {}, ctx, caller="model")

    assert not outcome.ok
    assert outcome.error_code == ToolErrorCode.invalid_arguments
    assert "message" in outcome.error_message.lower()
    assert output is None


def test_handler_exception_becomes_tool_failed(registry, ctx):
    """Handler exceptions are caught and returned as tool_failed."""
    outcome, output = registry.execute("failing", {}, ctx, caller="model")

    assert not outcome.ok
    assert outcome.error_code == ToolErrorCode.tool_failed
    assert "Handler failed intentionally" in outcome.error_message
    assert output is None


def test_tool_unavailable_mapped(registry, ctx):
    """ToolUnavailable exception maps to tool_unavailable error code."""
    outcome, output = registry.execute("unavailable", {"message": "test"}, ctx, caller="model")

    assert not outcome.ok
    assert outcome.error_code == ToolErrorCode.tool_unavailable
    assert "Service is down" in outcome.error_message
    assert output is None


def test_as_message_formats(registry, ctx):
    """Outcome.as_message() formats results correctly."""
    # Success case
    outcome, output = registry.execute("echo", {"message": "hello"}, ctx, caller="model")
    message = outcome.as_message()

    assert message.startswith("TOOL_RESULT echo: {")
    parsed = json.loads(message[len("TOOL_RESULT echo: "):])
    assert parsed["echoed"] == "hello"

    # Failure case
    outcome, output = registry.execute("nonexistent", {}, ctx, caller="model")
    message = outcome.as_message()

    assert message.startswith("TOOL_REJECTED nonexistent: unknown_tool:")


def test_model_tools_includes_product_tools_during_application(registry, state):
    """model_tools includes product_info tools when application is active."""
    # Without application, only active_flow tools
    state.active_flow = Flow.product_info
    state.application = None

    tools = registry.model_tools(state)
    tool_names = {spec.name for spec in tools}

    assert "echo" in tool_names
    assert "credit_tool" not in tool_names

    # With application, include both credit_application and product_info tools
    state.application = ApplicationState()

    tools = registry.model_tools(state)
    tool_names = {spec.name for spec in tools}

    # Should include product_info tools
    assert "echo" in tool_names
    # Should include credit_application tools
    assert "credit_tool" in tool_names
    assert "needs_application" in tool_names

    # Code-only tools never included
    assert "code_only" not in tool_names


def test_successful_execution_returns_output(registry, ctx):
    """Successful execution returns both outcome and typed output."""
    outcome, output = registry.execute("echo", {"message": "test"}, ctx, caller="model")

    assert outcome.ok
    assert outcome.error_code is None
    assert outcome.error_message is None
    assert output is not None
    assert isinstance(output, EchoOutput)
    assert output.echoed == "test"

    # Output is in outcome.output as dict
    assert outcome.output is not None
    assert outcome.output["echoed"] == "test"


def test_get_returns_spec_or_none(registry):
    """get() returns spec if registered, None otherwise."""
    spec = registry.get("echo")
    assert spec is not None
    assert spec.name == "echo"

    spec = registry.get("nonexistent")
    assert spec is None


def test_run_eligibility_input_validates_empty_dict():
    """RunEligibilityInput validates empty dict and ignores extra fields."""
    from src.agent.tools.contracts import RunEligibilityInput

    # Empty dict is valid
    input_obj = RunEligibilityInput.model_validate({})
    assert input_obj is not None

    # Extra fields are ignored (Pydantic default behavior)
    input_obj = RunEligibilityInput.model_validate({"extra": "ignored"})
    assert input_obj is not None
