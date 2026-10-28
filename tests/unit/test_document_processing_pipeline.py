"""Unit and integration tests for the Document Processing Pipeline."""

from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.models.document_processing import (
    DocumentKind,
    DocumentProcessingStatus,
    ExtractedIdentity,
    ExtractedIncome,
    ExtractedStatement,
)
from src.parsers.extraction.bank_statement_extractor import BankStatementExtractor
from src.parsers.extraction.id_card_extractor import IdCardExtractor
from src.parsers.extraction.income_certificate_extractor import IncomeCertificateExtractor
from src.parsers.validation.cnp_validator import compute_cnp_checksum, parse_cnp
from src.parsers.validation.cui_validator import validate_cui
from src.parsers.validation.document_validator import DocumentValidator
from src.parsers.validation.iban_validator import validate_iban
from src.services.document_processing.service import DocumentProcessingService
from src.storage.secure_documents.store import SecureDocumentStore


class DocumentProcessingPipelineTests(unittest.TestCase):
    def test_cnp_checksum_and_validation(self) -> None:
        base_12 = "192051541001"
        expected_control = compute_cnp_checksum(base_12)
        full_cnp = f"{base_12}{expected_control}"

        meta = parse_cnp(full_cnp, as_of=date(2026, 10, 28))
        self.assertTrue(meta.is_valid_format)
        self.assertTrue(meta.is_valid_checksum)
        self.assertTrue(meta.is_valid_date)
        self.assertEqual(meta.gender, "M")
        self.assertEqual(meta.birth_date, date(1992, 5, 15))
        self.assertEqual(meta.age_years, 34)

        bad_meta = parse_cnp("123ABC", as_of=date(2026, 10, 28))
        self.assertFalse(bad_meta.is_valid_format)

        invalid_date_cnp = "1920230410012"  # 30 Feb
        bad_date_meta = parse_cnp(invalid_date_cnp, as_of=date(2026, 10, 28))
        self.assertFalse(bad_date_meta.is_valid_date)

    def test_cui_validation(self) -> None:
        valid, cui_str = validate_cui("RO18318261")
        self.assertTrue(valid)
        self.assertEqual(cui_str, "18318261")

        valid2, cui_str2 = validate_cui("14399840")
        self.assertTrue(valid2)

        invalid, reason = validate_cui("RO18318269")
        self.assertFalse(invalid)
        self.assertIn("Invalid CUI control digit", reason)

    def test_iban_validation(self) -> None:
        valid, detail = validate_iban("RO54RZBR0000060012345678")
        self.assertTrue(valid)
        self.assertIn("Raiffeisen", detail)

        invalid, err = validate_iban("RO00RZBR0000060012345678")
        self.assertFalse(invalid)
        self.assertIn("checksum validation failed", err)

    def test_id_card_validator_rules(self) -> None:
        id_data = ExtractedIdentity(
            cnp="1920515410012",
            first_name="Alex",
            last_name="Morgan",
            series="RX",
            number="781920",
            gender="M",
            birth_date=date(1992, 5, 15),
            expiry_date=date(2032, 6, 10),
            mrz_line1="IDROUMORGAN<<ALEX<<<<<<<<<<<<<<<<<<",
        )
        summary = DocumentValidator.validate_identity(id_data, as_of=date(2026, 10, 28))
        self.assertTrue(summary.valid)
        self.assertEqual(summary.failed_rules_count, 0)

        # Expired ID
        expired_id = id_data.model_copy(update={"expiry_date": date(2020, 1, 1)})
        exp_summary = DocumentValidator.validate_identity(expired_id, as_of=date(2026, 10, 28))
        self.assertFalse(exp_summary.valid)
        self.assertIn("Expires on 2020-01-01", exp_summary.reasons[0])

    def test_income_certificate_validator_rules(self) -> None:
        inc_data = ExtractedIncome(
            employer_name="Tech Solutions S.R.L.",
            employer_cui="14399840",
            employee_name="Dan Ionescu",
            employee_cnp="1790420000031",
            job_title="Software Engineer",
            contract_type="NEDETERMINATĂ",
            employment_start_date=date(2021, 1, 1),
            monthly_net_income=6500.00,
            issue_date=date(2026, 10, 15),
        )
        summary = DocumentValidator.validate_income(inc_data, as_of=date(2026, 10, 28))
        self.assertTrue(summary.valid)
        self.assertEqual(summary.failed_rules_count, 0)

        # Stale certificate (> 30 days)
        stale_inc = inc_data.model_copy(update={"issue_date": date(2026, 8, 1)})
        stale_summary = DocumentValidator.validate_income(stale_inc, as_of=date(2026, 10, 28))
        self.assertFalse(stale_summary.valid)
        self.assertTrue(any("Issued 88 days" in r for r in stale_summary.reasons))

    def test_bank_statement_validator_rules(self) -> None:
        stmt_data = ExtractedStatement(
            bank_name="Raiffeisen Bank",
            account_holder="Alex Morgan",
            iban="RO54RZBR0000060012345678",
            initial_balance=10000.00,
            total_credits=8500.00,
            total_debits=3500.00,
            closing_balance=15000.00,
            period_end=date(2026, 10, 25),
            detected_salary_deposit=8500.00,
        )
        summary = DocumentValidator.validate_statement(stmt_data, as_of=date(2026, 10, 28))
        self.assertTrue(summary.valid)
        self.assertEqual(summary.failed_rules_count, 0)

        bad_math = stmt_data.model_copy(update={"closing_balance": 99999.00})
        bad_summary = DocumentValidator.validate_statement(bad_math, as_of=date(2026, 10, 28))
        self.assertFalse(bad_summary.valid)

    def test_cross_document_consistency(self) -> None:
        id_doc = ExtractedIdentity(
            cnp="1920515410012",
            first_name="Alex",
            last_name="Morgan",
        )
        inc_doc = ExtractedIncome(
            employee_name="Alex Morgan",
            employee_cnp="1920515410012",
            monthly_net_income=8500.00,
        )
        stmt_doc = ExtractedStatement(
            account_holder="Alex Morgan",
            detected_salary_deposit=8500.00,
        )

        cross = DocumentValidator.cross_validate(id_doc, inc_doc, stmt_doc)
        self.assertTrue(cross.consistent)
        self.assertFalse(cross.human_review_required)

        # Name mismatch
        mismatched_inc = inc_doc.model_copy(update={"employee_name": "Ion Popescu"})
        bad_cross = DocumentValidator.cross_validate(id_doc, mismatched_inc, stmt_doc)
        self.assertFalse(bad_cross.consistent)
        self.assertTrue(bad_cross.human_review_required)
        self.assertTrue(any("Name mismatch" in r for r in bad_cross.reasons))

    def test_secure_document_store_integrity_and_tampering(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SecureDocumentStore(root_dir=Path(tmpdir))
            sample_bytes = b"%PDF-1.4 synthetic content test"

            record = store.store_document(
                customer_id="cust-123",
                filename="test.pdf",
                content_bytes=sample_bytes,
                mime_type="application/pdf",
                doc_kind="identity",
            )

            doc_id = record["document_id"]
            self.assertTrue(store.verify_integrity(doc_id))

            # Retrieve with correct customer
            read_bytes, meta = store.get_document_bytes(doc_id, customer_id="cust-123")
            self.assertEqual(read_bytes, sample_bytes)

            # Unauthorized customer access
            with self.assertRaises(PermissionError):
                store.get_document_bytes(doc_id, customer_id="wrong-customer")

            # Simulate physical disk tampering
            file_on_disk = Path(tmpdir) / record["stored_path"]
            file_on_disk.write_bytes(b"%PDF-1.4 TAMPERED BY MALICIOUS PROCESS")

            self.assertFalse(store.verify_integrity(doc_id))
            with self.assertRaises(ValueError):
                store.get_document_bytes(doc_id, customer_id="cust-123")

    def test_e2e_process_and_store_pipeline(self) -> None:
        sample_pdf = Path("data/synthetic/documents/alex_morgan_demo_customer/buletin_alex_morgan_demo_customer.pdf")
        if not sample_pdf.exists():
            self.skipTest("Sample PDF not found.")

        with TemporaryDirectory() as tmpdir:
            store = SecureDocumentStore(root_dir=Path(tmpdir))
            svc = DocumentProcessingService(storage_store=store)

            processed = svc.process_and_store(
                content=sample_pdf,
                filename="buletin_alex.pdf",
                mime_type="application/pdf",
                customer_id="alex_morgan",
                declared_kind=DocumentKind.IDENTITY,
            )

            self.assertEqual(processed.kind, DocumentKind.IDENTITY)
            self.assertTrue(processed.validation.valid)
            self.assertEqual(processed.extracted_data["cnp"], "1920515410012")
            self.assertEqual(processed.extracted_data["series"], "RX")
            self.assertEqual(processed.extracted_data["number"], "781920")

    def test_e2e_full_dossier_processing_and_cross_validation(self) -> None:
        folder = Path("data/synthetic/documents/alex_morgan_demo_customer")
        if not (folder / "buletin_alex_morgan_demo_customer.pdf").exists():
            self.skipTest("Sample dossier not found.")

        with TemporaryDirectory() as tmpdir:
            store = SecureDocumentStore(root_dir=Path(tmpdir))
            svc = DocumentProcessingService(storage_store=store)

            p_id = svc.process_and_store(
                folder / "buletin_alex_morgan_demo_customer.pdf",
                "buletin.pdf",
                "application/pdf",
                "alex_morgan",
                DocumentKind.IDENTITY,
            )
            p_inc = svc.process_and_store(
                folder / "adeverinta_venit_alex_morgan_demo_customer.pdf",
                "adeverinta.pdf",
                "application/pdf",
                "alex_morgan",
                DocumentKind.INCOME,
            )
            p_stmt = svc.process_and_store(
                folder / "extras_cont_alex_morgan_demo_customer.pdf",
                "extras.pdf",
                "application/pdf",
                "alex_morgan",
                DocumentKind.STATEMENT,
            )

            self.assertTrue(p_id.validation.valid)
            self.assertTrue(p_inc.validation.valid)
            self.assertTrue(p_stmt.validation.valid)

            cross = svc.cross_validate_application(
                ExtractedIdentity(**p_id.extracted_data),
                ExtractedIncome(**p_inc.extracted_data),
                ExtractedStatement(**p_stmt.extracted_data),
            )
            self.assertTrue(cross.consistent)
            self.assertEqual(len(cross.reasons), 0)


if __name__ == "__main__":
    unittest.main()
