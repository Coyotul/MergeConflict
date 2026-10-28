"""Configured preliminary debt-ratio screening, never final credit authority."""

from decimal import Decimal, ROUND_HALF_UP, localcontext

from src.models.banking import Assessment, LoanQuote
from src.models.common import utc_now
from src.services.financial_calculations.engine import value


def assess_affordability(
    income: Decimal, obligations: Decimal, quote: LoanQuote, threshold: Decimal,
    policy_version: str, evidence_references: list[str],
) -> Assessment:
    with localcontext() as context:
        context.prec = 40
        ratio = (value(obligations, "Existing obligations", True) + quote.monthly_payment) / value(income, "Income") * 100
        satisfied = ratio <= threshold
        return Assessment(
            status="PRELIMINARY_REQUIREMENTS_SATISFIED" if satisfied else "MANUAL_REVIEW_REQUIRED",
            debt_ratio=ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), threshold=threshold,
            policy_version=policy_version, assessed_at=utc_now(), evidence_references=evidence_references,
            reason_codes=["DTI_WITHIN_DEMO_THRESHOLD" if satisfied else "DTI_EXCEEDS_DEMO_THRESHOLD", "SYNTHETIC_UNVERIFIED_INPUTS", "HUMAN_REVIEW_REQUIRED"],
            reasons=[
                "Within the configured demo debt-to-income threshold." if satisfied else
                "Exceeds the configured demo threshold; independent manual assessment is needed.",
                "Income, existing loans and documents are synthetic and not externally verified.",
                "Identity, age, employment and credit bureau checks are not implemented. This is not credit approval.",
                "Every application requires an authorized human decision after explicit customer submission.",
            ],
        )