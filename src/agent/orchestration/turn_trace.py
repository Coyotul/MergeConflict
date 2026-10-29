"""Per-turn decision trace for the orchestrator (observation only).

TurnTrace builds the §4.1 event payloads for one turn and hands them to the
session Tracer. Recording never raises into the turn: every payload build and
write is guarded, so a broken tracer leaves the turn's behaviour unchanged.
Only `execute` lets errors through, and only the tool's own (never tracing's).
"""
import functools
import logging
import time
from typing import Any, Callable

from pydantic import BaseModel

from src.agent.orchestration.actions import ModelAction
from src.agent.orchestration.blocks import build_awaiting
from src.agent.orchestration.events import (
    CustomerMessage,
    DocumentUploaded,
    OfferSelected,
    SessionStarted,
)
from src.agent.orchestration.fields import UpdateResult
from src.agent.orchestration.progress import derive_stage, next_needs
from src.agent.orchestration.prompting import PROMPT_VERSION, load_system_prompt
from src.agent.orchestration.state import SessionState, StoredMessage
from src.agent.orchestration.trace import Tracer, truncate_payload
from src.agent.tools.registry import ToolCallOutcome, ToolContext, ToolRegistry
from src.core.errors import ModelUnavailable
from src.integrations.llm.chat import ChatMessage

logger = logging.getLogger("src.agent.trace")

PAYLOAD_LIMIT = 20000
ERROR_MESSAGE_LIMIT = 500


def _guarded(method: Callable) -> Callable:
    """Run a recording method; log and swallow any failure."""
    @functools.wraps(method)
    def wrapper(self: "TurnTrace", *args, **kwargs) -> None:
        try:
            method(self, *args, **kwargs)
        except Exception as e:
            self._failed(e)
    return wrapper


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _stage(state: SessionState) -> str | None:
    stage = derive_stage(state)
    return stage.value if stage is not None else None


def _bounded(value: Any) -> tuple[Any, bool]:
    """The value itself if its JSON fits the limit, else its truncated JSON text."""
    text, truncated = truncate_payload(value, PAYLOAD_LIMIT)
    return (text if truncated else value), truncated


def _error_info(error: BaseException) -> dict[str, str]:
    """Exception class name and its message (bounded); nothing else from the exception."""
    return {"type": type(error).__name__, "message": str(error)[:ERROR_MESSAGE_LIMIT]}


def describe_event(event: object) -> dict[str, Any]:
    """Event kind plus its safe fields for turn_started.

    Uploads carry doc_type, filename and size only. Document bytes are never
    traced; document ids may still appear in tool_call arguments (process_document).
    """
    if isinstance(event, CustomerMessage):
        return {"kind": "customer_message", "text": event.text}
    if isinstance(event, DocumentUploaded):
        return {"kind": "document_uploaded", "doc_type": event.doc_type,
                "filename": event.filename, "size_bytes": event.size_bytes}
    if isinstance(event, OfferSelected):
        return {"kind": "offer_selected", "offer_id": event.offer_id}
    if isinstance(event, SessionStarted):
        return {"kind": "session_started"}
    return {"kind": type(event).__name__}


def record_session_started(
    tracer: Tracer, state: SessionState, *, model_info: dict[str, Any], max_steps: int, history_window: int
) -> None:
    """Write session_started (with the full system prompt) if the tracer needs it."""
    try:
        if not tracer.needs_system_prompt(state.session_id, PROMPT_VERSION):
            return
        tracer.record(
            state.session_id, None, None, "session_started",
            customer_id=state.customer_id,
            model=model_info.get("model"),
            temperature=model_info.get("temperature"),
            json_mode=model_info.get("json_mode"),
            max_steps=max_steps,
            history_window=history_window,
            prompt_version=PROMPT_VERSION,
            system_prompt=load_system_prompt(),
        )
    except Exception as e:
        logger.warning("trace_failed session_started %s: %s", state.session_id, e)


