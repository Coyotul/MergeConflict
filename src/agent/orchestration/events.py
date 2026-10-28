"""Code-handled turn events: document upload, offer selection, confirmation.

Each event's tool runs before any model call; the model then only explains
the result. If the model is unavailable, or gives no usable reply within the
step cap, the state is still saved and the customer gets a fixed text for the
event in the session language. A submission is saved the moment
submit_application succeeds, and its reply (also for a repeated confirmation)
is always the fixed "submitted" text: the model is never asked to describe it.
"""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Union

from src.agent.orchestration.blocks import all_specs
from src.agent.orchestration.fields import merge_document_extraction
from src.agent.orchestration.progress import NeedKind, next_needs, offers_current
from src.agent.orchestration.state import DocumentRecord, DocumentStatus, SessionState
from src.core.errors import InvalidUpload, ModelUnavailable
from src.models.chat import TurnResponse

if TYPE_CHECKING:
    from src.agent.orchestration.orchestrator import _Turn


# ---- events ---------------------------------------------------------------

@dataclass(frozen=True)
class SessionStarted:
    pass


@dataclass(frozen=True)
class CustomerMessage:
    text: str


@dataclass(frozen=True)
class DocumentUploaded:
    document_id: str
    doc_type: str
    filename: str
    size_bytes: int


@dataclass(frozen=True)
class OfferSelected:
    offer_id: str


@dataclass(frozen=True)
class ConfirmationDecision:
    summary_version: str
    decision: Literal["confirm", "decline"]


TurnEvent = Union[SessionStarted, CustomerMessage, DocumentUploaded, OfferSelected, ConfirmationDecision]


# ---- fixed texts (used when the model can't explain the event) -------------

EVENT_TEXTS: dict[str, dict[str, str]] = {
    "submitted": {
        "en": "Your application was submitted for human review. Its reference is {id}. "
              "No decision has been made yet.",
        "ro": "Cererea ta a fost trimisă spre analiză unui consultant. Referința ei este {id}. "
              "Nu s-a luat încă nicio decizie.",
    },
    "document_accepted": {
        "en": "We received your {label}.",
        "ro": "Am primit documentul: {label}.",
    },
    "document_rejected": {
        "en": "We couldn't use your {label}: {reason}",
        "ro": "Nu am putut folosi documentul {label}: {reason}",
    },
    "offer_selected": {
        "en": "You chose the {term}-month option.",
        "ro": "Ai ales varianta pe {months}.",
    },
    "declined": {
        "en": "OK, nothing was submitted. You can change any detail.",
        "ro": "Bine, nu am trimis nimic. Poți modifica orice detaliu.",
    },
    "offer_rejected": {
        "en": "That offer is no longer available. Please choose one of the current offers.",
        "ro": "Această ofertă nu mai este disponibilă. Te rog să alegi una dintre ofertele actuale.",
    },
    "summary_changed": {
        "en": "The summary you confirmed is no longer current, so nothing was submitted. "
              "Please review the current details.",
        "ro": "Rezumatul confirmat nu mai este actual, așa că nu am trimis nimic. "
              "Te rog să verifici detaliile actuale.",
    },
    "not_submitted": {
        "en": "Your application was not submitted because of a technical problem. "
              "Please try again in a moment.",
        "ro": "Cererea ta nu a fost trimisă din cauza unei probleme tehnice. "
              "Te rog să încerci din nou în câteva momente.",
    },
}

# Rejection reason when process_document itself fails (no success state).
PROCESSING_FAILED_REASON = "The document could not be processed right now; please upload it again."


def _ro_months(n: int) -> str:
    """'12 luni', '48 de luni' (Romanian takes 'de' from 20 upwards)."""
    if n == 1:
        return "1 lună"
    rest = n % 100
    return f"{n} de luni" if rest == 0 or rest >= 20 else f"{n} luni"


def event_text(key: str, language: str, **values) -> str:
    if key == "offer_selected":
        values.setdefault("months", _ro_months(values["term"]))
    return EVENT_TEXTS[key][language].format(**values)


def requested_document(state: SessionState, doc_type: str) -> str:
    """Return the label of a document the active application requires.

    Raises InvalidUpload("document_not_requested") otherwise.
    """
    app = state.application
    if app is None or app.requirements is None or app.application_id is not None:
        raise InvalidUpload("document_not_requested", "There is no active application requesting documents.")
    for req in app.requirements.documents:
        if req.doc_type == doc_type:
            return req.label
    raise InvalidUpload("document_not_requested", f"Document type '{doc_type}' is not requested.")


