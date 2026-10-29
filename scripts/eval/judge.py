"""Wording judge: grades agent replies against a general and a scenario rubric."""
import json

from pydantic import BaseModel, ConfigDict, Field

from scripts.eval.models import complete_json
from src.integrations.llm.chat import ChatMessage, ChatModel


GENERAL_RUBRIC: list[str] = [
    "Asks at most two things at once.",
    "Does not re-ask information the customer already gave.",
    "Uses clear, plain English.",
    "Invents no numbers or promises: amounts, rates and decisions come only from tool results in the transcript.",
]


class Grade(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    pass_: bool = Field(alias="pass")
    reason: str


class ReplyGrades(BaseModel):
    turn: int
    scores: dict[str, Grade]


class JudgeResult(BaseModel):
    replies: list[ReplyGrades]
    scenario: dict[str, Grade]


SYSTEM_PROMPT = """You are a strict reviewer of a bank loan assistant's replies to a customer.

For every agent reply, grade each general criterion:
{general}

Then grade the whole conversation once against each scenario criterion:
{scenario}

Each turn shows what the agent was waiting for before the reply and the tool results available to it. Numbers, rates and decisions are only allowed if they come from those tool results.

Respond with exactly one JSON object and nothing else:
{{"replies": [{{"turn": <turn number>, "scores": {{"<general criterion>": {{"pass": true|false, "reason": "<short reason>"}}}}}}],
 "scenario": {{"<scenario criterion>": {{"pass": true|false, "reason": "<short reason>"}}}}}}
Use the criteria texts exactly as given as keys."""


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- (none)"


def _messages(transcript: list[dict], scenario_rubric: list[str]) -> list[ChatMessage]:
    system = SYSTEM_PROMPT.format(general=_bullets(GENERAL_RUBRIC), scenario=_bullets(scenario_rubric))
    lines = ["Transcript:"]
    for item in transcript:
        lines.append(f"--- Turn {item['turn']} ---")
        lines.append(f"CUSTOMER: {item.get('customer', '')}")
        lines.append(
            "Agent was waiting for: " + (", ".join(item.get("awaiting_before") or []) or "(nothing)")
        )
        tool_results = item.get("tool_results") or []
        lines.append("Tool results: " + (json.dumps(tool_results, ensure_ascii=False) if tool_results else "(none)"))
        lines.append(f"AGENT: {item.get('agent', '')}")
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content="\n".join(lines)),
    ]


def judge_conversation(model: ChatModel, transcript: list[dict], scenario_rubric: list[str]) -> JudgeResult:
    """Grade a conversation; one retry on invalid JSON, then EvalModelError."""
    return complete_json(model, _messages(transcript, scenario_rubric), JudgeResult.model_validate, "judge")
