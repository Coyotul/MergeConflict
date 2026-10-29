"""Code-handled turn events: document upload and offer selection.

Each event's tool runs before any model call; the model then only explains
the result. If the model is unavailable, or gives no usable reply within the
step cap, the state is still saved and the customer gets a fixed text for the
event in the session language. A submission is saved the moment
submit_application succeeds, and its reply (also for a repeated confirmation)
is always the fixed "submitted" text: the model is never asked to describe it.
"""
from dataclasses import dataclass
import json
from typing import TYPE_CHECKING, Literal, Union

from src.agent.orchestration.blocks import all_specs
from src.agent.orchestration.fields import FieldValueError, field_type_to_kind, merge_document_extraction, parse_field_value
from src.agent.orchestration.progress import NeedKind, next_needs, offers_current
from src.agent.orchestration.state import DocumentRecord, DocumentStatus, FieldSource, FieldValue, SessionState
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


TurnEvent = Union[SessionStarted, CustomerMessage, DocumentUploaded, OfferSelected]


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
    "document_review": {
        "en": "Your {label} needs human verification: {reason} Offers and submission are blocked until the evidence is resolved.",
        "ro": "Documentul {label} necesită verificare umană: {reason} Ofertele și trimiterea cererii sunt blocate până la clarificarea dovezilor.",
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

    def references_document(self, session_id: str, customer_id: str, document_id: str) -> bool:
        """Cleanup must not remove evidence after state was committed but logging failed."""
        try:
            state = self._load_owned(session_id, customer_id)
        except Exception:
            # An unavailable state store is not proof that it is safe to delete evidence.
            return True
        return bool(state.application and any(d.document_id == document_id for d in state.application.documents))

    # ---- handlers ---------------------------------------------------------

    def _handle_document_uploaded(self, turn: "_Turn", event: DocumentUploaded) -> TurnResponse:
        state = turn.state
        label = requested_document(state, event.doc_type)
        loaded = state.model_copy(deep=True)
        app = state.application

        # A re-upload replaces the earlier record of this type.
        previous_ids = {d.document_id for d in app.documents if d.doc_type == event.doc_type}
        app.documents = [d for d in app.documents if d.doc_type != event.doc_type]
        # A replacement invalidates downstream decisions, even if values are unchanged.
        app.eligibility = None
        app.offers = None
        app.selected_offer_id = None
        app.summary = None
        app.document_verification = None
        app.document_verification_complete = False
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
            record.human_review_required = output.human_review_required
            record.validation = output.validation
            record.extracted_data = output.extracted_data
            record.sha256_hash = output.sha256_hash
            # Only safe, relevant evidence goes to the model, never raw OCR text,
            # identifiers, file paths, or detailed validation of the original document.
            self._add_message(turn, "tool", "TOOL_RESULT process_document: " + json.dumps({
                "status": output.status, "rejection_reason": output.rejection_reason,
                "extracted_fields": {name: value.model_dump() for name, value in output.extracted_fields.items()},
                "human_review_required": output.human_review_required, "simulated": output.simulated,
            }))
        self._refresh_document_verification(turn)
        if app.document_verification and app.document_verification.human_review_required and record.status == DocumentStatus.accepted:
            record.human_review_required = True
            record.rejection_reason = "; ".join(app.document_verification.reasons)
            record.extracted_fields = {}
        if record.human_review_required:
            record.status = DocumentStatus.rejected
        if record.status == DocumentStatus.accepted:
            merge_document_extraction(app, record, all_specs(app), now=turn.ctx.now)
            text = event_text("document_accepted", state.language, label=label)
            self._add_message(turn, "event", f"DOCUMENT_PROCESSED {event.doc_type}: accepted")
            turn.trace.code_event("upload", "accepted", doc_type=event.doc_type)
        else:
            # Preserve the customer's earlier statement, if known, but never its old
            # document verification. This also keeps a meaningful conflict on a retry.
            specs = all_specs(app)
            for name, value in list(app.fields.items()):
                if value.document_id not in previous_ids:
                    continue
                del app.fields[name]
                conflict = next((c for c in app.conflicts if c.field == name and c.document_id in previous_ids), None)
                if conflict is not None and name in specs:
                    try:
                        stated = parse_field_value(specs[name], conflict.customer_value)
                    except FieldValueError:
                        continue
                    app.fields[name] = FieldValue(
                        kind=field_type_to_kind(specs[name].type), value=stated,
                        source=FieldSource.customer, confirmed=True, updated_at=turn.ctx.now,
                    )
            app.conflicts = [conflict for conflict in app.conflicts if conflict.document_id not in previous_ids]
            reason = record.rejection_reason or ""
            text = event_text("document_rejected", state.language, label=label, reason=reason)
            turn.trace.code_event("upload", "rejected", doc_type=event.doc_type, reason=reason)
            self._add_message(turn, "event", f"DOCUMENT_PROCESSED {event.doc_type}: rejected {reason}".rstrip())
            if record.human_review_required:
                text = event_text("document_review", state.language, label=label, reason=reason)
                # A model explanation cannot conceal a deterministic review gate.
                return self._fixed_reply(turn, loaded, text)
        return self._explain(turn, loaded, text)

    def _handle_offer_selected(self, turn: "_Turn", event: OfferSelected) -> TurnResponse:
        state = turn.state
        loaded = state.model_copy(deep=True)
        self._refresh_document_verification(turn)
        app = state.application
        offer = None
        if app is not None and app.application_id is None and app.offers is not None and offers_current(app):
            offer = next((o for o in app.offers.offers if o.offer_id == event.offer_id), None)
        if offer is None:
            self._add_message(turn, "event", "OFFER_SELECTION_REJECTED")
            turn.trace.code_event("offer", "rejected", offer_id=event.offer_id)
            return self._explain(turn, loaded, event_text("offer_rejected", state.language))
        app.selected_offer_id = offer.offer_id
        self._add_message(turn, "event", f"OFFER_SELECTED {offer.offer_id}")
        turn.trace.code_event("offer", "selected", offer_id=offer.offer_id)
        return self._explain(turn, loaded, event_text("offer_selected", state.language, term=offer.term_months))

    def _fixed_reply(self, turn: "_Turn", loaded: SessionState, text: str) -> TurnResponse:
        """Reply with a fixed text, no model call (submission must never be paraphrased)."""
        turn.trace.outcome = "replied"
        self._add_message(turn, "assistant", text)
        return self._commit(turn, loaded)

    def _explain(self, turn: "_Turn", loaded: SessionState, text: str) -> TurnResponse:
        """Let the model explain the event; fall back to `text` if it can't. Then save."""
        try:
            self._run_model_steps(turn, [], fallback=text)
        except ModelUnavailable:
            turn.trace.outcome = "model_unavailable"
            self._add_message(turn, "assistant", text)
        return self._commit(turn, loaded)