class CodeEventsMixin:
    """Event handlers for Orchestrator (uses its turn plumbing and model loop)."""

    def check_upload(self, session_id: str, customer_id: str, doc_type: str) -> None:
        """Raise SessionNotFound / SessionAccessDenied / InvalidUpload before a file is stored."""
        requested_document(self._load_owned(session_id, customer_id), doc_type)

    # ---- handlers ---------------------------------------------------------

    def _handle_document_uploaded(self, state: SessionState, event: DocumentUploaded) -> TurnResponse:
        label = requested_document(state, event.doc_type)
        loaded = state.model_copy(deep=True)
        turn = self._begin_turn(state)
        app = state.application

        # A re-upload replaces the earlier record of this type.
        app.documents = [d for d in app.documents if d.doc_type != event.doc_type]
        record = DocumentRecord(
            document_id=event.document_id,
            doc_type=event.doc_type,
            filename=event.filename,
            status=DocumentStatus.processing,
            uploaded_at=self._clock(),
        )
        app.documents.append(record)

        output = self._code_tool(turn, "process_document", {
            "document_id": event.document_id,
            "doc_type": event.doc_type,
            "filename": event.filename,
            "size_bytes": event.size_bytes,
        })
        if output is None:
            record.status, record.rejection_reason = DocumentStatus.rejected, PROCESSING_FAILED_REASON
        else:
            record.status = DocumentStatus(output.status)
            record.rejection_reason = output.rejection_reason
            record.extracted_fields = dict(output.extracted_fields)
        if record.status == DocumentStatus.accepted:
            merge_document_extraction(app, record, all_specs(app), now=turn.ctx.now)
            text = event_text("document_accepted", state.language, label=label)
            self._add_message(turn, "event", f"DOCUMENT_PROCESSED {event.doc_type}: accepted")
        else:
            reason = record.rejection_reason or ""
            text = event_text("document_rejected", state.language, label=label, reason=reason)
            self._add_message(turn, "event", f"DOCUMENT_PROCESSED {event.doc_type}: rejected {reason}".rstrip())
        return self._explain(turn, loaded, text)

    def _handle_offer_selected(self, state: SessionState, event: OfferSelected) -> TurnResponse:
        loaded = state.model_copy(deep=True)
        turn = self._begin_turn(state)
        app = state.application
        offer = None
        if app is not None and app.application_id is None and app.offers is not None and offers_current(app):
            offer = next((o for o in app.offers.offers if o.offer_id == event.offer_id), None)
        if offer is None:
            self._add_message(turn, "event", "OFFER_SELECTION_REJECTED")
            return self._explain(turn, loaded, event_text("offer_rejected", state.language))
        app.selected_offer_id = offer.offer_id
        self._add_message(turn, "event", f"OFFER_SELECTED {offer.offer_id}")
        return self._explain(turn, loaded, event_text("offer_selected", state.language, term=offer.term_months))

    def _handle_confirmation(self, state: SessionState, event: ConfirmationDecision) -> TurnResponse:
        loaded = state.model_copy(deep=True)
        turn = self._begin_turn(state)
        app = state.application
        language = state.language

        if app is not None and app.application_id is not None:
            self._add_message(turn, "event", f"ALREADY_SUBMITTED {app.application_id}")
            return self._fixed_reply(turn, loaded, event_text("submitted", language, id=app.application_id))

        self._sync_application(turn)  # make sure the summary reflects the current state
        needs = [n.kind for n in next_needs(state)]
        if (
            app is None
            or needs[:1] != [NeedKind.confirm_submission]
            or app.summary is None
            or app.summary.summary_version != event.summary_version
        ):
            self._add_message(turn, "event", "SUMMARY_CHANGED")
            return self._explain(turn, loaded, event_text("summary_changed", language))

        if event.decision == "decline":
            app.summary = None
            app.selected_offer_id = None
            self._add_message(turn, "event", "SUBMISSION_DECLINED")
            return self._explain(turn, loaded, event_text("declined", language))

        key = f"{state.session_id}:{app.summary.summary_version}"
        outcome, output = self._run_code_tool(
            turn, "submit_application", {"application_id": app.draft_application_id, "idempotency_key": key}
        )
        if output is None:
            self._add_message(turn, "event", f"SUBMISSION_FAILED {outcome.error_code}")
            return self._explain(turn, loaded, event_text("not_submitted", language))

        app.application_id = output.application_id
        app.submitted_at = self._clock()
        app.idempotency_key = key
        # Persist the submission before any model call: it must survive a provider failure.
        state.updated_at = self._clock()
        saved = self._store.save(state, expected_version=loaded.version)
        state.version = saved.version
        loaded = state.model_copy(deep=True)

        self._add_message(turn, "tool", outcome.as_message())
        self._add_message(turn, "event", f"APPLICATION_SUBMITTED {app.application_id} {output.status}")
        return self._fixed_reply(turn, loaded, event_text("submitted", language, id=app.application_id))

    def _fixed_reply(self, turn: "_Turn", loaded: SessionState, text: str) -> TurnResponse:
        """Reply with a fixed text, no model call (submission must never be paraphrased)."""
        self._add_message(turn, "assistant", text)
        return self._commit(turn, loaded)

    def _explain(self, turn: "_Turn", loaded: SessionState, text: str) -> TurnResponse:
        """Let the model explain the event; fall back to `text` if it can't. Then save."""
        try:
            self._run_model_steps(turn, [], fallback=text)
        except ModelUnavailable:
            self._add_message(turn, "assistant", text)
        return self._commit(turn, loaded)
