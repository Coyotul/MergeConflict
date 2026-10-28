"""Structured document field extractors."""

from src.parsers.extraction.bank_statement_extractor import BankStatementExtractor
from src.parsers.extraction.id_card_extractor import IdCardExtractor
from src.parsers.extraction.income_certificate_extractor import IncomeCertificateExtractor

__all__ = [
    "IdCardExtractor",
    "IncomeCertificateExtractor",
    "BankStatementExtractor",
]
