"""Validate-first orchestrator turn loop.

The model returns one JSON action per step. Code validates intents, field
updates and tool calls before anything happens, executes tools, feeds results
back as messages and builds the TurnResponse purely from state.
"""
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Literal, TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel

from src.agent.orchestration.actions import (
    ActionParseError,
    CallTool,
    Intent,
    ModelAction,
    Respond,
    parse_model_output,
)
from src.agent.orchestration.blocks import all_specs, build_summary, build_turn_response
from src.agent.orchestration.events import (  # noqa: F401  (event types re-exported)
    EVENT_TEXTS,
    CodeEventsMixin,
    ConfirmationDecision,
    CustomerMessage,
    DocumentUploaded,
    OfferSelected,
    SessionStarted,
    TurnEvent,
)
from src.agent.orchestration.fields import (
    FieldUpdate,
    FieldValueError,
    UpdateResult,
    apply_field_updates,
    merge_document_extraction,
    field_type_to_kind,
    parse_field_value,
)
from src.agent.orchestration.progress import (
    NeedKind,
    all_verified,
    eligibility_input_names,
    fingerprint,
    next_needs,
    offer_input_names,
    offers_current,
)
from src.agent.orchestration.prompting import build_context, build_messages
from src.agent.orchestration.state import (
    ApplicationState,
    DocumentStatus,
    EligibilityRecord,
    FieldSource,
    FieldValue,
    Flow,
    OffersRecord,
    SessionState,
    StoredMessage,
)
from src.agent.orchestration.trace import NullTracer, Tracer
from src.agent.orchestration.turn_trace import TurnTrace, record_session_started
from src.agent.tools.contracts import CustomerProfileOutput
from src.agent.tools.registry import ToolCallOutcome, ToolContext, ToolErrorCode, ToolRegistry
from src.core.errors import ModelUnavailable, SessionAccessDenied, SessionBusy
from src.integrations.llm.chat import ChatModel
from src.models.chat import ChatMessageView, CitationRef, SessionView, TurnResponse
from src.models.credit import FieldSpec, FieldType
from src.services.conversations.store import SessionStore

logger = logging.getLogger("src.agent.orchestration")

if TYPE_CHECKING:
    from src.services.document_processing.service import DocumentProcessingService


def utcnow() -> datetime:
    return datetime.now(UTC)


# ---- fixed texts ----------------------------------------------------------

FALLBACK_REPLY = {
    "en": "Sorry, I couldn't process that. Could you rephrase?",
    "ro": "Ne pare rău, nu am putut procesa mesajul. Poți reformula?",
}
FALLBACK_GREETING = (
    "Bună! Sunt asistentul tău pentru credite. Cu ce te pot ajuta?\n"
    "Hi! I'm your credit assistant. How can I help?"
)
INVALID_ACTION_NOTICE = "INVALID_ACTION: {error}. Return exactly one JSON object matching the schema."
SESSION_STARTED_EVENT = "SESSION_STARTED"

# ---- language detection ---------------------------------------------------

_RO_DIACRITICS = re.compile(r"[ăâîșțşţ]", re.IGNORECASE)
_RO_WORDS = re.compile(
    r"\b(?:vreau|credit de|pot|cât|cat|lei|luni|ani|da|nu|bună|buna|sunt|am|un|o|de|pentru|"
    r"este|și|si|meu|mea|venitul|venit|aveți|aveti|cum|ce|mulțumesc|multumesc)\b",
    re.IGNORECASE,
)
_EN_WORDS = re.compile(
    r"\b(?:i want|i|loan|loans|how|what|can|months|month|years|yes|the|my|is|per|pay|want|need|"
    r"please|thanks|hello|hi|income|salary|for|and|of)\b",
    re.IGNORECASE,
)


def detect_language(text: str, previous: Literal["ro", "en"]) -> Literal["ro", "en"]:
    """Count Romanian (keywords + diacritics) vs English keyword matches; higher wins, tie keeps previous."""
    ro = len(_RO_DIACRITICS.findall(text)) + len(_RO_WORDS.findall(text))
    en = len(_EN_WORDS.findall(text))
    if ro > en:
        return "ro"
    if en > ro:
        return "en"
    return previous


# ---- turn -----------------------------------------------------------------

