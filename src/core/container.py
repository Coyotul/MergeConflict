"""The modular-monolith composition root; domain services do not import FastAPI."""

from dataclasses import dataclass

from src.core.catalogue import Catalogue
from src.core.context import CallContext
from src.core.settings import Settings
from src.models.banking import Actor, AffordabilityPreview, AuditEvent, Role, Snapshot
from src.models.requests import LoanScenarioInput
from src.observability.audit import record_audit
from src.security.permissions import require_role, visible_application
from src.security.sessions import DemoSessions
from src.services.conversations.service import ConversationService
from src.services.customers.service import CustomerService
from src.services.document_processing.service import DocumentService
from src.services.eligibility.backend import BackendEligibilityService
from src.services.financial_calculations.preview import AffordabilityPreviewService
from src.services.human_review.service import HumanReviewService
from src.services.loan_servicing.service import LoanServicingService
from src.services.notifications.service import NotificationService
from src.services.pricing.service import PricingService
from src.services.refinancing.service import RefinancingService
from src.services.retrieval.service import RetrievalService
from src.services.workflow.service import WorkflowService
from src.storage.application_db.repository import Repository


@dataclass(frozen=True)
class Container:
    catalogue: Catalogue
    repository: Repository
    sessions: DemoSessions
    customers: CustomerService
    pricing: PricingService
    affordability: AffordabilityPreviewService
    evidence_eligibility: BackendEligibilityService
    documents: DocumentService
    workflow: WorkflowService
    reviews: HumanReviewService
    servicing: LoanServicingService
    refinancing: RefinancingService
    retrieval: RetrievalService
    notifications: NotificationService
    conversations: ConversationService

    @classmethod
    def build(cls, settings: Settings) -> "Container":
        catalogue = Catalogue.load(settings.config_root)
        repository = Repository(settings.database_path)
        repository.initialize(catalogue.fixtures)
        pricing = PricingService(catalogue)
        affordability = AffordabilityPreviewService(catalogue, pricing)
        documents = DocumentService(catalogue)
        return cls(
            catalogue=catalogue, repository=repository,
            sessions=DemoSessions(catalogue.fixtures.accounts, settings.session_hours),
            customers=CustomerService(repository), pricing=pricing, affordability=affordability,
            evidence_eligibility=BackendEligibilityService(repository, settings.config_root / "config/rules/eligibility_reference_ro.json"), documents=documents,
            workflow=WorkflowService(repository, catalogue, pricing, affordability, documents),
            reviews=HumanReviewService(repository), servicing=LoanServicingService(repository, catalogue),
            refinancing=RefinancingService(repository, catalogue), retrieval=RetrievalService(catalogue),
            notifications=NotificationService(repository), conversations=ConversationService(repository),
        )

    def preview(self, context: CallContext, input: LoanScenarioInput) -> AffordabilityPreview:
        require_role(context.actor, Role.CUSTOMER)
        with self.repository.transaction() as unit:
            assessment = self.affordability.assess(unit, context.actor, input)
            record_audit(unit, context, "AFFORDABILITY_PREVIEW_CALCULATED", context.actor.id, "Synthetic declared-income preview only")
            return assessment

    def audit(self, actor: Actor) -> list[AuditEvent]:
        with self.repository.read() as unit:
            return unit.audit(actor)

    def snapshot(self, actor: Actor) -> Snapshot:
        with self.repository.read() as unit:
            applications = [visible_application(app, actor) for app in unit.applications(actor)]
            customer_id = actor.id if actor.role == Role.CUSTOMER else (applications[0].customer_id if applications else None)
            return Snapshot(
                actor=actor, customer=unit.customer(customer_id) if customer_id else None,
                products=list(self.catalogue.products), policies=list(self.catalogue.policies),
                loans=unit.loans(customer_id) if customer_id else [], applications=applications,
                messages=unit.messages(actor.id) if actor.role == Role.CUSTOMER else [],
                notifications=unit.notifications(actor.id) if actor.role == Role.CUSTOMER else [],
                audit=unit.audit(actor), consent=unit.consent(customer_id) if customer_id else None,
            )