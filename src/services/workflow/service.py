"""Own the origination state machine, evidence gates and submission confirmation."""

from src.core.catalogue import Catalogue
from src.core.context import CallContext
from src.core.errors import DomainError
from src.models.banking import (
    ApplicationDocument,
    ApplicationState,
    ApplicationStatus,
    DocumentKind,
    HistoryEntry,
    LoanApplication,
    ReviewNote,
    Role,
)
from src.models.common import new_id, utc_now
from src.models.requests import (
    CancelApplicationInput,
    CreateApplicationInput,
    SubmitApplicationInput,
    UploadDocumentInput,
)
from src.observability.audit import record_audit
from src.security.permissions import require_role, visible_application
from src.services.document_processing.service import DocumentService
from src.services.financial_calculations.preview import AffordabilityPreviewService
from src.services.notifications.service import workflow_notification
from src.services.pricing.service import PricingService
from src.storage.application_db.repository import Repository


S = ApplicationStatus
TRANSITIONS = {
    S.DRAFT: {S.AWAITING_DOCUMENTS, S.CANCELLED},
    S.AWAITING_DOCUMENTS: {S.READY_FOR_SUBMISSION, S.CANCELLED},
    S.READY_FOR_SUBMISSION: {S.PENDING_HUMAN_REVIEW, S.CANCELLED},
    S.PENDING_HUMAN_REVIEW: {S.MORE_INFORMATION_REQUIRED, S.APPROVED, S.REJECTED},
    S.MORE_INFORMATION_REQUIRED: {S.READY_FOR_SUBMISSION, S.CANCELLED},
    S.APPROVED: set(), S.REJECTED: set(), S.CANCELLED: set(),
}


def has_required_documents(application: LoanApplication) -> bool:
    required = set(application.required_document_kinds)
    if application.requested_document is not None:
        required.add(application.requested_document)
    accepted = {d.kind for d in application.documents if d.status == "FORMAT_ACCEPTED"}
    return bool(required) and required <= accepted


def transition(application: LoanApplication, next_status: ApplicationStatus, context: CallContext, description: str) -> None:
    if next_status not in TRANSITIONS[application.status]:
        raise DomainError("INVALID_TRANSITION", f"Cannot change {application.status.value} to {next_status.value}.", 409)
    application.status = next_status
    application.updated_at = utc_now()
    application.history.append(HistoryEntry(
        id=new_id(), status=next_status, at=application.updated_at, actor=context.actor.name,
        description=description, correlation_id=context.correlation_id,
    ))


