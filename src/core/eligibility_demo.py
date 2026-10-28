"""Explicit synthetic composition root; replace ports, not domain rules, for live use."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from src.integrations.anaf.mock import SyntheticAnafProvider
from src.integrations.credit_bureau.mock import SyntheticCreditBureauProvider
from src.integrations.customer_loans.mock import SyntheticCustomerLoansProvider
from src.models.eligibility import ApplicationSnapshot, ContractModel, EvidenceSource
from src.services.eligibility.interfaces import Clock
from src.services.eligibility.policy import load_policy
from src.services.eligibility.service import EligibilityService, utc_now
from src.storage.application_db.eligibility import SqliteAssessmentRepository
from src.storage.application_db.synthetic_applications import SyntheticApplicationRepository


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "data" / "synthetic" / "applications" / "eligibility_reference.json"
DEFAULT_DATABASE_PATH = ROOT / "data" / "local" / "eligibility-demo.sqlite3"


class ReferenceFixture(ContractModel):
    fixture_id: str
    simulated: Literal[True]
    reference_time: AwareDatetime
    application: ApplicationSnapshot
    # Provider payloads deliberately remain raw until the service validates them.
    verifications: dict[EvidenceSource, dict[str, Any]] = Field(min_length=3, max_length=3)


def load_reference_fixture() -> ReferenceFixture:
    fixture = ReferenceFixture.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))
    if fixture.simulated is not True or set(fixture.verifications) != {
        EvidenceSource.ANAF, EvidenceSource.CREDIT_BUREAU, EvidenceSource.INTERNAL_LOANS,
    }:
        raise ValueError("Only a complete synthetic reference fixture is allowed.")
    return fixture


@dataclass(frozen=True)
class DemoCase:
    application: ApplicationSnapshot
    verifications: dict[EvidenceSource, dict[str, Any]]


def demo_cases() -> tuple[DemoCase, ...]:
    fixture = load_reference_fixture()
    cases = []
    for name in ("eligible", "high-dti", "missing-id", "adverse-history", "bureau-unavailable", "missing-consent"):
        raw = fixture.application.model_dump(mode="json")
        customer_id = "demo-customer" if name == "eligible" else f"demo-customer-{name}"
        application_id = f"demo-app-{name}"
        raw.update(application_id=application_id, customer_id=customer_id)
        raw["profile"]["customer_id"] = customer_id
        for field in ("profile_evidence", "identity_document"):
            raw[field]["evidence_id"] = f"{field}-{customer_id}"
        for authorization in raw["authorizations"]:
            authorization["customer_id"] = customer_id
            authorization["authorization_id"] += f"-{name}"
        quote = raw["pricing_scenarios"][0]
        quote.update(scenario_id=f"demo-quote-{name}", application_id=application_id, customer_id=customer_id)
        quote["evidence"]["evidence_id"] = f"quote-{application_id}"
        verifications = deepcopy(fixture.verifications)
        for source, result in verifications.items():
            result["customer_id"] = customer_id
            result["data"]["customer_id"] = customer_id
            result["evidence"]["evidence_id"] = f"{source.value.lower()}-{customer_id}"
        if name == "high-dti":
            raw["declared_net_income_ron"] = "3000.00"
            verifications[EvidenceSource.ANAF]["data"]["net_monthly_income_ron"] = "3000.00"
        elif name == "missing-id":
            raw["identity_document"] = None
        elif name == "adverse-history":
            verifications[EvidenceSource.CREDIT_BUREAU]["data"]["has_enforced_loans"] = True
        elif name == "bureau-unavailable":
            verifications[EvidenceSource.CREDIT_BUREAU] = {
                "provider": "CREDIT_BUREAU", "customer_id": customer_id,
                "status": "UNAVAILABLE", "simulated": True,
            }
        elif name == "missing-consent":
            raw["authorizations"] = [a for a in raw["authorizations"] if a["scope"] != "INCOME_VERIFICATION"]
        cases.append(DemoCase(ApplicationSnapshot.model_validate(raw), verifications))
    return tuple(cases)


def build_demo_service(
    database_path: Path = DEFAULT_DATABASE_PATH, clock: Clock = utc_now,
) -> EligibilityService:
    cases = demo_cases()
    records = {
        source: {case.application.customer_id: case.verifications[source] for case in cases}
        for source in EvidenceSource if source in cases[0].verifications
    }
    return EligibilityService(
        SyntheticApplicationRepository(tuple(case.application for case in cases)),
        SqliteAssessmentRepository(database_path),
        (SyntheticAnafProvider(records[EvidenceSource.ANAF]),
         SyntheticCreditBureauProvider(records[EvidenceSource.CREDIT_BUREAU]),
         SyntheticCustomerLoansProvider(records[EvidenceSource.INTERNAL_LOANS])),
        (load_policy(),), clock,
    )