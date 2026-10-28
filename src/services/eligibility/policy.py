"""Validated, effective-dated policy snapshots; no rules are sourced from an LLM."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.models.eligibility import (
    AgePolicyCategory, ContractModel, EvidenceSource, Identifier, PositiveInt,
    PositiveMoney, Ratio, SourceReference,
)


DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[3]
    / "config" / "rules" / "eligibility_reference_ro.json"
)


PolicySource = SourceReference


class EligibilityPolicy(ContractModel):
    policy_id: Identifier
    version: Identifier
    product_id: Identifier
    effective_from: date
    effective_to: date
    minimum_age_years: PositiveInt
    maximum_maturity_age_years: dict[AgePolicyCategory, PositiveInt]
    minimum_amount_ron: PositiveMoney
    maximum_amount_ron: PositiveMoney
    minimum_term_months: PositiveInt
    maximum_term_months: Annotated[int, Field(strict=True, gt=0, le=60)]
    minimum_employment_months: PositiveInt
    minimum_successive_renewals: PositiveInt
    minimum_net_income_ron: PositiveMoney
    maximum_debt_to_income_ratio: Ratio
    revolving_limit_factor: Ratio
    evidence_max_age_days: dict[EvidenceSource, PositiveInt]
    income_period_max_age_days: PositiveInt
    provider_timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=30)]
    provider_max_attempts: Annotated[int, Field(strict=True, ge=1, le=3)]
    sources: tuple[PolicySource, ...]
    rule_sources: dict[Identifier, tuple[Identifier, ...]]
    assumptions: tuple[str, ...]
    simulated: Literal[True] = True

    @model_validator(mode="after")
    def coherent_policy(self) -> "EligibilityPolicy":
        if self.effective_to < self.effective_from:
            raise ValueError("Policy effective dates are inverted.")
        if self.minimum_amount_ron > self.maximum_amount_ron:
            raise ValueError("Policy amount bounds are inverted.")
        if self.minimum_term_months > self.maximum_term_months:
            raise ValueError("Policy term bounds are inverted.")
        if not Decimal("0") < self.maximum_debt_to_income_ratio <= Decimal("0.40"):
            raise ValueError("Ordinary RON personal-loan DTI limit must be in (0, .40].")
        if self.revolving_limit_factor < Decimal("0.03"):
            raise ValueError("Revolving facility factor must be at least .03.")
        expected = {AgePolicyCategory.FEMALE_REFERENCE, AgePolicyCategory.MALE_REFERENCE}
        if set(self.maximum_maturity_age_years) != expected:
            raise ValueError("Configure both published age categories, not an inferred default.")
        if any(age < self.minimum_age_years for age in self.maximum_maturity_age_years.values()):
            raise ValueError("Maturity age cannot be below minimum age.")
        if set(self.evidence_max_age_days) != set(EvidenceSource):
            raise ValueError("Every evidence source needs a freshness window.")
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Duplicate source identifiers.")
        required = {
            "POLICY", "PRODUCT", "AGE", "EMPLOYMENT", "IDENTITY", "INCOME",
            "CREDIT_HISTORY", "OBLIGATIONS", "AFFORDABILITY", "AUTHORIZATION",
            "VERIFICATION",
        }
        if not required.issubset(self.rule_sources):
            raise ValueError("All rule groups require provenance.")
        for ids in self.rule_sources.values():
            if not ids or not set(ids).issubset(source_ids):
                raise ValueError("Rule references must resolve to nonempty policy sources.")
        return self

    def is_effective(self, on_date: date) -> bool:
        return self.effective_from <= on_date <= self.effective_to

    def source_ids_for(self, rule: str) -> tuple[str, ...]:
        return self.rule_sources[rule]

    def digest(self) -> str:
        content = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> EligibilityPolicy:
    return EligibilityPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def select_policy(
    policies: tuple[EligibilityPolicy, ...], product_id: str, on_date: date
) -> EligibilityPolicy:
    """Do not silently choose the newest when effective versions conflict."""
    matches = [p for p in policies if p.product_id == product_id and p.is_effective(on_date)]
    if len(matches) != 1:
        raise ValueError("Exactly one effective policy must match the product and date.")
    return matches[0]