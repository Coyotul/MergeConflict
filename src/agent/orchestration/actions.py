"""Model action parsing and validation."""
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.agent.orchestration.fields import FieldUpdate


class Intent(StrEnum):
    """Customer intent classification."""
    product_info = "product_info"
    credit_application = "credit_application"
    application_status = "application_status"
    human_help = "human_help"
    other = "other"
    unclear = "unclear"


class CallTool(BaseModel):
    """Tool call action."""
    type: Literal["call_tool"]
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Respond(BaseModel):
    """Response action."""
    type: Literal["respond"]
    message: str = Field(min_length=1, max_length=4000)
    citation_ids: list[str] = Field(default_factory=list)


class ModelAction(BaseModel):
    """Validated model output containing intent, field updates, and action."""
    model_config = ConfigDict(extra="ignore")

    intent: Intent
    field_updates: list[FieldUpdate] = Field(default_factory=list)
    action: CallTool | Respond = Field(discriminator="type")


class ActionParseError(ValueError):
    """Raised when model output cannot be parsed as a valid action."""
    pass


def parse_model_output(text: str) -> ModelAction:
    """Parse and validate model output JSON.

    Strips code fences and finds the first balanced top-level JSON object.
    Tolerates prefix text (reasoning) and suffix text.

    Args:
        text: Raw model output text

    Returns:
        Validated ModelAction

    Raises:
        ActionParseError: If parsing or validation fails
    """
    if not text or not text.strip():
        raise ActionParseError("Empty output")

    # Strip common markdown code fences
    stripped = text.strip()
    if stripped.startswith("```"):
        # Remove opening fence
        lines = stripped.split("\n", 1)
        if len(lines) > 1:
            stripped = lines[1]
        else:
            stripped = ""

    # Remove closing fence if present
    if stripped.endswith("```"):
        stripped = stripped[:-3].rstrip()

    # Find the first balanced JSON object
    json_obj = _extract_first_json_object(stripped)
    if json_obj is None:
        raise ActionParseError("No valid JSON object found")

    # Parse and validate
    try:
        data = json.loads(json_obj)
    except json.JSONDecodeError as e:
        raise ActionParseError(f"Invalid JSON: {e}")

    if not isinstance(data, dict):
        raise ActionParseError("JSON must be an object")

    # Validate with Pydantic
    try:
        return ModelAction(**data)
    except Exception as e:
        # Convert validation errors to ActionParseError with concise message
        error_msg = str(e)
        # Simplify common Pydantic error messages
        if "validation error" in error_msg.lower():
            # Extract just the field errors
            lines = error_msg.split("\n")
            if len(lines) > 1:
                error_msg = lines[0]
        raise ActionParseError(f"Validation failed: {error_msg}")


def _extract_first_json_object(text: str) -> str | None:
    """Extract the first balanced JSON object from text.

    Performs a string-aware brace scan, ignoring braces inside strings.

    Args:
        text: Text potentially containing JSON

    Returns:
        First balanced JSON object as string, or None if not found
    """
    # Find the first opening brace
    start = -1
    for i, char in enumerate(text):
        if char == "{":
            start = i
            break

    if start == -1:
        return None

    # Track brace depth and string state
    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        char = text[i]

        if escape:
            escape = False
            continue

        if char == "\\":
            escape = True
            continue

        if char == '"' and not escape:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                # Found the closing brace
                return text[start:i+1]

    return None
