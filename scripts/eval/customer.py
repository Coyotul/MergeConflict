"""Simulated customer: plays a scenario brief and answers with one JSON action."""
import json
import re
from typing import Literal

from pydantic import BaseModel, model_validator

from scripts.eval.models import complete_json
from src.integrations.llm.chat import ChatMessage, ChatModel


_REQUIRED = {"say": "text", "upload": "doc_type", "choose_offer": "offer_id", "done": "reason"}


class CustomerAction(BaseModel):
    type: Literal["say", "upload", "choose_offer", "done"]
    text: str | None = None
    switch: bool = False
    doc_type: str | None = None
    offer_id: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _required_field(self) -> "CustomerAction":
        field = _REQUIRED[self.type]
        value = getattr(self, field)
        if value is None or not str(value).strip():
            raise ValueError(f"action '{self.type}' requires '{field}'")
        return self


_ROMANIAN_LETTERS = set("ăâîșțşţĂÂÎȘȚŞŢ")
# Very common Romanian words that do not occur in English customer messages.
_ROMANIAN_WORDS = re.compile(
    r"\b(vreau|doresc|da|nu|pentru|sunt|este|si|sau|care|multumesc|buna|ziua|imi|meu|mea|"
    r"lunar|luni|venitul|angajatorul|credit pentru|nevoie de)\b",
    re.IGNORECASE,
)


def non_english_reason(text: str) -> str | None:
    """Why `text` looks Romanian rather than English (a simple heuristic), or None."""
    letters = sorted({c for c in text if c in _ROMANIAN_LETTERS})
    if letters:
        return f"Romanian letters {''.join(letters)}"
    words = sorted({m.group(0).lower() for m in _ROMANIAN_WORDS.finditer(text)})
    if words:
        return f"Romanian words {', '.join(words)}"
    return None


def _parse_action(data: object) -> CustomerAction:
    action = CustomerAction.model_validate(data)
    if action.type == "say":
        reason = non_english_reason(action.text)
        if reason:
            raise ValueError(f"the message must be written in English, but it contains {reason}")
    return action


class CustomerView(BaseModel):
    transcript: list[tuple[Literal["customer", "agent"], str]]
    awaiting_kind: str
    document_types: list[str] = []
    offers: list[dict] = []
    feedback: str | None = None


SYSTEM_PROMPT = """You are role-playing a bank customer chatting with a loan assistant. Play the customer described in the brief below.

Rules:
- Answer only what the agent asked. Do not volunteer extra details.
- Facts the brief marks as "only if asked" may be revealed only when the agent asks about them.
- Follow the brief's timed changes (for example a change of mind after a certain point). The message in which you make such a change must have "switch": true; every other message has "switch": false.
- Always write in English, even if the agent writes in Romanian. Messages in Romanian are rejected.
- Respond with exactly one JSON object and nothing else, one of:
  {"type": "say", "text": "<your message>", "switch": false}
  {"type": "upload", "doc_type": "<one of the requested document types>"}
  {"type": "choose_offer", "offer_id": "<one of the listed offer IDs>"}
  {"type": "done", "reason": "<why the conversation is over>"}
- Upload only document types the agent has requested (listed below as requested document types).
- Choose only offer IDs that are listed below.
- Use "done" when the brief's goal has been reached.

Brief:
{brief}"""


class SimulatedCustomer:
    def __init__(self, model: ChatModel, brief: str):
        self.model = model
        self.brief = brief

    def _messages(self, view: CustomerView) -> list[ChatMessage]:
        lines = ["Conversation so far:"]
        if view.transcript:
            for speaker, text in view.transcript:
                lines.append(f"{speaker.upper()}: {text}")
        else:
            lines.append("(nothing yet)")
        lines.append("")
        lines.append(f"The agent is waiting for: {view.awaiting_kind}")
        lines.append(
            "Requested document types: "
            + (", ".join(view.document_types) if view.document_types else "(none)")
        )
        if view.offers:
            lines.append("Offers shown:")
            for offer in view.offers:
                lines.append("- " + json.dumps(offer, ensure_ascii=False))
        else:
            lines.append("Offers shown: (none)")
        if view.feedback:
            lines.append("")
            lines.append(f"Note about your previous action: {view.feedback}")
        lines.append("")
        lines.append("Reply with your next action as one JSON object.")
        return [
            ChatMessage(role="system", content=SYSTEM_PROMPT.replace("{brief}", self.brief)),
            ChatMessage(role="user", content="\n".join(lines)),
        ]

    def next_action(self, view: CustomerView) -> CustomerAction:
        """Next customer action; one retry on invalid output (incl. a non-English message), then EvalModelError."""
        return complete_json(
            self.model, self._messages(view), _parse_action, "simulated customer"
        )
