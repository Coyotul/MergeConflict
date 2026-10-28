"""Dictionary-only ANAF test double; the demo composition uses the SQLite adapter."""

from src.integrations.bank.synthetic import SyntheticVerificationProvider
from src.models.eligibility import EvidenceSource


class SyntheticAnafProvider(SyntheticVerificationProvider):
    source = EvidenceSource.ANAF