"""Synthetic customer-loan obligations with canonical liability identifiers."""

from src.integrations.bank.synthetic import SyntheticVerificationProvider
from src.models.eligibility import EvidenceSource


class SyntheticCustomerLoansProvider(SyntheticVerificationProvider):
    source = EvidenceSource.INTERNAL_LOANS