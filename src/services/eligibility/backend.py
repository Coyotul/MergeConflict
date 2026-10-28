"""Integrate the merged evidence-based service with authenticated backend records."""

from pathlib import Path

from src.core.context import CallContext
from src.integrations.anaf.mock import SyntheticAnafProvider
from src.integrations.credit_bureau.mock import SyntheticCreditBureauProvider
from src.integrations.customer_loans.mock import SyntheticCustomerLoansProvider
from src.models.banking import Role
from src.models.eligibility import EligibilityAssessment, EligibilityCheckRequest
from src.models.requests import EligibilityRunInput
from src.security.eligibility import ActorContext, ActorRole
from src.services.eligibility.policy import load_policy
from src.services.eligibility.service import EligibilityService
from src.storage.application_db.eligibility import SqliteAssessmentRepository
from src.storage.application_db.eligibility_bridge import WorkflowEligibilityRepository
from src.storage.application_db.repository import Repository


class BackendEligibilityService:
    def __init__(self, repository: Repository, policy_path: Path):
        self.repository = repository
        # Keep upstream immutable assessment/audit persistence in the same local DB,
        # without mixing its replay/snapshot rules with workflow-command snapshots.
        assessments = SqliteAssessmentRepository(repository.path)
        self.service = EligibilityService(
            WorkflowEligibilityRepository(repository), assessments,
            (SyntheticAnafProvider({}), SyntheticCreditBureauProvider({}), SyntheticCustomerLoansProvider({})),
            (load_policy(policy_path),),
        )

    def principal(self, context: CallContext) -> ActorContext:
        with self.repository.read() as unit:
            applications = unit.applications(context.actor)
        return ActorContext(
            actor_id=context.actor.id,
            role=ActorRole.CUSTOMER if context.actor.role == Role.CUSTOMER else ActorRole.REVIEWER,
            customer_id=context.actor.id if context.actor.role == Role.CUSTOMER else None,
            assigned_application_ids=frozenset(app.id for app in applications),
            permissions=frozenset({"eligibility:assess", "eligibility:read"}),
        )

    async def run(self, context: CallContext, input: EligibilityRunInput) -> EligibilityAssessment:
        request = EligibilityCheckRequest(
            application_id=input.application_id, pricing_scenario_id=input.pricing_scenario_id,
            idempotency_key=str(input.idempotency_key),
        )
        return await self.service.assess(request, self.principal(context), context.correlation_id)

    def get(self, context: CallContext, assessment_id: str) -> EligibilityAssessment:
        return self.service.get_assessment(assessment_id, self.principal(context))