"""Wire/domain contracts for synthetic preliminary personal-loan assessment.

HTTP/tool callers supply identifiers, never the trusted evidence models below.
Money is encoded as decimal strings; binary floating-point inputs are rejected.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    model_validator,
)


def _exact_decimal(value: object) -> object:
    if isinstance(value, (float, bool)):
        raise ValueError("Use decimal strings or integers, not floats or booleans.")
    return value


def _synthetic_only(value: object) -> object:
    if value is not True:
        raise ValueError("This boundary requires an explicit synthetic=true marker.")
    return value


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
Money = Annotated[
    Decimal,
    BeforeValidator(_exact_decimal),
    Field(ge=0, max_digits=14, decimal_places=2),
]
PositiveMoney = Annotated[
    Decimal,
    BeforeValidator(_exact_decimal),
    Field(gt=0, max_digits=14, decimal_places=2),
]
Rate = Annotated[
    Decimal,
    BeforeValidator(_exact_decimal),
    Field(ge=0, le=100, max_digits=9, decimal_places=6),
]
Ratio = Annotated[
    Decimal, BeforeValidator(_exact_decimal),
    Field(ge=0, le=1, max_digits=12, decimal_places=9),
]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
SyntheticFlag = Annotated[Literal[True], BeforeValidator(_synthetic_only)]


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_default=True,
        str_strip_whitespace=True, allow_inf_nan=False, revalidate_instances="always",
    )


class AssessmentStatus(str, Enum):
    SATISFIED = "PRELIMINARY_REQUIREMENTS_SATISFIED"
    NOT_SATISFIED = "PRELIMINARY_REQUIREMENTS_NOT_SATISFIED"
    INFORMATION_REQUIRED = "ADDITIONAL_INFORMATION_REQUIRED"
    REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class RuleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INFORMATION_REQUIRED = "INFORMATION_REQUIRED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class WorkflowState(str, Enum):
    DRAFT = "DRAFT"
    AWAITING_DOCUMENTS = "AWAITING_DOCUMENTS"
    PRELIMINARY_ASSESSMENT = "PRELIMINARY_ASSESSMENT"
    READY_FOR_SUBMISSION = "READY_FOR_SUBMISSION"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    MORE_INFORMATION_REQUIRED = "MORE_INFORMATION_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    AWAITING_SIGNATURE = "AWAITING_SIGNATURE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EvidenceSource(str, Enum):
    CUSTOMER_PROFILE = "CUSTOMER_PROFILE"
    DOCUMENT = "DOCUMENT"
    ANAF = "ANAF"
    CREDIT_BUREAU = "CREDIT_BUREAU"
    INTERNAL_LOANS = "INTERNAL_LOANS"
    PRICING = "PRICING"


class EvidenceStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    INVALID = "INVALID"


class EvidenceReference(ContractModel):
    evidence_id: Identifier
    source: EvidenceSource
    recorded_at: AwareDatetime
    status: EvidenceStatus
    source_version: Identifier
    document_kind: Literal["IDENTITY", "INCOME", "BANK_STATEMENT"] | None = None
    expires_on: date | None = None
    simulated: SyntheticFlag


class AgePolicyCategory(str, Enum):
    FEMALE_REFERENCE = "FEMALE_REFERENCE"
    MALE_REFERENCE = "MALE_REFERENCE"
    UNSPECIFIED = "UNSPECIFIED"


class IncomeKind(str, Enum):
    SALARY = "SALARY"
    PENSION = "PENSION"
    SELF_EMPLOYED = "SELF_EMPLOYED"
    RENTAL = "RENTAL"
    DIVIDENDS = "DIVIDENDS"
    FOREIGN_SALARY = "FOREIGN_SALARY"
    OTHER = "OTHER"


class EmploymentContract(str, Enum):
    INDEFINITE = "INDEFINITE"
    FIXED_TERM = "FIXED_TERM"


class ApplicantProfile(ContractModel):
    customer_id: Identifier
    birth_date: date | None = None
    age_policy_category: AgePolicyCategory = AgePolicyCategory.UNSPECIFIED
    income_kind: IncomeKind | None = None
    employment_start_date: date | None = None
    employment_contract: EmploymentContract | None = None
    employment_end_date: date | None = None
    successive_contract_renewals: NonNegativeInt | None = None


class LoanRequest(ContractModel):
    product_id: Identifier
    amount_ron: PositiveMoney
    term_months: Annotated[int, Field(strict=True, ge=1, le=600)]


class RepaymentType(str, Enum):
    EQUAL = "EQUAL"
    DECREASING = "DECREASING"
    UNEQUAL = "UNEQUAL"


class PricingScenario(ContractModel):
    scenario_id: Identifier
    application_id: Identifier
    customer_id: Identifier
    principal_ron: PositiveMoney
    financed_costs_ron: Money = Decimal("0")
    term_months: Annotated[int, Field(strict=True, ge=1, le=600)]
    annual_interest_percent: Rate
    repayment_type: RepaymentType = RepaymentType.EQUAL
    monthly_fee_ron: Money = Decimal("0")
    monthly_insurance_ron: Money = Decimal("0")
    evidence: EvidenceReference
    indicative: Literal[True] = True


class AuthorizationScope(str, Enum):
    BUREAU_PRECHECK = "BUREAU_PRECHECK"
    INCOME_VERIFICATION = "INCOME_VERIFICATION"
    INTERNAL_LOANS = "INTERNAL_LOANS"


class LegalBasis(str, Enum):
    CONSENT = "CONSENT"
    LEGITIMATE_INTEREST = "LEGITIMATE_INTEREST"
    CONTRACT = "CONTRACT"


class AuthorizationRecord(ContractModel):
    authorization_id: Identifier
    customer_id: Identifier
    scope: AuthorizationScope
    legal_basis: LegalBasis
    recorded_at: AwareDatetime
    notice_version: Identifier
    notice_acknowledged: StrictBool
    consent_recorded_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    revoked_at: AwareDatetime | None = None
    simulated: SyntheticFlag


class ApplicationSnapshot(ContractModel):
    application_id: Identifier
    customer_id: Identifier
    revision: PositiveInt
    workflow_state: WorkflowState
    request: LoanRequest
    profile: ApplicantProfile
    profile_evidence: EvidenceReference | None = None
    identity_document: EvidenceReference | None = None
    declared_net_income_ron: Money | None = None
    authorizations: tuple[AuthorizationRecord, ...] = ()
    pricing_scenarios: tuple[PricingScenario, ...] = ()
    simulated: SyntheticFlag

    @model_validator(mode="after")
    def unique_records(self) -> "ApplicationSnapshot":
        if self.profile.customer_id != self.customer_id:
            raise ValueError("Profile must belong to the application's customer.")
        scopes = [item.scope for item in self.authorizations]
        if len(scopes) != len(set(scopes)):
            raise ValueError("Only one current authorization per scope is permitted.")
        scenarios = [item.scenario_id for item in self.pricing_scenarios]
        if len(scenarios) != len(set(scenarios)):
            raise ValueError("Pricing scenario identifiers must be unique.")
        return self


class DebtKind(str, Enum):
    INSTALLMENT = "INSTALLMENT"
    REVOLVING = "REVOLVING"


class DebtObligation(ContractModel):
    """Canonical liability_id must be reconciled by the bank's adapter mapping."""

    liability_id: Identifier
    kind: DebtKind
    currency: Literal["RON", "EUR", "USD"] = "RON"
    active: StrictBool = True
    monthly_payment: Money | None = None
    maximum_monthly_payment: Money | None = None
    credit_limit: Money | None = None
    repayment_type: RepaymentType = RepaymentType.EQUAL


