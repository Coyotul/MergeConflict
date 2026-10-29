"""Wording judge: grades agent replies against a general and a scenario rubric.

Criteria are sent with ids (g1..gN general, s1..sM scenario) and results are keyed by
our own criterion texts. The judge may answer with the ids or echo the names (matched
case-, whitespace- and trailing-punctuation-insensitively); an unknown or missing
criterion, or a reply turn not graded, is invalid output (one retry, then EvalModelError).
`"pass": null` means the criterion's situation never occurred (not applicable).
"""
import json
import re

from pydantic import BaseModel, ConfigDict, Field

from scripts.eval.models import complete_json
from src.integrations.llm.chat import ChatMessage, ChatModel


GENERAL_RUBRIC: list[str] = [
    "Asks no more than two questions in one reply (exactly two is fine; one request to upload the required documents counts as a single request).",
    "Does not re-ask information the customer already gave.",
    "Is written in clear, plain English; a reply in Romanian or any other language fails this criterion.",
    "Invents no numbers or promises: amounts, rates and decisions come only from tool results in the transcript.",
]


class Grade(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    pass_: bool | None = Field(alias="pass")  # None: not applicable
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

Each turn shows what the agent was waiting for before the reply, the tool results available to it, and what was shown to the customer on screen besides the reply text (for example eligibility results or offers). Judge what the customer actually saw: offers shown on screen count as presented. Numbers, rates and decisions are only allowed if they come from those tool results or from what was shown on screen.

The agent must write in English: a reply written in Romanian (or any language other than English) fails the English criterion.

Use "pass": true or false. Use "pass": null only when the criterion's situation never occurred in this conversation (for example offers were never shown), and say so in the reason.

Respond with exactly one JSON object and nothing else, keyed by the criterion ids:
{{"replies": [{{"turn": <turn number>, "scores": {{"g1": {{"pass": true|false|null, "reason": "<short reason>"}}, ...}}}}],
 "scenario": {{"s1": {{"pass": true|false|null, "reason": "<short reason>"}}, ...}}}}
Grade every turn, and every criterion id exactly once."""


def _listing(prefix: str, items: list[str]) -> str:
    return "\n".join(f"- {prefix}{i}: {item}" for i, item in enumerate(items, 1)) if items else "- (none)"


def _messages(transcript: list[dict], scenario_rubric: list[str]) -> list[ChatMessage]:
    system = SYSTEM_PROMPT.format(general=_listing("g", GENERAL_RUBRIC), scenario=_listing("s", scenario_rubric))
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
        lines.append("Shown to the customer: " + ("; ".join(item.get("blocks") or []) or "(nothing)"))
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content="\n".join(lines)),
    ]


def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().rstrip(".!?:;, ").lower()


def _keyed(scores: dict[str, Grade], prefix: str, criteria: list[str], where: str) -> dict[str, Grade]:
    """Map the judge's keys (ids or echoed names) onto our criteria; unknown/missing/duplicate: ValueError."""
    by_key = {f"{prefix}{i}": c for i, c in enumerate(criteria, 1)} | {_normalise(c): c for c in criteria}
    result: dict[str, Grade] = {}
    for key, grade in scores.items():
        criterion = by_key.get(key.strip().lower()) or by_key.get(_normalise(key))
        if criterion is None:
            raise ValueError(f"{where}: unknown criterion {key!r}")
        if criterion in result:
            raise ValueError(f"{where}: criterion {key!r} graded twice")
        result[criterion] = grade
    missing = [f"{prefix}{i}" for i, c in enumerate(criteria, 1) if c not in result]
    if missing:
        raise ValueError(f"{where}: missing criteria {', '.join(missing)}")
    return {c: result[c] for c in criteria}


def _parser(transcript: list[dict], scenario_rubric: list[str]):
    turns = [item["turn"] for item in transcript]

    def parse(data: object) -> JudgeResult:
        raw = JudgeResult.model_validate(data)
        graded = [r.turn for r in raw.replies]
        if sorted(graded) != sorted(turns):
            raise ValueError(f"replies must grade each turn {turns} exactly once, got {graded}")
        replies = [ReplyGrades(turn=r.turn, scores=_keyed(r.scores, "g", GENERAL_RUBRIC, f"turn {r.turn}"))
                   for r in sorted(raw.replies, key=lambda r: r.turn)]
        return JudgeResult(replies=replies, scenario=_keyed(raw.scenario, "s", scenario_rubric, "scenario"))

    return parse


def judge_conversation(model: ChatModel, transcript: list[dict], scenario_rubric: list[str]) -> JudgeResult:
    """Grade a conversation; one retry on invalid output, then EvalModelError."""
    return complete_json(model, _messages(transcript, scenario_rubric), _parser(transcript, scenario_rubric), "judge")
