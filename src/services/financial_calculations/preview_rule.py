"""Fictional debt-ratio preview, never evidence-based eligibility or credit authority."""

from decimal import Decimal, ROUND_HALF_UP, localcontext

from src.models.banking import AffordabilityPreview, LoanQuote
from src.models.common import utc_now
from src.services.financial_calculations.engine import value


def assess_affordability(
    income: Decimal, obligations: Decimal, quote: LoanQuote, threshold: Decimal,
    policy_version: str, evidence_references: list[str],
) -> AffordabilityPreview:
    with localcontext() as context:
        context.prec = 40
        ratio = (value(obligations, "Existing obligations", True) + quote.monthly_payment) / value(income, "Income") * 100
        satisfied = ratio <= threshold
        return AffordabilityPreview(
            status="PRELIMINARY_REQUIREMENTS_SATISFIED" if satisfied else "MANUAL_REVIEW_REQUIRED",
            debt_ratio=ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), threshold=threshold,
            policy_version=policy_version, assessed_at=utc_now(), evidence_references=evidence_references,
            reason_codes=["DTI_WITHIN_DEMO_THRESHOLD" if satisfied else "DTI_EXCEEDS_DEMO_THRESHOLD", "SYNTHETIC_UNVERIFIED_INPUTS", "HUMAN_REVIEW_REQUIRED"],
            reasons=[
                "Within the configured demo debt-to-income threshold." if satisfied else
                "Exceeds the configured demo threshold; independent manual assessment is needed.",
                "Income, existing loans and documents are synthetic and not externally verified.",
                "This preview does not check identity, age, employment or credit history. Run the separate evidence-based eligibility tool for those checks.",
                "Every application requires an authorized human decision after explicit customer submission.",
            ],
        )