class PaymentIncident(ContractModel):
    incident_id: Identifier
    days_past_due: PositiveInt
    amount_ron: Money
    reported_on: date
    resolved: StrictBool


class InquiryPurpose(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    CREDIT_APPLICATION = "CREDIT_APPLICATION"


class IncomeBasis(str, Enum):
    MONTHLY_SALARY = "MONTHLY_SALARY"
    ANNUAL_AVERAGE = "ANNUAL_AVERAGE"


class IncomeVerificationData(ContractModel):
    customer_id: Identifier
    income_kind: IncomeKind
    net_monthly_income_ron: Money
    period_end: date
    recurring: StrictBool
    income_basis: IncomeBasis = IncomeBasis.MONTHLY_SALARY
    reference_date: date | None = None
    fiscal_year: Annotated[int, Field(strict=True, ge=1, le=9999)] | None = None
    reported_income_types: tuple[Literal[
        "SALARY", "INDEPENDENT_ACTIVITY", "PENSION", "SOCIAL_INSURANCE",
        "RENTAL", "INVESTMENT", "OTHER",
    ], ...] = ()
    observed_salary_months: tuple[date, ...] = ()

    @model_validator(mode="after")
    def coherent_income_period(self) -> "IncomeVerificationData":
        if self.reference_date is not None and self.period_end > self.reference_date:
            raise ValueError("Income period cannot extend beyond the source reporting date.")
        if self.income_basis == IncomeBasis.ANNUAL_AVERAGE:
            if self.fiscal_year is None or self.recurring:
                raise ValueError("Annual-average evidence needs its year and cannot assert current recurring salary.")
            if self.period_end != date(self.fiscal_year, 12, 31):
                raise ValueError("Annual-average evidence must preserve the completed fiscal-year end.")
            if self.reference_date is not None and self.fiscal_year >= self.reference_date.year:
                raise ValueError("Annual income requires a completed fiscal year.")
        months = self.observed_salary_months
        if len(months) != len(set(months)) or any(month.day != 1 for month in months):
            raise ValueError("Salary evidence needs distinct first-of-month periods.")
        if any(month > self.period_end for month in months):
            raise ValueError("Observed salary month is after the income period.")
        return self


class LoanVerificationData(ContractModel):
    customer_id: Identifier
    obligations: tuple[DebtObligation, ...]
    complete: StrictBool

    @model_validator(mode="after")
    def unique_liabilities(self) -> "LoanVerificationData":
        ids = [debt.liability_id for debt in self.obligations]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate liabilities within one report are invalid.")
        return self


class CreditBureauData(LoanVerificationData):
    inquiry_purpose: InquiryPurpose
    fico_score: Annotated[int, Field(strict=True, ge=300, le=850)] | None = None
    no_credit_history: StrictBool
    has_enforced_loans: StrictBool | None
    has_large_repeated_delays: StrictBool | None
    disputed: StrictBool = False
    payment_incidents: tuple[PaymentIncident, ...] = ()

    @model_validator(mode="after")
    def consistent_history(self) -> "CreditBureauData":
        if self.no_credit_history and (
            self.obligations or self.payment_incidents or self.has_enforced_loans
            or self.has_large_repeated_delays
        ):
            raise ValueError("A no-history report cannot contain credit history.")
        return self


class VerificationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    PENDING = "PENDING"


DataT = TypeVar("DataT")


class VerificationResult(ContractModel, Generic[DataT]):
    provider: EvidenceSource
    customer_id: Identifier
    status: VerificationStatus
    data: DataT | None = None
    evidence: EvidenceReference | None = None
    simulated: SyntheticFlag

    @model_validator(mode="after")
    def valid_envelope(self) -> "VerificationResult[DataT]":
        if self.status == VerificationStatus.SUCCESS:
            if self.data is None or self.evidence is None:
                raise ValueError("Successful verification needs data and provenance.")
        elif self.data is not None or self.evidence is not None:
            raise ValueError("Unsuccessful verification cannot contain usable evidence.")
        return self


class ProviderQuery(ContractModel):
    customer_id: Identifier
    authorization_id: Identifier
    correlation_id: Identifier
    inquiry_purpose: Literal[InquiryPurpose.PRELIMINARY] = InquiryPurpose.PRELIMINARY


class RuleCheck(ContractModel):
    rule_id: Identifier
    status: RuleStatus
    reason_code: Identifier
    message: Annotated[str, Field(min_length=1, max_length=600)]
    evidence_ids: tuple[Identifier, ...] = ()
    source_ids: tuple[Identifier, ...] = ()


class FinancialAssessment(ContractModel):
    verified_net_income_ron: Money
    existing_monthly_debt_ron: Money
    proposed_monthly_debt_ron: Money
    total_monthly_debt_ron: Money
    debt_to_income_ratio: Annotated[Decimal, BeforeValidator(_exact_decimal), Field(ge=0)]
    maximum_debt_to_income_ratio: Ratio
    remaining_installment_capacity_ron: Money
    indicative: Literal[True] = True


class EligibilityCheckRequest(ContractModel):
    application_id: Identifier
    pricing_scenario_id: Identifier | None = None
    idempotency_key: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{8,128}$")]


class AuditEvent(ContractModel):
    event_id: Identifier
    actor_id: Identifier
    action: Literal["eligibility.assessed", "eligibility.access_denied"]
    application_id: Identifier
    assessment_id: Identifier | None = None
    timestamp: AwareDatetime
    result: Identifier
    correlation_id: Identifier
    reason_codes: tuple[Identifier, ...] = ()
    simulated: Literal[True] = True


class PolicyReference(ContractModel):
    policy_id: Identifier
    version: Identifier
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    effective_from: date
    effective_to: date


class SourceReference(ContractModel):
    source_id: Identifier
    classification: Literal["REGULATORY", "PUBLIC_BANK_REFERENCE", "SYNTHETIC_ASSUMPTION"]
    title: str
    url: HttpUrl | None = None
    retrieved_on: date
    section: str

    @model_validator(mode="after")
    def public_source_url(self) -> "SourceReference":
        if self.classification != "SYNTHETIC_ASSUMPTION" and self.url is None:
            raise ValueError("Public/regulatory sources require a URL.")
        if self.url is not None and self.url.scheme != "https":
            raise ValueError("Source URLs must use HTTPS.")
        return self


class EligibilityAssessment(ContractModel):
    assessment_id: Identifier
    application_id: Identifier
    customer_id: Identifier
    status: AssessmentStatus
    assessed_at: AwareDatetime
    correlation_id: Identifier
    policy: PolicyReference
    checks: tuple[RuleCheck, ...]
    financial_assessment: FinancialAssessment | None = None
    evidence: tuple[EvidenceReference, ...] = ()
    source_urls: tuple[str, ...] = ()
    source_references: tuple[SourceReference, ...] = ()
    assumptions: tuple[str, ...] = ()
    final_credit_decision: Literal[False] = False
    human_review_required: Literal[True] = True
    simulated: Literal[True] = True
    disclaimer: str = (
        "Synthetic preliminary assessment only; not a bank offer, loan approval "
        "or rejection. Every submitted application requires authorized human review."
    )