"""Ports owned by eligibility; concrete synthetic/storage adapters live elsewhere."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol

from src.models.eligibility import (
    ApplicationSnapshot, AuditEvent, EligibilityAssessment, EvidenceSource,
    ProviderQuery, VerificationResult,
)


class ApplicationRepository(Protocol):
    def get_application(self, application_id: str) -> ApplicationSnapshot | None: ...


class VerificationProvider(Protocol):
    source: EvidenceSource

    async def verify(self, query: ProviderQuery) -> VerificationResult[Any] | dict[str, Any]: ...


@dataclass(frozen=True)
class StoredAssessment:
    request_fingerprint: str
    input_fingerprint: str
    assessment: EligibilityAssessment


class AssessmentRepository(Protocol):
    def get_assessment(self, assessment_id: str) -> EligibilityAssessment | None: ...

    def get_run(self, actor_id: str, key: str) -> StoredAssessment | None: ...

    def save_run(
        self, actor_id: str, key: str, request_fingerprint: str,
        input_fingerprint: str, assessment: EligibilityAssessment, audit: AuditEvent,
    ) -> EligibilityAssessment: ...

    def append_audit(self, event: AuditEvent) -> None: ...

    def healthcheck(self) -> bool: ...


# Kept callable/injected to make time deterministic in tests and orchestration.
Clock = Callable[[], datetime]