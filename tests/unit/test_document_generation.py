"""Tests for synthetic document generation."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.services.document_generation.bank_statement import generate_bank_statement
from src.services.document_generation.generator import (
    PRESET_PROFILES,
    generate_document_suite,
    generate_documents_for_profile,
    load_profile_from_db,
)
from src.services.document_generation.id_card import generate_identity_card
from src.services.document_generation.income_certificate import generate_income_certificate
from src.services.document_generation.models import CustomerDocumentProfile


class DocumentGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = PRESET_PROFILES["alex_morgan"]

    def test_identity_card_generation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            pdf_path = tmp_path / "buletin.pdf"
            png_path = tmp_path / "buletin.png"

            img = generate_identity_card(self.profile, output_pdf=pdf_path, output_png=png_path)
            self.assertIsNotNone(img)
            self.assertTrue(pdf_path.exists())
            self.assertTrue(png_path.exists())
            self.assertGreater(pdf_path.stat().st_size, 1000)
            self.assertGreater(png_path.stat().st_size, 1000)

    def test_income_certificate_generation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            pdf_path = tmp_path / "adeverinta.pdf"
            png_path = tmp_path / "adeverinta.png"

            img = generate_income_certificate(self.profile, output_pdf=pdf_path, output_png=png_path)
            self.assertIsNotNone(img)
            self.assertTrue(pdf_path.exists())
            self.assertTrue(png_path.exists())
            self.assertGreater(pdf_path.stat().st_size, 1000)
            self.assertGreater(png_path.stat().st_size, 1000)

    def test_bank_statement_generation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            pdf_path = tmp_path / "extras.pdf"
            png_path = tmp_path / "extras.png"

            img = generate_bank_statement(self.profile, output_pdf=pdf_path, output_png=png_path)
            self.assertIsNotNone(img)
            self.assertTrue(pdf_path.exists())
            self.assertTrue(png_path.exists())
            self.assertGreater(pdf_path.stat().st_size, 1000)
            self.assertGreater(png_path.stat().st_size, 1000)

    def test_generate_documents_for_profile(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            docs = generate_documents_for_profile(self.profile, output_dir=tmp_path)

            self.assertIn("identity", docs)
            self.assertIn("income", docs)
            self.assertIn("statement", docs)

            for kind, formats in docs.items():
                self.assertIsNotNone(formats["pdf"])
                self.assertTrue(formats["pdf"].exists())
                self.assertGreater(formats["pdf"].stat().st_size, 1000)

    def test_generate_document_suite_and_index(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            manifest = generate_document_suite(
                output_dir=tmp_path,
                profiles=[self.profile],
                include_pdf=True,
                include_png=False,
            )

            self.assertEqual(len(manifest), 1)
            index_path = tmp_path / "INDEX.md"
            self.assertTrue(index_path.exists())
            content = index_path.read_text(encoding="utf-8")
            self.assertIn("Alex Morgan", content)
            self.assertIn("DEMO_CUSTOMER", content)

    def test_load_profile_from_db_dsti_39(self) -> None:
        profile = load_profile_from_db("DSTI_39")
        if profile is not None:
            self.assertEqual(profile.cnp, "1790420000031")
            self.assertEqual(profile.first_name, "Dan")


if __name__ == "__main__":
    unittest.main()
