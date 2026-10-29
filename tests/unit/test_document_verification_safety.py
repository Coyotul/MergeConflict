"""Readable document checks: no guessed fields, bypassed checksums, or repaired evidence."""
from datetime import date

import pytest

from src.models.document_processing import ExtractedIdentity, ExtractedIncome, ExtractedStatement
from src.parsers.extraction.bank_statement_extractor import BankStatementExtractor
from src.parsers.extraction.income_certificate_extractor import IncomeCertificateExtractor
from src.parsers.extraction.amounts import parse_document_amount
from src.parsers.ocr.pdf_extractor import PdfExtractor
from src.parsers.validation.document_validator import DocumentValidator
from tests.fixtures.documents import CNP, identity_text, pdf_bytes, statement_text


def test_pdf_metadata_cannot_impersonate_the_contents_of_a_blank_document():
    forged = pdf_bytes("", metadata={"/Subject": identity_text()})
    assert PdfExtractor.extract_text(forged) == ""


def test_statement_extraction_does_not_repair_an_inconsistent_balance():
    extracted = BankStatementExtractor.extract(statement_text(closing="99.999,00"))
    assert extracted.total_debits == 400
    summary = DocumentValidator.validate_statement(extracted, as_of=date(2026, 10, 28))
    assert not summary.valid
    assert any(rule.code == "STMT_BALANCE_INTEGRITY" and not rule.passed for rule in summary.rules_evaluated)


def test_bank_statement_only_extracts_obligations_when_the_document_supplies_them():
    explicit = BankStatementExtractor.extract(statement_text())
    assert explicit.existing_monthly_obligations == 400
    absent = BankStatementExtractor.extract(statement_text().split("Obligatii lunare")[0])
    assert absent.existing_monthly_obligations is None


def test_missing_statement_period_is_not_treated_as_verified():
    data = ExtractedStatement(iban="RO54RZBR0000060012345678", account_holder="ANA POPESCU")
    summary = DocumentValidator.validate_statement(data, as_of=date(2026, 10, 28))
    assert summary.human_review_required
    assert any(rule.code == "STMT_RECENCY" and not rule.passed for rule in summary.rules_evaluated)


def test_balance_integrity_is_also_checked_for_accounts_starting_at_zero():
    data = ExtractedStatement(
        iban="RO54RZBR0000060012345678", account_holder="ANA POPESCU",
        initial_balance=0, total_credits=6200, total_debits=400, closing_balance=99999,
        period_end=date(2026, 10, 28),
    )
    assert not DocumentValidator.validate_statement(data, as_of=date(2026, 10, 28)).valid


@pytest.mark.parametrize("name", ["ANA IONESCU", "MARIA POPESCU", "POPESCU"])
def test_sharing_only_one_name_is_not_enough_to_pass_cross_document_checks(name):
    identity = ExtractedIdentity(first_name="ANA", last_name="POPESCU", cnp=CNP)
    income = ExtractedIncome(employee_name=name, employee_cnp=CNP, monthly_net_income=6200)
    summary = DocumentValidator.cross_validate(identity=identity, income=income)
    assert not summary.consistent
    assert summary.human_review_required


def test_name_order_differences_are_allowed_when_the_full_name_matches():
    identity = ExtractedIdentity(first_name="ANA", last_name="POPESCU", cnp=CNP)
    income = ExtractedIncome(employee_name=" Popescu  Ana ", employee_cnp=CNP, monthly_net_income=6200)
    summary = DocumentValidator.cross_validate(identity=identity, income=income)
    assert summary.consistent


def test_income_and_statement_are_reconciled_even_when_identity_has_not_arrived():
    income = ExtractedIncome(employee_name="ANA POPESCU", employee_cnp=CNP, monthly_net_income=6200)
    statement = ExtractedStatement(account_holder="MARIA IONESCU", detected_salary_deposit=6200)
    summary = DocumentValidator.cross_validate(income=income, statement=statement)
    assert not summary.consistent


def test_absent_salary_evidence_is_not_claimed_as_a_verified_deposit():
    income = ExtractedIncome(employee_name="ANA POPESCU", employee_cnp=CNP, monthly_net_income=6200)
    statement = ExtractedStatement(account_holder="ANA POPESCU")
    summary = DocumentValidator.cross_validate(income=income, statement=statement)
    assert not summary.salary_verified_in_statement
    assert summary.human_review_required


def test_total_bank_credits_and_generic_transfers_are_not_invented_salary():
    text = statement_text().replace("VIRAMENT SALARIU: +6.200,00 RON", "VIRAMENT - Transfer from savings")
    assert BankStatementExtractor.extract(text).detected_salary_deposit is None


def test_gross_pay_or_random_amounts_do_not_become_monthly_net_income():
    text = "ADEVERINTA DE VENIT\nVenit Brut: 15.000,00 RON\nTax: 4.000,00 RON\n"
    assert IncomeCertificateExtractor.extract(text).monthly_net_income == 0


def test_currency_is_read_from_account_label_even_if_ron_is_elsewhere_in_text():
    text = statement_text() + "\nMoneda cont: EUR\nRON exchange-rate disclosure\n"
    assert BankStatementExtractor.extract(text).currency == "EUR"


def test_annual_tax_income_is_not_misrepresented_as_monthly_salary():
    text = "Venit Net Realizat\n102.000,00 lei\nVenitul net lunar de 8500,00 RON\n"
    assert IncomeCertificateExtractor.extract(text).monthly_net_income == 8500
    assert IncomeCertificateExtractor.extract("Venit Net Realizat\n102.000,00 lei\n").monthly_net_income == 0


@pytest.mark.parametrize("raw,expected", [
    ("8.500,00", 8500), ("8,500.00", 8500), ("8500.25", 8500.25),
    ("8 500,25", 8500.25), ("0,00", 0), ("-400,50", -400.50), ("1.000.000,00", 1000000),
])
def test_explicit_romanian_and_english_amounts_are_parsed_without_changing_magnitude(raw, expected):
    assert parse_document_amount(raw) == expected


@pytest.mark.parametrize("raw", ["4,,00", "6.2.00,00", "", "NaN", "inf", "12,1234", "9" * 1000])
def test_malformed_or_overflowing_amounts_are_not_silently_turned_into_zero(raw):
    with pytest.raises(ValueError):
        parse_document_amount(raw)


def test_missing_balance_summary_amount_is_not_assumed_to_be_zero():
    text = statement_text(closing="7.200,00").replace("Total plati: 400,00 RON\n", "")
    data = BankStatementExtractor.extract(text)
    assert not data.balance_fields_complete
    result = DocumentValidator.validate_statement(data, as_of=date(2026, 10, 28))
    assert not result.valid
    assert any(rule.code == "STMT_BALANCE_COMPLETENESS" and not rule.passed for rule in result.rules_evaluated)