class WorkflowService:
    def __init__(
        self, repository: Repository, catalogue: Catalogue, pricing: PricingService,
        affordability: AffordabilityPreviewService, documents: DocumentService,
    ):
        self.repository = repository
        self.catalogue = catalogue
        self.pricing = pricing
        self.affordability = affordability
        self.documents = documents

    def list(self, context: CallContext) -> list[LoanApplication]:
        with self.repository.read() as unit:
            return [visible_application(app, context.actor) for app in unit.applications(context.actor)]

    def get(self, context: CallContext, application_id: str) -> LoanApplication:
        with self.repository.read() as unit:
            return visible_application(unit.application(application_id, context.actor), context.actor)

    def status(self, context: CallContext, application_id: str) -> ApplicationState:
        application = self.get(context, application_id)
        return ApplicationState(
            application_id=application.id, status=application.status, updated_at=application.updated_at,
            requested_document=application.requested_document, request_reason=application.request_reason,
            decision_reason=application.decision_reason, history=application.history,
        )

    def create(self, context: CallContext, input: CreateApplicationInput) -> LoanApplication:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.transaction() as unit:
            def action() -> LoanApplication:
                product = self.catalogue.product(input.product_id)
                quote = self.pricing.calculate(input)
                now = utc_now()
                application = LoanApplication(
                    id=new_id(), reference=unit.next_reference(), customer_id=context.actor.id,
                    customer=unit.customer(context.actor.id), reviewer_id=self.catalogue.fixtures.default_reviewer_id,
                    product_id=product.id, policy_version=product.policy_version, amount=quote.amount,
                    months=input.months, quote=quote, affordability_preview=self.affordability.assess(unit, context.actor, input),
                    status=S.DRAFT, created_at=now, updated_at=now,
                    documents=[ApplicationDocument(kind=kind) for kind in DocumentKind],
                    required_document_kinds=product.required_documents,
                    history=[HistoryEntry(
                        id=new_id(), status=S.DRAFT, at=now, actor=context.actor.name,
                        description="Synthetic draft saved. No application has been submitted.",
                        correlation_id=context.correlation_id,
                    )],
                )
                application.pricing_scenario_id = f"quote-{application.id}"
                transition(application, S.AWAITING_DOCUMENTS, context, "Add the required synthetic document metadata.")
                unit.save_application(application)
                record_audit(unit, context, "APPLICATION_CREATED", application.id, "Synthetic draft only")
                return visible_application(application, context.actor)

            return unit.idempotent(context.actor, str(input.idempotency_key), "application:create", input, LoanApplication, action)

    def upload(self, context: CallContext, application_id: str, input: UploadDocumentInput) -> LoanApplication:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.transaction() as unit:
            application = unit.application(application_id, context.actor)

            def action() -> LoanApplication:
                if application.status not in {S.AWAITING_DOCUMENTS, S.READY_FOR_SUBMISSION, S.MORE_INFORMATION_REQUIRED}:
                    raise DomainError("INVALID_TRANSITION", "This application is not accepting document metadata.", 409)
                self.documents.validate(input)
                index = next((i for i, d in enumerate(application.documents) if d.kind == input.kind), None)
                if index is None:
                    raise DomainError("VALIDATION_ERROR", "Document kind is not part of this application's checklist.")
                application.documents[index] = ApplicationDocument(
                    kind=input.kind, status="FORMAT_ACCEPTED", name=input.name, mime_type=input.mime_type,
                    size=input.size, uploaded_at=utc_now(),
                )
                application.updated_at = utc_now()
                if application.status != S.READY_FOR_SUBMISSION and has_required_documents(application):
                    transition(application, S.READY_FOR_SUBMISSION, context, "Metadata checklist complete; explicit submission is still required.")
                application.notes.append(ReviewNote(
                    id=new_id(), author=context.actor.name, at=application.updated_at, internal=False,
                    text=f"{input.kind.value} metadata accepted. No bytes, OCR or authenticity verification.",
                ))
                unit.save_application(application)
                record_audit(unit, context, "DOCUMENT_METADATA_ADDED", application.id, f"{input.kind.value}: format accepted, not verified")
                return visible_application(application, context.actor)

            return unit.idempotent(context.actor, str(input.idempotency_key), f"document:add:{application_id}", input, LoanApplication, action)

    def submit(self, context: CallContext, application_id: str, input: SubmitApplicationInput) -> LoanApplication:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.transaction() as unit:
            application = unit.application(application_id, context.actor)

            def action() -> LoanApplication:
                if input.confirmed is not True:
                    raise DomainError("CONFIRMATION_REQUIRED", "Explicit customer submission confirmation is required.")
                if application.status != S.READY_FOR_SUBMISSION or not has_required_documents(application):
                    raise DomainError("INVALID_TRANSITION", "Complete the requested document metadata before submitting.", 409)
                transition(application, S.PENDING_HUMAN_REVIEW, context, "Customer explicitly confirmed submission to the assigned human reviewer.")
                application.requested_document = None
                application.request_reason = None
                unit.save_application(application)
                record_audit(unit, context, "APPLICATION_SUBMITTED", application.id, "Pending independent human review; not approved")
                workflow_notification(unit, application, "Application sent for demo review", f"{application.reference} is awaiting human review. No real bank application was sent.")
                return visible_application(application, context.actor)

            return unit.idempotent(context.actor, str(input.idempotency_key), f"application:submit:{application_id}", input, LoanApplication, action)

    def cancel(self, context: CallContext, application_id: str, input: CancelApplicationInput) -> LoanApplication:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.transaction() as unit:
            application = unit.application(application_id, context.actor)

            def action() -> LoanApplication:
                transition(application, S.CANCELLED, context, input.reason)
                unit.save_application(application)
                record_audit(unit, context, "APPLICATION_CANCELLED", application.id, "Synthetic pre-review application cancelled")
                return visible_application(application, context.actor)

            return unit.idempotent(context.actor, str(input.idempotency_key), f"application:cancel:{application_id}", input, LoanApplication, action)