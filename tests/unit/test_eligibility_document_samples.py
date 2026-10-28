"""Unit tests verifying synthetic test documents for eligibility screening."""

from pathlib import Path
import unittest

from src.models.document_processing import DocumentKind, DocumentProcessingStatus
from src.services.document_processing.service import DocumentProcessingService


class EligibilityDocumentSamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = DocumentProcessingService()
        cls.base_dir = Path("data/test_samples_eligibility")

    def test_zero_income_anaf_certificate_rejected(self):
        pdf_path = self.base_dir / "01_RESPINS_Venit_Zero" / "adeverinta_anaf_zero_venit.pdf"
        self.assertTrue(pdf_path.exists(), f"Fișierul lipsește: {pdf_path}")

        res = self.service.process_and_store(
            content=pdf_path,
            filename=pdf_path.name,
            mime_type="application/pdf",
            customer_id="victor-1830107000044",
            declared_kind=DocumentKind.INCOME,
        )
        self.assertEqual(res.status, DocumentProcessingStatus.REJECTED)
        self.assertFalse(res.validation.valid)
        income = res.extracted_data.get("monthly_net_income", -1)
        self.assertEqual(income, 0.0)
        self.assertTrue(any("0.00 RON" in reason for reason in res.validation.reasons))

    def test_zero_income_salary_certificate_rejected(self):
        pdf_path = self.base_dir / "01_RESPINS_Venit_Zero" / "adeverinta_venit_zero_venituri.pdf"
        self.assertTrue(pdf_path.exists(), f"Fișierul lipsește: {pdf_path}")

        res = self.service.process_and_store(
            content=pdf_path,
            filename=pdf_path.name,
            mime_type="application/pdf",
            customer_id="victor-1830107000044",
            declared_kind=DocumentKind.INCOME,
        )
        self.assertEqual(res.status, DocumentProcessingStatus.REJECTED)
        self.assertFalse(res.validation.valid)
        income = res.extracted_data.get("monthly_net_income", -1)
        self.assertEqual(income, 0.0)

    def test_ok_income_anaf_certificate_validated(self):
        pdf_path = self.base_dir / "02_ELIGIBIL_Venit_Optim" / "adeverinta_anaf_venit_ok.pdf"
        self.assertTrue(pdf_path.exists(), f"Fișierul lipsește: {pdf_path}")

        res = self.service.process_and_store(
            content=pdf_path,
            filename=pdf_path.name,
            mime_type="application/pdf",
            customer_id="alex-1920515410012",
            declared_kind=DocumentKind.INCOME,
        )
        self.assertEqual(res.status, DocumentProcessingStatus.VALIDATED)
        self.assertTrue(res.validation.valid)
        self.assertEqual(res.validation.failed_rules_count, 0)
        income = res.extracted_data.get("monthly_net_income", 0.0)
        self.assertEqual(income, 8500.0)

    def test_ok_income_salary_certificate_validated(self):
        pdf_path = self.base_dir / "02_ELIGIBIL_Venit_Optim" / "adeverinta_venit_ok_8500_ron.pdf"
        self.assertTrue(pdf_path.exists(), f"Fișierul lipsește: {pdf_path}")

        res = self.service.process_and_store(
            content=pdf_path,
            filename=pdf_path.name,
            mime_type="application/pdf",
            customer_id="alex-1920515410012",
            declared_kind=DocumentKind.INCOME,
        )
        self.assertEqual(res.status, DocumentProcessingStatus.VALIDATED)
        self.assertTrue(res.validation.valid)
        income = res.extracted_data.get("monthly_net_income", 0.0)
        self.assertEqual(income, 8500.0)

    def test_sub_minimum_income_certificate_rejected(self):
        pdf_path = self.base_dir / "03_RESPINS_Venit_Sub_Minim" / "adeverinta_venit_sub_minim_1500_ron.pdf"
        self.assertTrue(pdf_path.exists(), f"Fișierul lipsește: {pdf_path}")

        res = self.service.process_and_store(
            content=pdf_path,
            filename=pdf_path.name,
            mime_type="application/pdf",
            customer_id="maria-2850912000084",
            declared_kind=DocumentKind.INCOME,
        )
        self.assertEqual(res.status, DocumentProcessingStatus.REJECTED)
        self.assertFalse(res.validation.valid)
        income = res.extracted_data.get("monthly_net_income", 0.0)
        self.assertEqual(income, 1500.0)
        self.assertTrue(any("1,500.00 RON" in reason for reason in res.validation.reasons))


if __name__ == "__main__":
    unittest.main()
