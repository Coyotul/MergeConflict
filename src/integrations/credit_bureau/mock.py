"""Synthetic preliminary bureau lookup; never performs a real/score-affecting query."""

from src.integrations.bank.synthetic import SyntheticVerificationProvider
from src.models.eligibility import EvidenceSource


class SyntheticCreditBureauProvider(SyntheticVerificationProvider):
    source = EvidenceSource.CREDIT_BUREAU