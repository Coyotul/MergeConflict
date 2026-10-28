"""Map persisted workflow records to the existing eligibility repository port.

Missing profile/authorizations remain missing; metadata never becomes VERIFIED.
The reference service, not this adapter, owns eligibility policy/rule behavior.
"""

from src.models.banking import DocumentKind
from src.models.eligibility import (
    ApplicantProfile,
    ApplicationSnapshot,
    EvidenceReference,
    EvidenceSource,
    EvidenceStatus,
    LoanRequest,
    PricingScenario,
    WorkflowState,
)
from src.storage.application_db.repository import Repository


class WorkflowEligibilityRepository:
    def __init__(self, repository: Repository):
        self.repository = repository

    def get_application(self, application_id: str) -> ApplicationSnapshot | None:
        with self.repository.read() as unit:
            application = unit.application_for_eligibility(application_id)
        if application is None:
            return None
        identity = next((d for d in application.documents if d.kind == DocumentKind.IDENTITY and d.status == "FORMAT_ACCEPTED"), None)
        identity_evidence = None
        if identity is not None:
            identity_evidence = EvidenceReference(
                evidence_id=f"metadata-identity-{application.id}", source=EvidenceSource.DOCUMENT,
                recorded_at=identity.uploaded_at or application.updated_at, status=EvidenceStatus.UNVERIFIED,
                source_version="metadata-only-v1", document_kind="IDENTITY", simulated=True,
            )
        scenario = PricingScenario(
            scenario_id=application.pricing_scenario_id or f"quote-{application.id}",
            application_id=application.id, customer_id=application.customer_id,
            principal_ron=application.quote.amount, financed_costs_ron="0.00",
            term_months=application.months, annual_interest_percent=application.quote.annual_rate,
            monthly_fee_ron="0.00", monthly_insurance_ron=application.quote.monthly_insurance,
            evidence=EvidenceReference(
                evidence_id=f"pricing-{application.id}", source=EvidenceSource.PRICING,
                recorded_at=application.created_at, status=EvidenceStatus.VERIFIED,
                source_version=application.policy_version, simulated=True,
            ),
        )
        # Explicit product mapping; unsupported products are not forced into personal-loan rules.
        product_id = "personal_loan_ron" if application.product_id == "personal" else application.product_id
        return ApplicationSnapshot(
            application_id=application.id, customer_id=application.customer_id, revision=application.revision,
            workflow_state=WorkflowState(application.status.value),
            request=LoanRequest(product_id=product_id, amount_ron=application.amount, term_months=application.months),
            profile=ApplicantProfile(customer_id=application.customer_id), profile_evidence=None,
            identity_document=identity_evidence, declared_net_income_ron=application.customer.monthly_income,
            authorizations=(), pricing_scenarios=(scenario,), simulated=True,
        )