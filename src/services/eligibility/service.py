"""Authorized synthetic eligibility coordination; never changes application state."""

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from src.core.eligibility_errors import AccessDenied, EligibilityError, IdempotencyConflict
from src.models.eligibility import (
    ApplicationSnapshot, AuditEvent, AuthorizationScope, CreditBureauData,
    EligibilityAssessment, EligibilityCheckRequest, EvidenceReference,
    EvidenceSource, IncomeVerificationData, InquiryPurpose, LoanVerificationData,
    PolicyReference, ProviderQuery, RuleCheck, RuleStatus, VerificationResult,
    VerificationStatus, WorkflowState,
)
from src.rules.eligibility.engine import (
    affordability_checks, aggregate_status, check, evidence_problem, history_checks,
    identity_check, income_checks, product_checks, profile_checks,
)
from src.security.eligibility import ActorContext, authorization_is_valid, authorize_assessment
from src.services.eligibility.interfaces import (
    ApplicationRepository, AssessmentRepository, Clock, VerificationProvider,
)
from src.services.eligibility.policy import EligibilityPolicy


PROVIDER_SCOPES = {
    EvidenceSource.ANAF: AuthorizationScope.INCOME_VERIFICATION,
    EvidenceSource.CREDIT_BUREAU: AuthorizationScope.BUREAU_PRECHECK,
    EvidenceSource.INTERNAL_LOANS: AuthorizationScope.INTERNAL_LOANS,
}
RESULT_SCHEMAS = {
    EvidenceSource.ANAF: VerificationResult[IncomeVerificationData],
    EvidenceSource.CREDIT_BUREAU: VerificationResult[CreditBureauData],
    EvidenceSource.INTERNAL_LOANS: VerificationResult[LoanVerificationData],
}
PERMITTED_STATES = frozenset({
    WorkflowState.DRAFT, WorkflowState.AWAITING_DOCUMENTS,
    WorkflowState.PRELIMINARY_ASSESSMENT, WorkflowState.READY_FOR_SUBMISSION,
    WorkflowState.PENDING_HUMAN_REVIEW, WorkflowState.MORE_INFORMATION_REQUIRED,
})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class EligibilityService:
    def __init__(
        self, applications: ApplicationRepository, assessments: AssessmentRepository,
        providers: tuple[VerificationProvider, ...], policies: tuple[EligibilityPolicy, ...],
        clock: Clock = utc_now,
    ) -> None:
        if not policies:
            raise ValueError("At least one validated reference policy is required.")
        self.applications = applications
        self.assessments = assessments
        self.providers = {provider.source: provider for provider in providers}
        if len(self.providers) != len(providers) or set(self.providers) != set(PROVIDER_SCOPES):
            raise ValueError("Exactly one synthetic provider per required source is needed.")
        # Detached snapshots prevent caller-owned mutable configuration from changing a run.
        self.policies = tuple(EligibilityPolicy.model_validate_json(p.model_dump_json()) for p in policies)
        self.clock = clock
        # Local demo serialization prevents repeated same-key inquiries within one process.
        # SQLite uniqueness/transactions also guard independent process writers.
        self._lock = asyncio.Lock()

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Eligibility clock must return an aware timestamp.")
        return value.astimezone(timezone.utc)

    def _deny(self, actor: ActorContext, application_id: str, correlation_id: str) -> None:
        self.assessments.append_audit(AuditEvent(
            event_id=str(uuid4()), actor_id=actor.actor_id,
            action="eligibility.access_denied", application_id=application_id,
            timestamp=self._now(), result="ACCESS_DENIED", correlation_id=correlation_id,
        ))
        raise AccessDenied()

    def _application(
        self, application_id: str, actor: ActorContext, correlation_id: str,
        permission: str = "eligibility:assess",
    ) -> ApplicationSnapshot:
        application = self.applications.get_application(application_id)
        if application is None:
            self._deny(actor, application_id, correlation_id)
        try:
            authorize_assessment(actor, application, permission)
        except AccessDenied:
            self._deny(actor, application_id, correlation_id)
        return ApplicationSnapshot.model_validate(application)

    def _input_fingerprint(self, application: ApplicationSnapshot) -> str:
        return fingerprint({
            "application": application.model_dump(mode="json"),
            "policies": sorted(p.digest() for p in self.policies),
        })

    def _policy(
        self, application: ApplicationSnapshot, now: datetime,
    ) -> tuple[EligibilityPolicy, str | None]:
        candidates = [p for p in self.policies if p.product_id == application.request.product_id]
        fallback = sorted(candidates or self.policies, key=lambda p: (p.version, p.digest()))[0]
        active = [p for p in candidates if p.is_effective(now.date())]
        if not candidates:
            return fallback, "UNSUPPORTED_PRODUCT"
        if not active:
            return fallback, "POLICY_NOT_EFFECTIVE"
        if len(active) != 1:
            return fallback, "POLICY_VERSION_CONFLICT"
        return active[0], None

    async def _verify(
        self, source: EvidenceSource, query: ProviderQuery, policy: EligibilityPolicy,
    ) -> VerificationResult[Any]:
        schema = RESULT_SCHEMAS[source]
        provider = self.providers[source]
        result: VerificationResult[Any]
        for attempt in range(policy.provider_max_attempts):
            try:
                raw = await asyncio.wait_for(provider.verify(query), policy.provider_timeout_seconds)
                result = schema.model_validate(raw)
                if (
                    result.provider != source or result.customer_id != query.customer_id
                    or (result.data is not None and result.data.customer_id != query.customer_id)
                    or (result.evidence is not None and result.evidence.source != source)
                    or (isinstance(result.data, CreditBureauData)
                        and result.data.inquiry_purpose != InquiryPurpose.PRELIMINARY)
                ):
                    raise ValueError("Provider ownership, provenance or inquiry purpose mismatch.")
            except TimeoutError:
                result = schema(provider=source, customer_id=query.customer_id, status=VerificationStatus.TIMEOUT, simulated=True)
            except (ValidationError, TypeError, ValueError):
                result = schema(provider=source, customer_id=query.customer_id, status=VerificationStatus.INVALID_RESPONSE, simulated=True)
            except Exception:
                # Provider exception text may contain PII/secrets; never expose or log it.
                result = schema(provider=source, customer_id=query.customer_id, status=VerificationStatus.UNAVAILABLE, simulated=True)
            if result.status not in {VerificationStatus.TIMEOUT, VerificationStatus.UNAVAILABLE}:
                return result
            if attempt + 1 == policy.provider_max_attempts:
                return result
        raise RuntimeError("A validated policy must allow at least one provider attempt.")

    async def assess(
        self, request: EligibilityCheckRequest, actor: ActorContext,
        correlation_id: str | None = None,
    ) -> EligibilityAssessment:
        request = EligibilityCheckRequest.model_validate(request)
        correlation_id = correlation_id or str(uuid4())
        # Correlation identifiers are trusted server-generated values at HTTP/tool boundaries.
        async with self._lock:
            now = self._now()
            application = self._application(request.application_id, actor, correlation_id)
            if application.workflow_state not in PERMITTED_STATES:
                raise EligibilityError("INVALID_WORKFLOW_STATE", "A new assessment is not permitted in this state.", 409)
            request_hash = fingerprint({
                "application_id": request.application_id,
                "pricing_scenario_id": request.pricing_scenario_id,
            })
            input_hash = self._input_fingerprint(application)
            previous = self.assessments.get_run(actor.actor_id, request.idempotency_key)
            if previous is not None:
                if previous.request_fingerprint != request_hash or previous.input_fingerprint != input_hash:
                    raise IdempotencyConflict()
                # Explicit historical replay: original assessed_at, not a fresh verification claim.
                return previous.assessment
            scenario = None
            if request.pricing_scenario_id is not None:
                scenario = next((s for s in application.pricing_scenarios
                                 if s.scenario_id == request.pricing_scenario_id), None)
                if scenario is None:
                    raise EligibilityError("PRICING_SCENARIO_NOT_FOUND", "The scenario is not available for this application.", 404)
            policy, policy_problem = self._policy(application, now)
            checks: list[RuleCheck] = []
            evidence: list[EvidenceReference] = []
            financial = None
            if policy_problem is not None:
                checks.append(check(policy, "POLICY", RuleStatus.REVIEW_REQUIRED, policy_problem,
                                    "Exactly one current product policy is required; no provider inquiry was made."))
            else:
                checks.append(check(policy, "POLICY", RuleStatus.PASS, "POLICY_EFFECTIVE",
                                    "One effective versioned synthetic reference policy applies."))
                checks.extend(product_checks(application, policy))
                checks.extend(profile_checks(application, policy, now))
                checks.append(identity_check(application, policy, now))
                for item in (application.profile_evidence, application.identity_document):
                    if item is not None:
                        evidence.append(item)
                available: dict[EvidenceSource, VerificationResult[Any]] = {}
                tasks = []
                sources = []
                for source, scope in PROVIDER_SCOPES.items():
                    authorization = next((a for a in application.authorizations if a.scope == scope), None)
                    valid = authorization_is_valid(authorization, scope, application.customer_id, now)
                    checks.append(check(
                        policy, "AUTHORIZATION", RuleStatus.PASS if valid else RuleStatus.INFORMATION_REQUIRED,
                        f"{source.value}_AUTHORIZED" if valid else f"{source.value}_AUTHORIZATION_REQUIRED",
                        "Purpose-scoped backend authorization checked; client consent claims are not accepted.",
                    ))
                    if valid:
                        query = ProviderQuery(
                            customer_id=application.customer_id, authorization_id=authorization.authorization_id,
                            correlation_id=correlation_id,
                        )
                        sources.append(source)
                        tasks.append(self._verify(source, query, policy))
                results = await asyncio.gather(*tasks)
                for source, result in zip(sources, results):
                    if result.status != VerificationStatus.SUCCESS:
                        is_missing = result.status in {VerificationStatus.NOT_FOUND, VerificationStatus.NOT_AUTHORIZED}
                        checks.append(check(
                            policy, "VERIFICATION",
                            RuleStatus.INFORMATION_REQUIRED if is_missing else RuleStatus.REVIEW_REQUIRED,
                            f"{source.value}_{result.status.value}",
                            "External verification is incomplete; an empty or unavailable report is never treated as clean.",
                        ))
                        continue
                    evidence.append(result.evidence)
                    problem = evidence_problem(result.evidence, source, policy, now)
                    checks.append(check(
                        policy, "VERIFICATION", RuleStatus.REVIEW_REQUIRED if problem else RuleStatus.PASS,
                        f"{source.value}_{problem}" if problem else f"{source.value}_VERIFIED",
                        "Provider response ownership, provenance and evidence freshness checked.",
                        (result.evidence.evidence_id,),
                    ))
                    if problem is None:
                        available[source] = result
                income_result = available.get(EvidenceSource.ANAF)
                bureau_result = available.get(EvidenceSource.CREDIT_BUREAU)
                internal_result = available.get(EvidenceSource.INTERNAL_LOANS)
                usable_income = None
                if income_result is not None:
                    income_rules = income_checks(application, income_result.data, income_result.evidence, policy, now)
                    checks.extend(income_rules)
                    if not any(c.status in {RuleStatus.REVIEW_REQUIRED, RuleStatus.INFORMATION_REQUIRED} for c in income_rules):
                        usable_income = income_result.data
                if bureau_result is not None:
                    if bureau_result.data.complete:
                        checks.extend(history_checks(bureau_result.data, bureau_result.evidence, policy))
                    else:
                        checks.append(check(policy, "CREDIT_HISTORY", RuleStatus.REVIEW_REQUIRED,
                                            "CREDIT_HISTORY_COMPLETE_REPORT_REQUIRED",
                                            "A partial bureau report cannot establish clean credit history.",
                                            (bureau_result.evidence.evidence_id,)))
                finance_checks, financial = affordability_checks(
                    application, usable_income, bureau_result.data if bureau_result else None,
                    internal_result.data if internal_result else None, scenario, policy, now,
                    tuple(r.evidence.evidence_id for r in available.values()),
                )
                checks.extend(finance_checks)
                if scenario is not None:
                    evidence.append(scenario.evidence)
            unique_evidence: dict[str, EvidenceReference] = {}
            for item in evidence:
                if item.evidence_id in unique_evidence and unique_evidence[item.evidence_id] != item:
                    checks.append(check(policy, "VERIFICATION", RuleStatus.REVIEW_REQUIRED,
                                        "EVIDENCE_ID_CONFLICT", "Evidence identifiers resolve to conflicting records."))
                    financial = None
                unique_evidence[item.evidence_id] = item
            # Recheck trusted state after provider awaits; do not persist stale application snapshots.
            latest = self._application(request.application_id, actor, correlation_id)
            if self._input_fingerprint(latest) != input_hash:
                raise EligibilityError("APPLICATION_CHANGED", "Application evidence changed; retry with a new key.", 409)
            assessment = EligibilityAssessment(
                assessment_id=str(uuid4()), application_id=application.application_id,
                customer_id=application.customer_id, status=aggregate_status(tuple(checks)),
                assessed_at=now, correlation_id=correlation_id,
                policy=PolicyReference(
                    policy_id=policy.policy_id, version=policy.version, sha256=policy.digest(),
                    effective_from=policy.effective_from, effective_to=policy.effective_to,
                ), checks=tuple(checks), financial_assessment=financial,
                evidence=tuple(unique_evidence.values()),
                source_urls=tuple(str(s.url) for s in policy.sources if s.url is not None),
                source_references=policy.sources, assumptions=policy.assumptions,
            )
            audit = AuditEvent(
                event_id=str(uuid4()), actor_id=actor.actor_id, action="eligibility.assessed",
                application_id=application.application_id, assessment_id=assessment.assessment_id,
                timestamp=now, result=assessment.status.value, correlation_id=correlation_id,
                reason_codes=tuple(c.reason_code for c in checks),
            )
            return self.assessments.save_run(
                actor.actor_id, request.idempotency_key, request_hash, input_hash, assessment, audit,
            )

    def get_assessment(self, assessment_id: str, actor: ActorContext) -> EligibilityAssessment:
        correlation_id = str(uuid4())
        # Permission checked before existence to prevent an unpermitted enumeration path.
        if "eligibility:read" not in actor.permissions:
            raise AccessDenied()
        item = self.assessments.get_assessment(assessment_id)
        if item is None:
            raise EligibilityError("ASSESSMENT_NOT_FOUND", "Assessment not found.", 404)
        application = self._application(item.application_id, actor, correlation_id, "eligibility:read")
        if item.customer_id != application.customer_id:
            raise AccessDenied()
        return item