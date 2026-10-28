"""Tool registry and validation for the orchestrator."""
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Callable, Literal

from pydantic import BaseModel, ValidationError

from src.agent.orchestration.state import SessionState, Flow
from src.core.errors import ToolUnavailable

logger = logging.getLogger("src.agent.tools")


@dataclass
class ToolContext:
    """Context for tool execution."""
    state: SessionState
    now: datetime


@dataclass(frozen=True)
class ToolSpec:
    """Specification for a tool."""
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    model_callable: bool
    flows: frozenset[Flow]
    handler: Callable[[BaseModel, ToolContext], BaseModel]
    precondition: Callable[[SessionState], str | None] | None = None
    authorization: Literal["customer_owns_session"] = "customer_owns_session"


class ToolErrorCode(StrEnum):
    """Error codes for tool execution failures."""
    unknown_tool = "unknown_tool"
    not_model_callable = "not_model_callable"
    not_allowed_in_flow = "not_allowed_in_flow"
    precondition_failed = "precondition_failed"
    invalid_arguments = "invalid_arguments"
    tool_failed = "tool_failed"
    tool_unavailable = "tool_unavailable"


class ToolCallOutcome(BaseModel):
    """Outcome of a tool call."""
    tool: str
    ok: bool
    output: dict | None
    error_code: ToolErrorCode | None
    error_message: str | None

    def as_message(self) -> str:
        """Format outcome as a message for the model."""
        if self.ok:
            # Compact JSON with no spaces
            output_json = json.dumps(self.output, separators=(',', ':'))
            return f"TOOL_RESULT {self.tool}: {output_json}"
        else:
            return f"TOOL_REJECTED {self.tool}: {self.error_code}: {self.error_message}"


def _allowed_flows(state: SessionState) -> set[Flow]:
    """Flows whose tools the model may use in this state."""
    if state.application is not None:
        return {Flow.credit_application, Flow.product_info}
    if state.active_flow == Flow.none:
        return {Flow.none, Flow.product_info}
    return {state.active_flow}


class ToolRegistry:
    """Registry of available tools with validation."""

    def __init__(self):
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Register a tool spec."""
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        """Get a tool spec by name, or None if not found."""
        return self._specs.get(name)

    def model_tools(self, state: SessionState) -> list[ToolSpec]:
        """Return model-callable tools available for the current state.

        When application is active, include tools from both credit_application
        and product_info flows. Before any flow (none), include none and
        product_info tools, so product questions work from the first message.
        Otherwise, include tools from the active flow.
        """
        allowed_flows = _allowed_flows(state)
        return [
            spec for spec in self._specs.values()
            if spec.model_callable and not allowed_flows.isdisjoint(spec.flows)
        ]

    def execute(
        self,
        name: str,
        raw_args: dict,
        ctx: ToolContext,
        *,
        caller: Literal["model", "code"]
    ) -> tuple[ToolCallOutcome, BaseModel | None]:
        """Execute a tool call with validation.

        Returns the outcome and the typed output (if successful).

        Validation order:
        1. unknown_tool - tool not registered
        2. not_model_callable - model trying to call code-only tool
        3. not_allowed_in_flow - tool not available in current flow
        4. precondition_failed - precondition check failed
        5. invalid_arguments - input validation failed
        6. Handler execution with exception handling
        """
        # 1. Check if tool exists
        spec = self.get(name)
        if spec is None:
            return (
                ToolCallOutcome(
                    tool=name,
                    ok=False,
                    output=None,
                    error_code=ToolErrorCode.unknown_tool,
                    error_message=f"Tool '{name}' not found"
                ),
                None
            )

        # 2. Check if model can call this tool
        if caller == "model" and not spec.model_callable:
            return (
                ToolCallOutcome(
                    tool=name,
                    ok=False,
                    output=None,
                    error_code=ToolErrorCode.not_model_callable,
                    error_message=f"Tool '{name}' is not callable by the model"
                ),
                None
            )

        # 3. Check if tool is allowed in current flow
        if ctx.state.application is not None:
            # When application is active, allow credit_application and product_info flows
            allowed_flows = {Flow.credit_application, Flow.product_info}
            if allowed_flows.isdisjoint(spec.flows):
                return (
                    ToolCallOutcome(
                        tool=name,
                        ok=False,
                        output=None,
                        error_code=ToolErrorCode.not_allowed_in_flow,
                        error_message=f"Tool '{name}' not allowed in current flow '{ctx.state.active_flow}'"
                    ),
                    None
                )
        else:
            # Otherwise, check active flow (flow none also allows product_info tools)
            if _allowed_flows(ctx.state).isdisjoint(spec.flows):
                return (
                    ToolCallOutcome(
                        tool=name,
                        ok=False,
                        output=None,
                        error_code=ToolErrorCode.not_allowed_in_flow,
                        error_message=f"Tool '{name}' not allowed in flow '{ctx.state.active_flow}'"
                    ),
                    None
                )

        # 4. Check precondition
        if spec.precondition is not None:
            reason = spec.precondition(ctx.state)
            if reason is not None:
                return (
                    ToolCallOutcome(
                        tool=name,
                        ok=False,
                        output=None,
                        error_code=ToolErrorCode.precondition_failed,
                        error_message=reason
                    ),
                    None
                )

        # 5. Validate input arguments
        try:
            validated_input = spec.input_model.model_validate(raw_args)
        except ValidationError as e:
            return (
                ToolCallOutcome(
                    tool=name,
                    ok=False,
                    output=None,
                    error_code=ToolErrorCode.invalid_arguments,
                    error_message=str(e)
                ),
                None
            )

        # 6. Execute handler
        try:
            output = spec.handler(validated_input, ctx)
        except ToolUnavailable as e:
            return (
                ToolCallOutcome(
                    tool=name,
                    ok=False,
                    output=None,
                    error_code=ToolErrorCode.tool_unavailable,
                    error_message=str(e)
                ),
                None
            )
        except Exception as e:
            logger.exception(f"Tool '{name}' failed")
            return (
                ToolCallOutcome(
                    tool=name,
                    ok=False,
                    output=None,
                    error_code=ToolErrorCode.tool_failed,
                    error_message=str(e)
                ),
                None
            )

        # Validate output
        try:
            # Ensure output matches the output_model
            if not isinstance(output, spec.output_model):
                raise ValueError(f"Handler returned {type(output).__name__} instead of {spec.output_model.__name__}")

            # Convert to dict for outcome
            output_dict = output.model_dump(mode="json")

            return (
                ToolCallOutcome(
                    tool=name,
                    ok=True,
                    output=output_dict,
                    error_code=None,
                    error_message=None
                ),
                output
            )
        except Exception as e:
            logger.exception(f"Tool '{name}' output validation failed")
            return (
                ToolCallOutcome(
                    tool=name,
                    ok=False,
                    output=None,
                    error_code=ToolErrorCode.tool_failed,
                    error_message=f"Output validation failed: {e}"
                ),
                None
            )