@dataclass
class _Turn:
    """In-flight turn: working state, prior log and this turn's new messages."""
    state: SessionState
    turn_id: str
    ctx: ToolContext
    history: list[StoredMessage]
    trace: TurnTrace
    new_messages: list[StoredMessage] = field(default_factory=list)

    @property
    def transcript(self) -> list[StoredMessage]:
        return self.history + self.new_messages


class Orchestrator(CodeEventsMixin):
    def __init__(
        self,
        store: SessionStore,
        model: ChatModel,
        registry: ToolRegistry,
        catalog_codes: list[str],
        *,
        max_steps: int = 4,
        history_window: int = 30,
        tracer: Tracer = NullTracer(),
        model_info: dict[str, Any] | None = None,
        clock: Callable[[], datetime] = utcnow,
        new_id: Callable[[], str] = lambda: uuid4().hex,
    ):
        self._store = store
        self._model = model
        self._registry = registry
        self._catalog_codes = list(catalog_codes)
        self._tracer = tracer
        # Traced model settings (allow-list: model, temperature, json_mode).
        self._model_info = dict(model_info or {"model": type(model).__name__})
        self._max_steps = max_steps
        self._history_window = history_window
        self._clock = clock
        self._new_id = new_id
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def configure_document_tools(self, service: "DocumentProcessingService", profiles: dict[str, dict]) -> None:
        """Bind the API's upload store, including for an injected test orchestrator."""
        from src.agent.tools.documents import register_document_tools
        register_document_tools(self._registry, service, profiles)

    # ---- public API -------------------------------------------------------

    def start_session(self, customer_id: str) -> TurnResponse:
        """Create a session and greet with one model step (fixed greeting on failure)."""
        now = self._clock()
        state = SessionState(session_id=self._new_id(), customer_id=customer_id, created_at=now, updated_at=now)
        record_session_started(
            self._tracer, state, model_info=self._model_info,
            max_steps=self._max_steps, history_window=self._history_window,
        )
        turn = self._begin_turn(state, SessionStarted(), history=[])
        return self._traced(turn, lambda: self._greet(turn))

    def _greet(self, turn: _Turn) -> TurnResponse:
        state = turn.state
        self._add_message(turn, "event", SESSION_STARTED_EVENT)

        greeting = FALLBACK_GREETING
        started = time.perf_counter()
        action_type, outcome = None, "fallback_greeting"
        turn.trace.outcome = "fallback"
        try:
            action = self._parse(turn, self._complete(turn, 1, [], []), will_retry=False)
            action_type = action.action.type
            if isinstance(action.action, Respond):
                greeting, outcome = action.action.message, "responded"
                turn.trace.outcome = "replied"
        except ModelUnavailable:
            outcome = turn.trace.outcome = "model_unavailable"
        except ActionParseError:
            outcome = "parse_error"
        self._log_step(turn, 1, started, action_type, None, outcome)

        self._add_message(turn, "assistant", greeting)
        self._store.create(state)
        turn.trace.saved = True
        self._store.append_messages(state.session_id, turn.new_messages)
        return build_turn_response(state, turn.new_messages, turn.turn_id)

    def handle(self, session_id: str, customer_id: str, event: TurnEvent) -> TurnResponse:
        """Run one turn. Raises SessionNotFound, SessionAccessDenied, SessionBusy,
        InvalidUpload (DocumentUploaded for a document not requested), and
        ModelUnavailable (CustomerMessage only; nothing is saved then).

        Code-handled events never raise ModelUnavailable: their state is saved
        and a fixed text replaces the model's explanation.
        """
        self._load_owned(session_id, customer_id)
        lock = self._lock_for(session_id)
        if not lock.acquire(blocking=False):
            raise SessionBusy(f"Session {session_id} is busy")
        try:
            state = self._store.get(session_id)
            handler = self._handler_for(event)
            turn = self._begin_turn(state, event)
            return self._traced(turn, lambda: handler(turn, event))
        finally:
            lock.release()

    def _handler_for(self, event: TurnEvent) -> Callable[[_Turn, TurnEvent], TurnResponse]:
        if isinstance(event, CustomerMessage):
            return self._handle_customer_message
        if isinstance(event, DocumentUploaded):
            return self._handle_document_uploaded
        if isinstance(event, OfferSelected):
            return self._handle_offer_selected
        if isinstance(event, ConfirmationDecision):
            return self._handle_confirmation
        if isinstance(event, SessionStarted):
            raise ValueError("SessionStarted is handled by start_session")
        raise TypeError(f"Unknown event {type(event).__name__}")

    def _traced(self, turn: _Turn, run: Callable[[], TurnResponse]) -> TurnResponse:
        """Run a turn; turn_finished is recorded even when it raises (then re-raised unchanged)."""
        error: BaseException | None = None
        try:
            return run()
        except BaseException as e:
            error = e
            raise
        finally:
            turn.trace.finish(turn.state, turn.new_messages, error)

    def view(self, session_id: str, customer_id: str) -> SessionView:
        """Chat messages plus the current response fields.

        latest.turn_id is the turn id of the last logged message (a fresh id
        if the log is empty); latest.messages is empty.
        """
        state = self._load_owned(session_id, customer_id)
        log = self._store.messages(session_id)
        chat = [
            ChatMessageView(role=m.role, text=m.content, citations=m.citations, created_at=m.created_at)
            for m in log
            if m.role in ("customer", "assistant")
        ]
        turn_id = log[-1].turn_id if log else self._new_id()
        return SessionView(
            session_id=state.session_id,
            created_at=state.created_at,
            messages=chat,
            latest=build_turn_response(state, [], turn_id),
        )

    # ---- turn plumbing ----------------------------------------------------

    def _load_owned(self, session_id: str, customer_id: str) -> SessionState:
        state = self._store.get(session_id)
        if state.customer_id != customer_id:
            raise SessionAccessDenied(f"Session {session_id} belongs to another customer")
        return state

    def _lock_for(self, session_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(session_id, threading.Lock())

    def _begin_turn(
        self, state: SessionState, event: TurnEvent, history: list[StoredMessage] | None = None
    ) -> _Turn:
        if history is None:
            history = self._store.messages(state.session_id)
        turn_id = self._new_id()
        trace = TurnTrace(self._tracer, state.session_id, turn_id)
        trace.start(state, event)
        return _Turn(
            state=state,
            turn_id=turn_id,
            ctx=ToolContext(state=state, now=self._clock()),
            history=history,
            trace=trace,
        )

    def _add_message(
        self, turn: _Turn, role: str, content: str, citations: list[CitationRef] | None = None
    ) -> None:
        turn.new_messages.append(StoredMessage(
            message_id=self._new_id(),
            turn_id=turn.turn_id,
            role=role,
            content=content,
            citations=citations or [],
            created_at=self._clock(),
        ))

    def _commit(self, turn: _Turn, loaded: SessionState) -> TurnResponse:
        """Save (only if the state changed), then append this turn's messages.

        An unchanged state is not re-saved, so its version stays the same
        (e.g. a turn that ended in the invalid-output fallback).
        """
        state = turn.state
        saved = state
        if state.model_dump() != loaded.model_dump():
            state.updated_at = self._clock()
            saved = self._store.save(state, expected_version=loaded.version)
            turn.trace.saved = True
        if turn.new_messages:
            self._store.append_messages(state.session_id, turn.new_messages)
        return build_turn_response(saved, turn.new_messages, turn.turn_id)

    def _handle_customer_message(self, turn: _Turn, event: CustomerMessage) -> TurnResponse:
        state = turn.state
        loaded = state.model_copy(deep=True)
        self._add_message(turn, "customer", event.text)
        state.language = detect_language(event.text, state.language)
        self._run_model_steps(turn, [])
        return self._commit(turn, loaded)

    # ---- model loop -------------------------------------------------------

    def _run_model_steps(self, turn: _Turn, notices: list[str], *, fallback: str | None = None) -> bool:
        """Run up to max_steps model calls for this turn.

        `notices` go to the first step only. Returns True when the model gave a
        reply; otherwise appends `fallback` (default: the generic fallback in
        the session language) and returns False. ModelUnavailable propagates
        so the caller decides what to save.
        """
        state = turn.state
        pending = list(notices)
        parse_failed = False
        reasked = False
        self._sync_application(turn)

        no_reply = "step_cap"  # trace outcome when no reply was given
        for step in range(1, self._max_steps + 1):
            started = time.perf_counter()
            try:
                raw = self._complete(turn, step, next_needs(state), pending)
            except ModelUnavailable:
                self._log_step(turn, step, started, None, None, "model_unavailable")
                raise
            pending = []
            try:
                action = self._parse(turn, raw, will_retry=not parse_failed and step < self._max_steps)
            except ActionParseError as e:
                self._log_step(turn, step, started, None, None, "parse_error")
                if parse_failed:
                    no_reply = "fallback"
                    break
                parse_failed = True
                pending.append(INVALID_ACTION_NOTICE.format(error=e))
                continue

            self._route_intent(state, action.intent)
            rejected = self._apply_updates(turn, action.field_updates)
            rejection_notice = _rejection_notice(rejected) if rejected else None

            if isinstance(action.action, CallTool):
                outcome = self._execute_model_tool(turn, action)
                if rejection_notice:
                    pending.append(rejection_notice)
                result = "tool_ok" if outcome.ok else f"tool_rejected:{outcome.error_code}"
                self._log_step(turn, step, started, "call_tool", action.action.tool, result)
                continue

            if rejection_notice and not reasked and step < self._max_steps:
                # The reply was written as if the update stood; make the model re-ask.
                reasked = True
                pending.append(rejection_notice)
                self._log_step(turn, step, started, "respond", None, "reask")
                continue

            self._add_reply(turn, action.action)
            self._log_step(turn, step, started, "respond", None, "responded")
            turn.trace.outcome = "replied"
            return True

        turn.trace.outcome = no_reply
        self._add_message(turn, "assistant", fallback or FALLBACK_REPLY[state.language])
        return False

    def _complete(self, turn: _Turn, step: int, needs: list, notices: list[str]) -> str:
        """Build this step's messages and call the model (traced as model_call)."""
        state = turn.state
        tools = self._registry.model_tools(state)
        context = build_context(state, needs, tools, notices, catalog_codes=self._catalog_codes)
        messages = build_messages(
            state, needs, tools, turn.transcript, self._history_window, notices,
            catalog_codes=self._catalog_codes, context=context,
        )
        turn.trace.begin_step(step)
        started = time.perf_counter()
        try:
            raw = self._model.complete(messages)
        except ModelUnavailable as e:
            turn.trace.model_call(context, messages, notices, started, None, error=e)
            raise
        turn.trace.model_call(context, messages, notices, started, self._last_usage(), raw=raw)
        return raw

    def _last_usage(self) -> dict | None:
        """The model's last token usage, if it exposes one; never raises."""
        try:
            return getattr(self._model, "last_usage", None)
        except Exception:
            return None

    def _parse(self, turn: _Turn, raw: str, *, will_retry: bool) -> ModelAction:
        try:
            action = parse_model_output(raw)
        except ActionParseError as e:
            turn.trace.action_invalid(e, will_retry)
            raise
        turn.trace.action_parsed(action)
        return action

    def _route_intent(self, state: SessionState, intent: Intent) -> None:
        """Start the application on credit intent; never drop an active one."""
        if intent == Intent.credit_application and state.application is None:
            state.application = ApplicationState()
            state.active_flow = Flow.credit_application
        elif intent == Intent.product_info and state.active_flow == Flow.none:
            state.active_flow = Flow.product_info

    def _apply_updates(self, turn: _Turn, updates: list[FieldUpdate]) -> list[UpdateResult]:
        """Validate and apply field updates; return the rejected ones."""
        if not updates:
            return []
        results = self._update_results(turn, updates)
        turn.trace.field_updates(results)
        return [r for r in results if not r.accepted]

    def _update_results(self, turn: _Turn, updates: list[FieldUpdate]) -> list[UpdateResult]:
        app = turn.state.application
        if app is None:
            return [UpdateResult(field=u.field, accepted=False, reason="no_active_application") for u in updates]
        # product_code first: its requirements define the specs the other updates need.
        product_updates = [u for u in updates if u.field == "product_code"]
        other_updates = [u for u in updates if u.field != "product_code"]
        results: list[UpdateResult] = []
        for batch in (product_updates, other_updates):
            if not batch:
                continue
            specs = all_specs(app)
            specs["product_code"] = FieldSpec(
                name="product_code", label="Product", type=FieldType.enum, options=self._catalog_codes
            )
            offer_ids = {o.offer_id for o in app.offers.offers} if app.offers and offers_current(app) else set()
            results += apply_field_updates(app, batch, specs, offer_ids=offer_ids, now=turn.ctx.now)
            self._sync_application(turn)
        return results

    def _execute_model_tool(self, turn: _Turn, action: ModelAction) -> ToolCallOutcome:
        call = action.action
        self._add_message(turn, "action", json.dumps(action.model_dump(mode="json"), ensure_ascii=False))
        outcome, output = turn.trace.execute(self._registry, call.tool, call.arguments, turn.ctx, caller="model")
        if outcome.ok:
            self._store_output(turn, call.tool, output)
        elif call.tool == "calculate_loan_offer" and outcome.error_code in (
            ToolErrorCode.tool_failed, ToolErrorCode.tool_unavailable,
        ):
            self._clear_pricing(turn.state.application)
        self._add_message(turn, "tool", outcome.as_message())
        self._sync_application(turn)
        return outcome

    def _add_reply(self, turn: _Turn, reply: Respond) -> None:
        sources = turn.state.retrieved_sources
        citations: list[CitationRef] = []
        dropped: list[str] = []
        for cid in reply.citation_ids:
            if cid in sources:
                if sources[cid] not in citations:
                    citations.append(sources[cid])
            else:
                dropped.append(cid)
        if dropped:
            logger.info("citations_dropped %s", json.dumps({
                "session_id": turn.state.session_id, "turn_id": turn.turn_id, "citation_ids": dropped,
            }))
            turn.trace.citations_filtered([cid for cid in reply.citation_ids if cid in sources], dropped)
        self._add_message(turn, "assistant", reply.message, citations)

    # ---- code-side state sync ---------------------------------------------

    def _code_tool(self, turn: _Turn, name: str, arguments: dict) -> BaseModel | None:
        """Run a tool as code; the typed output, or None on failure."""
        return self._run_code_tool(turn, name, arguments)[1]

    def _run_code_tool(
        self, turn: _Turn, name: str, arguments: dict
    ) -> tuple[ToolCallOutcome, BaseModel | None]:
        """Run a tool as code. Failures are logged and reported to the model."""
        outcome, output = turn.trace.execute(self._registry, name, arguments, turn.ctx, caller="code")
        if not outcome.ok:
            if name == "calculate_loan_offer" and outcome.error_code in (
                ToolErrorCode.tool_failed, ToolErrorCode.tool_unavailable,
            ):
                self._clear_pricing(turn.state.application)
            logger.warning("code_tool_failed %s", json.dumps({
                "session_id": turn.state.session_id, "turn_id": turn.turn_id,
                "tool": name, "error_code": outcome.error_code, "error": outcome.error_message,
            }))
            self._add_message(turn, "tool", outcome.as_message())
            return outcome, None
        self._store_output(turn, name, output)
        return outcome, output

    def _store_output(self, turn: _Turn, name: str, output: BaseModel) -> None:
        """Store a successful tool's typed output in state."""
        state = turn.state
        if getattr(output, "simulated", False):
            state.used_stubs = True
        app = state.application
        if app is None:
            return
        if name == "run_eligibility_check":
            app.eligibility = EligibilityRecord(
                result=output,
                input_fingerprint=fingerprint(app, eligibility_input_names(app)),
                verified_inputs=all_verified(app),
            )
        elif name == "calculate_loan_offer":
            if output.status != "ok" or not output.offers:
                self._clear_pricing(app)
                return
            app.offers = OffersRecord(offers=output.offers, input_fingerprint=fingerprint(app, offer_input_names(app)))
            if app.selected_offer_id not in {o.offer_id for o in output.offers}:
                app.selected_offer_id = None
                app.summary = None
        elif name == "get_customer_profile":
            self._apply_profile(app, output, turn.ctx.now)
        elif name == "verify_application_documents":
            app.document_verification = output.cross_validation
            app.document_verification_complete = output.complete
            for item in output.documents:
                records = [doc for doc in app.documents if doc.doc_type == item.doc_type]
                if not records:
                    continue
                doc = max(records, key=lambda record: record.uploaded_at)
                was_accepted = doc.status == DocumentStatus.accepted
                fields_changed = doc.extracted_fields != item.extracted_fields
                doc.human_review_required = item.human_review_required
                if item.status in ("accepted", "rejected"):
                    doc.status = DocumentStatus(item.status)
                    doc.rejection_reason = "; ".join(item.reasons) if item.reasons else None
                if output.cross_validation.human_review_required:
                    doc.status = DocumentStatus.rejected
                    doc.human_review_required = True
                    doc.rejection_reason = "; ".join(output.cross_validation.reasons)
                elif doc.status == DocumentStatus.accepted:
                    doc.extracted_fields = item.extracted_fields
                    if not was_accepted or fields_changed:
                        merge_document_extraction(app, doc, all_specs(app), now=turn.ctx.now)
                        app.eligibility = None
                        app.offers = None
                        app.selected_offer_id = None
                        app.summary = None
            if not output.ready_for_application:
                app.offers = None
                app.selected_offer_id = None
                app.summary = None

    def _refresh_document_verification(self, turn: _Turn) -> None:
        """Fail closed when evidence changes; this gate is independent of model actions."""
        app = turn.state.application
        if not app or not app.requirements or not app.documents or app.application_id is not None:
            return
        if self._registry.get("verify_application_documents") is None:
            return  # Standalone stub registries are only used by isolated unit tests.
        output = self._code_tool(turn, "verify_application_documents", {})
        if output is None:
            for doc in app.documents:
                doc.status = DocumentStatus.rejected
                doc.human_review_required = True
                doc.rejection_reason = "Document verification is unavailable; human review is required."
            app.offers = None
            app.selected_offer_id = None
            app.summary = None

    @staticmethod
    def _clear_pricing(app: ApplicationState | None) -> None:
        """A failed recalculation cannot leave an old offer ready for confirmation."""
        if app is not None and app.application_id is None:
            app.offers = None
            app.selected_offer_id = None
            app.summary = None

    def _apply_profile(self, app: ApplicationState, profile: CustomerProfileOutput, now: datetime) -> None:
        """Profile values fill required identity fields not already set by a document."""
        if app.requirements is None:
            return
        for spec in app.requirements.fields:
            if not spec.identity or spec.name not in ("full_name", "age"):
                continue
            existing = app.fields.get(spec.name)
            if existing is not None and existing.source == FieldSource.document:
                continue
            try:
                value = parse_field_value(spec, getattr(profile, spec.name))
            except FieldValueError:
                continue
            app.fields[spec.name] = FieldValue(
                kind=field_type_to_kind(spec.type),
                value=value,
                source=FieldSource.profile,
                confirmed=True,
                updated_at=now,
            )

    def _sync_application(self, turn: _Turn) -> None:
        """Fetch requirements/profile when the product is set; build the summary
        when only confirmation is left."""
        app = turn.state.application
        if app is None or app.application_id is not None:
            return
        if app.product_code is not None and (
            app.requirements is None or app.requirements.product_code != app.product_code
        ):
            requirements = self._code_tool(turn, "get_product_requirements", {"product_code": app.product_code.value})
            if requirements is None:
                return
            app.requirements = requirements
            if any(spec.identity for spec in requirements.fields):
                self._code_tool(turn, "get_customer_profile", {})
        self._refresh_document_verification(turn)
        self._sync_summary(turn)

    def _sync_summary(self, turn: _Turn) -> None:
        app = turn.state.application
        if [n.kind for n in next_needs(turn.state)] != [NeedKind.confirm_submission]:
            return
        offer = next((o for o in app.offers.offers if o.offer_id == app.selected_offer_id), None)
        if offer is None:
            return
        if app.draft_application_id is None:
            draft = self._code_tool(turn, "create_loan_application", {})
            if draft is None:
                return
            app.draft_application_id = draft.draft_application_id
        if app.summary is not None and app.summary.product_code == offer.product_code:
            product_name = app.summary.product_name
        else:
            product_name = self._product_name(turn, offer.product_code.value)
        summary = build_summary(app, offer, product_name, app.draft_application_id)
        if app.summary is None or app.summary.summary_version != summary.summary_version:
            app.summary = summary

    def _product_name(self, turn: _Turn, code: str) -> str:
        catalog = self._code_tool(turn, "get_credit_products", {})
        if catalog is not None:
            for product in catalog.products:
                if product.code.value == code:
                    return product.name
        return code

    # ---- logging ----------------------------------------------------------

    def _log_step(
        self, turn: _Turn, step: int, started: float, action_type: str | None, tool: str | None, outcome: str
    ) -> None:
        logger.info("orchestrator_step %s", json.dumps({
            "session_id": turn.state.session_id,
            "turn_id": turn.turn_id,
            "step": step,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "action_type": action_type,
            "tool": tool,
            "outcome": outcome,
        }))


def _rejection_notice(rejected: list[UpdateResult]) -> str:
    return "FIELD_UPDATES_REJECTED: " + json.dumps(
        [{"field": r.field, "reason": r.reason} for r in rejected], ensure_ascii=False
    )
