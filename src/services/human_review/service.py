"""Only the assigned reviewer can record justified synthetic decisions."""

from src.core.context import CallContext
from src.core.errors import DomainError
from src.models.banking import ApplicationDocument, ApplicationStatus, LoanApplication, ReviewNote, Role
from src.models.common import new_id, utc_now
from src.models.requests import NoteInput, ReviewInput
from src.observability.audit import record_audit
from src.security.permissions import require_role
from src.services.notifications.service import workflow_notification
from src.services.workflow.service import has_required_documents, transition
from src.storage.application_db.repository import Repository


class HumanReviewService:
    def __init__(self, repository: Repository):
        self.repository = repository

    def queue(self, context: CallContext) -> list[LoanApplication]:
        require_role(context.actor, Role.REVIEWER)
        with self.repository.read() as unit:
            return [app for app in unit.applications(context.actor) if app.status == ApplicationStatus.PENDING_HUMAN_REVIEW]

    def review(self, context: CallContext, application_id: str, input: ReviewInput) -> LoanApplication:
        require_role(context.actor, Role.REVIEWER)
        with self.repository.transaction() as unit:
            application = unit.application(application_id, context.actor)

            def action() -> LoanApplication:
                if application.status != ApplicationStatus.PENDING_HUMAN_REVIEW:
                    raise DomainError("INVALID_TRANSITION", "Only applications awaiting human review can receive a decision.", 409)
                if input.evidence_reviewed is not True:
                    raise DomainError("EVIDENCE_REQUIRED", "Independently inspect the evidence before recording a decision.")
                if input.action != "request-information" and not has_required_documents(application):
                    raise DomainError("EVIDENCE_REQUIRED", "The required demo document metadata is incomplete.", 409)
                if input.action == "request-information":
                    if input.requested_document is None:
                        raise DomainError("VALIDATION_ERROR", "Choose the additional document to request.")
                    index = next((i for i, d in enumerate(application.documents) if d.kind == input.requested_document), None)
                    if index is None:
                        raise DomainError("VALIDATION_ERROR", "Requested document is not in the application checklist.")
                    application.documents[index] = ApplicationDocument(kind=input.requested_document)
                    if input.requested_document not in application.required_document_kinds:
                        application.required_document_kinds.append(input.requested_document)
                    application.requested_document = input.requested_document
                    application.request_reason = input.reason
                    next_status = ApplicationStatus.MORE_INFORMATION_REQUIRED
                else:
                    application.decision_reason = input.reason
                    next_status = ApplicationStatus.APPROVED if input.action == "approve" else ApplicationStatus.REJECTED
                transition(application, next_status, context, input.reason)
                application.notes.append(ReviewNote(
                    id=new_id(), author=context.actor.name, at=application.updated_at, text=input.reason, internal=False,
                ))
                unit.save_application(application)
                record_audit(unit, context, f"REVIEW_{input.action.upper().replace('-', '_')}", application.id, "Synthetic assigned-human review recorded; not signed or funded")
                workflow_notification(
                    unit, application,
                    "A reviewer needs more information" if input.action == "request-information" else "Your demo review has an outcome",
                    f"{input.reason} This is a synthetic review only. Nothing was signed or funded.",
                )
                return application

            return unit.idempotent(context.actor, str(input.idempotency_key), f"application:review:{application_id}", input, LoanApplication, action)

    def add_note(self, context: CallContext, application_id: str, input: NoteInput) -> LoanApplication:
        require_role(context.actor, Role.REVIEWER)
        with self.repository.transaction() as unit:
            application = unit.application(application_id, context.actor)

            def action() -> LoanApplication:
                application.notes.append(ReviewNote(
                    id=new_id(), author=context.actor.name, at=utc_now(), text=input.text, internal=True,
                ))
                application.updated_at = utc_now()
                unit.save_application(application)
                record_audit(unit, context, "INTERNAL_NOTE_ADDED", application.id, "Recorded for the assigned reviewer only")
                return application

            return unit.idempotent(context.actor, str(input.idempotency_key), f"application:note:{application_id}", input, LoanApplication, action)