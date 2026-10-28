"""Reusable synthetic fixtures and service factory for standard-library unittest."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.eligibility_demo import load_reference_fixture
from src.integrations.anaf.mock import SyntheticAnafProvider
from src.integrations.credit_bureau.mock import SyntheticCreditBureauProvider
from src.integrations.customer_loans.mock import SyntheticCustomerLoansProvider
from src.models.eligibility import (
    ApplicationSnapshot, CreditBureauData, EligibilityCheckRequest, EvidenceSource,
    IncomeVerificationData, LoanVerificationData, VerificationResult,
)
from src.security.eligibility import ActorContext, ActorRole
from src.services.eligibility.policy import EligibilityPolicy, load_policy
from src.services.eligibility.service import EligibilityService
from src.storage.application_db.eligibility import SqliteAssessmentRepository
from src.storage.application_db.synthetic_applications import SyntheticApplicationRepository


NOW = load_reference_fixture().reference_time
CUSTOMER = ActorContext(
    "test-customer", ActorRole.CUSTOMER, customer_id="demo-customer",
    permissions=frozenset({"eligibility:assess", "eligibility:read"}),
)
REVIEWER = ActorContext(
    "test-reviewer", ActorRole.REVIEWER,
    permissions=frozenset({"eligibility:assess", "eligibility:read"}),
    assigned_application_ids=frozenset({"demo-app-eligible"}),
)


def application(**changes: Any) -> ApplicationSnapshot:
    raw = load_reference_fixture().application.model_dump(mode="json")
    raw.update(changes)
    return ApplicationSnapshot.model_validate(raw)


def changed_model(model: Any, **changes: Any) -> Any:
    raw = model.model_dump(mode="json")
    raw.update(changes)
    return type(model).model_validate(raw)


def provider_records() -> dict[EvidenceSource, dict[str, Any]]:
    return deepcopy(load_reference_fixture().verifications)


def verification_models(records: dict[EvidenceSource, dict[str, Any]] | None = None) -> dict:
    records = records or provider_records()
    return {
        EvidenceSource.ANAF: VerificationResult[IncomeVerificationData].model_validate(records[EvidenceSource.ANAF]),
        EvidenceSource.CREDIT_BUREAU: VerificationResult[CreditBureauData].model_validate(records[EvidenceSource.CREDIT_BUREAU]),
        EvidenceSource.INTERNAL_LOANS: VerificationResult[LoanVerificationData].model_validate(records[EvidenceSource.INTERNAL_LOANS]),
    }


def request(key: str = "test-key-0001", scenario: bool = True) -> EligibilityCheckRequest:
    return EligibilityCheckRequest(
        application_id="demo-app-eligible", pricing_scenario_id="demo-quote-eligible" if scenario else None,
        idempotency_key=key,
    )


class MutableApplicationRepository(SyntheticApplicationRepository):
    """Test-only upstream repository to simulate edits while a check is in flight."""

    def replace(self, item: ApplicationSnapshot) -> None:
        self._applications[item.application_id] = item


@dataclass
class ServiceFixture:
    service: EligibilityService
    applications: MutableApplicationRepository
    assessments: SqliteAssessmentRepository
    providers: dict


def service_fixture(
    path: Path, item: ApplicationSnapshot | None = None,
    records: dict[EvidenceSource, dict[str, Any]] | None = None,
    policies: tuple[EligibilityPolicy, ...] | None = None, **provider_options: Any,
) -> ServiceFixture:
    item = item or application()
    records = records or provider_records()
    providers = {
        EvidenceSource.ANAF: SyntheticAnafProvider({item.customer_id: records[EvidenceSource.ANAF]}, **provider_options),
        EvidenceSource.CREDIT_BUREAU: SyntheticCreditBureauProvider({item.customer_id: records[EvidenceSource.CREDIT_BUREAU]}, **provider_options),
        EvidenceSource.INTERNAL_LOANS: SyntheticCustomerLoansProvider({item.customer_id: records[EvidenceSource.INTERNAL_LOANS]}, **provider_options),
    }
    applications = MutableApplicationRepository((item,))
    assessments = SqliteAssessmentRepository(path)
    service = EligibilityService(applications, assessments, tuple(providers.values()), policies or (load_policy(),), lambda: NOW)
    return ServiceFixture(service, applications, assessments, providers)