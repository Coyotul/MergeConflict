"""Model factory and shared JSON handling for the eval customer and judge."""
import json
import os
import re
from typing import Callable, Literal, TypeVar

from pydantic import ValidationError

from src.core.settings import OrchestratorSettings
from src.integrations.llm.chat import ChatMessage, ChatModel, FeatherlessChatModel


T = TypeVar("T")

_TEMPERATURES = {"customer": 0.7, "judge": 0.0}

# A different family from the agent's default (openai/gpt-oss-120b), so the judge does not grade
# its own style. Instruction-tuned, ungated on Featherless, follows the JSON grading format.
DEFAULT_JUDGE_MODEL = "deepseek-ai/DeepSeek-V3-0324"


class EvalModelError(Exception):
    """The simulated customer or the judge produced unusable output."""


def build_eval_model(role: Literal["customer", "judge"], base: OrchestratorSettings) -> ChatModel:
    """Featherless model for the eval role, derived from the agent's settings."""
    if role == "customer":
        model = os.environ.get("EVAL_CUSTOMER_MODEL") or base.model
    elif role == "judge":
        model = os.environ.get("EVAL_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL
    else:
        raise ValueError(f"unknown eval model role: {role}")
    settings = base.model_copy(update={"model": model, "temperature": _TEMPERATURES[role]})
    return FeatherlessChatModel(settings)


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _loads(text: str):
    match = _FENCE.match(text)
    return json.loads(match.group(1) if match else text)


def complete_json(
    model: ChatModel,
    messages: list[ChatMessage],
    parse: Callable[[object], T],
    what: str,
) -> T:
    """Ask for JSON, parse/validate it; one retry with the error, then EvalModelError."""
    messages = list(messages)
    error = ""
    for attempt in range(2):
        raw = model.complete(messages)
        try:
            return parse(_loads(raw))
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            if attempt == 0:
                messages = messages + [
                    ChatMessage(role="assistant", content=raw),
                    ChatMessage(
                        role="user",
                        content=(
                            f"Your previous answer was invalid ({error}). "
                            "Reply again with exactly one JSON object in the required format and nothing else."
                        ),
                    ),
                ]
    raise EvalModelError(f"{what} returned invalid output twice: {error}")
