"""Repository integration tests; no writes to checked-in fixtures or real stores."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from scripts.credit_sources import generate_credit_sources as fixtures
from scripts.credit_sources.setup import create_database
from scripts.credit_sources.verify_credit_sources import verify_saved_database


class CreditSourcesSetupTests(unittest.TestCase):
    def test_versioned_fixture_creates_expected_local_database(self):
        with TemporaryDirectory(prefix="credit-sources-setup-") as directory:
            target = Path(directory) / "nested" / "credit_sources.db"
            create_database(target)
            self.assertEqual(len(verify_saved_database(target, replay=True)), 12)
            with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM persons").fetchone()[0], 323)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM credit_products").fetchone()[0], 422)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM payment_history").fetchone()[0], 10615)

    def test_empty_setup_preserves_original_schema_contract(self):
        with TemporaryDirectory(prefix="credit-sources-empty-") as directory:
            target = create_database(Path(directory) / "empty.db", empty=True)
            with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as db:
                for table in fixtures.TABLES:
                    self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM report_params").fetchone()[0], 1)

    def test_existing_database_is_never_overwritten(self):
        with TemporaryDirectory(prefix="credit-sources-preserve-") as directory:
            target = create_database(Path(directory) / "existing.db", empty=True)
            before = hashlib.sha256(target.read_bytes()).hexdigest()
            with self.assertRaises(FileExistsError):
                create_database(target)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)

    def test_invalid_source_does_not_create_target(self):
        with TemporaryDirectory(prefix="credit-sources-invalid-") as directory:
            root = Path(directory)
            (root / "credit_sources_sample_data.sql").write_text("THIS IS NOT SQL;", encoding="utf-8")
            target = root / "not_created.db"
            with self.assertRaises(sqlite3.Error):
                create_database(target, sample_dir=root)
            self.assertFalse(target.exists())

    def test_setup_entry_point_works_outside_repository(self):
        with TemporaryDirectory(prefix="credit-sources-cli-") as directory:
            target = Path(directory) / "cli.db"
            result = subprocess.run(
                [sys.executable, "-B", str(fixtures.ROOT / "scripts" / "credit_sources" / "setup.py"),
                 "--database", str(target), "--empty"],
                cwd=directory, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(target.exists())

    def test_saved_export_is_reproducible_from_default_seed(self):
        with closing(fixtures.new_database()) as db:
            manifest = fixtures.build_fixture(db)
            manifest["view_counts_at_default_date"] = fixtures.validate_fixture(db, manifest)
            self.assertEqual(fixtures.export_data_sql(db),
                             (fixtures.SAMPLE_DIR / "credit_sources_sample_data.sql").read_text(encoding="utf-8"))
            self.assertEqual(manifest, json.loads((fixtures.SAMPLE_DIR / "sample_data_manifest.json").read_text(encoding="utf-8")))
            self.assertEqual(fixtures.export_catalogue(manifest),
                             (fixtures.SAMPLE_DIR / "SAMPLE_DATA.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()