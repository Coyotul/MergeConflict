"""Synthetic banking document generation package."""

from src.services.document_generation.bank_statement import generate_bank_statement
from src.services.document_generation.generator import (
    DEFAULT_OUTPUT_DIR,
    PRESET_PROFILES,
    generate_document_suite,
    generate_documents_for_profile,
    load_profile_from_db,
)
from src.services.document_generation.id_card import generate_identity_card
from src.services.document_generation.income_certificate import generate_income_certificate
from src.services.document_generation.models import (
    CustomerDocumentProfile,
    ExistingLoanInfo,
    SalaryMonth,
    TransactionRow,
)

__all__ = [
    "generate_identity_card",
    "generate_income_certificate",
    "generate_bank_statement",
    "generate_documents_for_profile",
    "generate_document_suite",
    "load_profile_from_db",
    "CustomerDocumentProfile",
    "ExistingLoanInfo",
    "SalaryMonth",
    "TransactionRow",
    "PRESET_PROFILES",
    "DEFAULT_OUTPUT_DIR",
]
