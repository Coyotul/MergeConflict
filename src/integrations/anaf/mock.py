"""Synthetic income verification; never connects to ANAF."""

from src.integrations.bank.synthetic import SyntheticVerificationProvider
from src.models.eligibility import EvidenceSource


class SyntheticAnafProvider(SyntheticVerificationProvider):
    source = EvidenceSource.ANAF