class TurnTrace:
    """Records one turn's events. `outcome` and `saved` are set by the turn as it runs."""

    def __init__(self, tracer: Tracer, session_id: str, turn_id: str):
        self._tracer = tracer
        self.session_id = session_id
        self.turn_id = turn_id
        # Current model step. Events recorded inside a model step (including code
        # tool calls it triggers) inherit it; before the first step it is None.
        self.step: int | None = None
        self.outcome: str | None = None
        self.saved = False
        self._model_error: ModelUnavailable | None = None
        self._steps_used = 0
        self._stage_before: str | None = None
        self._started = time.perf_counter()
        self._warned = False

    def _record(self, type: str, **payload: Any) -> None:
        self._tracer.record(self.session_id, self.turn_id, self.step, type, **payload)

    def _failed(self, error: Exception) -> None:
        if not self._warned:
            self._warned = True
            logger.warning("trace_failed session=%s turn=%s: %s", self.session_id, self.turn_id, error)

    # ---- turn boundaries --------------------------------------------------

    @_guarded
    def start(self, state: SessionState, event: object) -> None:
        self._stage_before = _stage(state)
        self._record(
            "turn_started",
            event=describe_event(event),
            stage=self._stage_before,
            needs=[{"kind": n.kind.value, "target": n.target} for n in next_needs(state)],
            state_version=state.version,
        )

    @_guarded
    def finish(self, state: SessionState, new_messages: list[StoredMessage], error: BaseException | None) -> None:
        error_info = None
        if error is None:
            outcome = self.outcome or "replied"
            reply = next((m for m in reversed(new_messages) if m.role == "assistant"), None)
        else:
            outcome = "model_unavailable" if isinstance(error, ModelUnavailable) else "error"
            reply = None
            error_info = _error_info(error)
        if outcome == "model_unavailable" and error_info is None and self._model_error is not None:
            error_info = _error_info(self._model_error)  # handled fallback (e.g. _explain)
        try:
            awaiting = build_awaiting(state).kind.value
        except Exception:
            awaiting = None
        self.step = None
        self._record(
            "turn_finished",
            outcome=outcome,
            reply=reply.content if reply is not None else None,
            citations=[c.id for c in reply.citations] if reply is not None else [],
            steps_used=self._steps_used,
            stage_before=self._stage_before,
            stage_after=_stage(state),
            awaiting_kind=awaiting,
            duration_ms=_ms(self._started),
            saved=self.saved,
            error=error_info,
        )

    # ---- model steps ------------------------------------------------------

    @_guarded
    def begin_step(self, step: int) -> None:
        """Mark a model step; re-write the system prompt if its version changed."""
        self.step = step
        self._steps_used = step
        if self._tracer.needs_system_prompt(self.session_id, PROMPT_VERSION):
            self._record("system_prompt_changed", prompt_version=PROMPT_VERSION, system_prompt=load_system_prompt())

    @_guarded
    def model_call(
        self,
        context: dict[str, Any],
        messages: list[ChatMessage],
        notices: list[str],
        started: float,
        usage: dict | None,
        *,
        raw: str | None = None,
        error: ModelUnavailable | None = None,
    ) -> None:
        if error is not None:
            self._model_error = error
        raw_output, truncated = _bounded(raw) if raw is not None else (None, False)
        payload: dict[str, Any] = dict(
            context=context,
            history_messages=max(len(messages) - 2, 0),  # minus system prompt and CONTEXT_JSON
            notices=list(notices),
            latency_ms=_ms(started),
            usage=usage,
            raw_output=raw_output,
            error={"code": "model_unavailable", "message": str(error)[:ERROR_MESSAGE_LIMIT]}
            if error is not None else None,
        )
        if truncated:
            payload["truncated"] = True
        self._record("model_call", **payload)

    @_guarded
    def action_parsed(self, action: ModelAction) -> None:
        self._record(
            "action_parsed",
            intent=action.intent.value,
            field_updates=[u.model_dump(mode="json", exclude_unset=True) for u in action.field_updates],
            action=action.action.model_dump(mode="json"),
        )

    @_guarded
    def action_invalid(self, error: Exception, will_retry: bool) -> None:
        self._record("action_invalid", error=str(error), will_retry=will_retry)

    @_guarded
    def field_updates(self, results: list[UpdateResult]) -> None:
        self._record("field_updates", results=[r.model_dump(mode="json") for r in results])

    @_guarded
    def citations_filtered(self, kept: list[str], dropped: list[str]) -> None:
        self._record("citations_filtered", kept=list(kept), dropped=list(dropped))

    # ---- tools and code-handled events ------------------------------------

    def execute(
        self, registry: ToolRegistry, name: str, arguments: dict, ctx: ToolContext, *, caller: str
    ) -> tuple[ToolCallOutcome, BaseModel | None]:
        """registry.execute, timed and traced as tool_call.

        The event's step is the current model step (code tools synced during a
        step inherit it); code tools run before any model step get step null.
        """
        started = time.perf_counter()
        outcome, output = registry.execute(name, arguments, ctx, caller=caller)
        self._tool_call(name, caller, arguments, outcome, started)
        return outcome, output

    @_guarded
    def _tool_call(self, name: str, caller: str, arguments: dict, outcome: ToolCallOutcome, started: float) -> None:
        output, truncated = _bounded(outcome.output)
        payload: dict[str, Any] = dict(
            tool=name,
            caller=caller,
            arguments=arguments,
            ok=outcome.ok,
            error_code=outcome.error_code.value if outcome.error_code is not None else None,
            error_message=outcome.error_message,
            output=output,
            duration_ms=_ms(started),
        )
        if truncated:
            payload["truncated"] = True
        self._record("tool_call", **payload)

    @_guarded
    def code_event(self, kind: str, outcome: str, **detail: Any) -> None:
        self._record("code_event", kind=kind, outcome=outcome, detail=detail)
