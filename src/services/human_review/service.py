"""Reviewer decisions and customer uploads for requested documents.

A requested upload is only processed as the requested type and only moves the case on when it
passes the same acceptance rules as a chat upload. Accepted evidence triggers a fresh eligibility
and pricing run on the stored values; the reviewer then sees both the original and current result.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Literal

from src.agent.orchestration.state import (
    ApplicationState, DocumentStatus, FieldSource, FieldValue, Flow, SessionState,
)
from src.agent.orchestration.fields import field_type_to_kind, parse_field_value
from src.agent.tools.contracts import CalculateOffersInput, RunEligibilityInput
from src.agent.tools.documents import DOCUMENT_KINDS, assess_processed_document
from src.agent.tools.registry import ToolContext
from src.agent.tools.stubs import StubData, build_stub_registry
from src.models.document_processing import ExtractedIdentity, ExtractedIncome, ExtractedStatement
from src.services.document_processing.service import DocumentProcessingService
from src.services.human_review.models import (
    InvalidTransition, NotFound, ReviewApplication, ReviewDocument, ReviewStatus,
)
from src.services.human_review.store import ReviewStore

DOCUMENT_LABELS = {"id_card": "ID card", "payslip": "payslip", "bank_statement": "bank statement"}
_EXTRACTED_MODELS = {"id_card": ExtractedIdentity, "payslip": ExtractedIncome, "bank_statement": ExtractedStatement}


@dataclass
class UploadOutcome:
    accepted: bool
    reasons: list[str] = field(default_factory=list)


class ReviewService:
    def __init__(self, store: ReviewStore, documents: DocumentProcessingService, stub_data: StubData,
                 clock: Callable[[], datetime]):
        self.store = store
        self.documents = documents
        self.stub_data = stub_data
        self.clock = clock

    # ---- reviewer ---------------------------------------------------------

    def request_document(self, app_id: str, *, doc_type: str, reason: str, version: int) -> ReviewApplication:
        app = self.store.get(app_id)
        reason = _required_reason(reason)
        if doc_type not in DOCUMENT_KINDS or doc_type not in _required_doc_types(app):
            raise ValueError(f"'{doc_type}' cannot be requested for this application.")
        if app.open_request is not None:
            raise InvalidTransition("A document request is already open.")
        return self.store.transition(app_id, to=ReviewStatus.MORE_INFORMATION_REQUIRED, actor="reviewer",
                                     reason=reason, expected_version=version, now=self.clock(),
                                     request_doc_type=doc_type)

    def decide(self, app_id: str, *, action: Literal["approve", "reject"], reason: str, version: int) -> ReviewApplication:
        to = {"approve": ReviewStatus.APPROVED, "reject": ReviewStatus.REJECTED}[action]
        return self.store.transition(app_id, to=to, actor="reviewer", reason=_required_reason(reason),
                                     expected_version=version, now=self.clock())

    # ---- customer ---------------------------------------------------------

    def customer_application(self, app_id: str, customer_id: str) -> ReviewApplication:
        app = self.store.get(app_id)
        if app.customer_id != customer_id:
            raise NotFound(app_id)
        return app

    def upload_requested(
        self, app_id: str, request_id: str, *, customer_id: str, filename: str, content: bytes, mime_type: str,
    ) -> tuple[ReviewApplication, UploadOutcome]:
        app = self.customer_application(app_id, customer_id)
        request = app.open_request
        if request is None or request.id != request_id or app.status != ReviewStatus.MORE_INFORMATION_REQUIRED:
            raise InvalidTransition("There is no open request for this document.")
        doc_type, now = request.doc_type, self.clock()
        stored = self.documents.storage.store_document(
            customer_id=customer_id, filename=filename, content_bytes=content, mime_type=mime_type,
            doc_kind=doc_type, application_id=app_id,
        )
        result = self.documents.process_stored_document(
            stored["document_id"], customer_id, DOCUMENT_KINDS[doc_type], as_of=now.date(), allow_synthetic_cnp=False,
        )
        requirements = app.current["application"].get("requirements") or {}
        specs = [s for s in _application(app).requirements.fields if s.required and s.verified_by == doc_type] \
            if requirements else []
        output = assess_processed_document(doc_type, result, profile=app.snapshot.get("profile", {}),
                                           required_fields=specs, today=now.date())
        reasons = []
        if output.status != "accepted" or output.human_review_required:
            reasons = [r.strip() for r in (output.rejection_reason or "").split(";") if r.strip()]
            if not any(output.extracted_data.get(k) for k in _identifying_keys(doc_type)):
                reasons.insert(0, f"This doesn't look like the requested {DOCUMENT_LABELS[doc_type]}.")
            reasons = reasons or ["The document could not be accepted; please upload a clear, current copy."]
        else:
            reasons = self._cross_check(app, doc_type, output.extracted_data)
        if reasons:
            self.documents.storage.delete_document(stored["document_id"], customer_id=customer_id)
            return app, UploadOutcome(accepted=False, reasons=reasons)

        document = ReviewDocument(
            document_id=stored["document_id"], doc_type=doc_type, origin="information_request", status="accepted",
            filename=stored["original_filename"],
            extracted_fields={name: f.value for name, f in output.extracted_fields.items()},
            validation=output.validation.model_dump(mode="json") if output.validation else None,
            sha256=output.sha256_hash, uploaded_at=now,
        )
        current = self._recalculate(app, doc_type, document, output.extracted_fields, output.extracted_data, now)
        return self.store.fulfil_request(app_id, request_id, document=document, current=current, now=now), \
            UploadOutcome(accepted=True)

    # ---- helpers ----------------------------------------------------------

    def _cross_check(self, app: ReviewApplication, doc_type: str, extracted: dict) -> list[str]:
        others = _application(app).documents
        values = {d.doc_type: d.extracted_data for d in others
                  if d.status == DocumentStatus.accepted and d.extracted_data and d.doc_type != doc_type}
        values[doc_type] = extracted
        parsed = {k: _EXTRACTED_MODELS[k].model_validate(v) for k, v in values.items() if k in _EXTRACTED_MODELS}
        if len(parsed) < 2:
            return []
        cross = self.documents.cross_validate_application(
            identity_doc=parsed.get("id_card"), income_doc=parsed.get("payslip"), statement_doc=parsed.get("bank_statement"),
        )
        if cross.consistent and not cross.human_review_required:
            return []
        return cross.reasons or ["The document does not match the other documents in this application."]

    def _recalculate(self, app, doc_type, document, extracted_fields, extracted_data, now) -> dict:
        state = SessionState(
            session_id=app.session_id, customer_id=app.customer_id, created_at=now, updated_at=now,
            active_flow=Flow.credit_application, application=_application(app),
        )
        application = state.application
        specs = {s.name: s for s in application.requirements.fields}
        for name, extracted in extracted_fields.items():
            if name in specs:
                application.fields[name] = FieldValue(
                    kind=field_type_to_kind(specs[name].type), value=parse_field_value(specs[name], extracted.value),
                    source=FieldSource.document, document_id=document.document_id,
                    confidence=extracted.confidence, confirmed=True, updated_at=now,
                )
        for record in application.documents:
            if record.doc_type == doc_type:
                record.extracted_data = extracted_data
        ctx = ToolContext(state, now)
        registry = build_stub_registry(self.stub_data, _NoSearch())
        eligibility = registry.get("run_eligibility_check").handler(RunEligibilityInput(), ctx)
        priced = registry.get("calculate_loan_offer").handler(CalculateOffersInput(), ctx)
        offer = priced.offers[0] if priced.offers else None
        return {
            "application": application.model_dump(mode="json"),
            "eligibility": eligibility.model_dump(mode="json") if eligibility else None,
            "offer": offer.model_dump(mode="json") if offer else None,
            "pricing_errors": [e.model_dump(mode="json") for e in priced.errors],
        }


class _NoSearch:
    def search(self, query):  # pragma: no cover - recalculation never searches policies
        raise RuntimeError("policy search is not available during recalculation")


def _application(app: ReviewApplication) -> ApplicationState:
    return ApplicationState.model_validate(app.current["application"])


def _required_doc_types(app: ReviewApplication) -> set[str]:
    requirements = app.snapshot.get("application", {}).get("requirements") or {}
    return {d["doc_type"] for d in requirements.get("documents", [])}


def _required_reason(reason: str) -> str:
    if not reason or not reason.strip():
        raise ValueError("A reason the customer can read is required.")
    return reason.strip()


def _identifying_keys(doc_type: str) -> tuple[str, ...]:
    return {
        "id_card": ("cnp", "last_name"),
        "payslip": ("employer_name", "employee_name", "monthly_net_income"),
        "bank_statement": ("iban", "account_holder"),
    }[doc_type]
