"""Standard-library regression, data-quality and optional performance tests.

Run with: py -3 <absolute path to this file>
Add --create to create the component's data-directory database after tests pass.
Add --benchmark for the 3,000-person benchmark (optional p95 budget via
CREDIT_SOURCES_MAX_P95_MS). Fixtures use memory or temporary disk databases.
An existing output database is never overwritten.
"""

from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
import os
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
# Support both direct execution by absolute filename and unittest discovery,
# including when this component is placed inside a larger repository.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.credit_sources.credit_sources_validation import fictional_data_issues
from scripts.credit_sources import generate_credit_sources as fixtures
from scripts.credit_sources.verify_credit_sources import verify_saved_database


SCHEMA = fixtures.SCHEMA_PATH.read_text(encoding="utf-8")
DEBTOR = "1000000000001"
GUARANTOR = "1000000000002"
NO_HISTORY = "1000000000003"


def new_database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def verify_empty(db):
    tables = db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    assert len(tables) == 17, len(tables)
    for (name,) in tables:
        count = db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        assert count == (1 if name == "report_params" else 0), (name, count)
    views = db.execute("SELECT name FROM sqlite_master WHERE type = 'view'").fetchall()
    assert len(views) == 12, len(views)
    for (name,) in views:
        assert db.execute(f'SELECT * FROM "{name}"').fetchall() == [], name
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.db = new_database()
        self.addCleanup(self.db.close)
        self.db.execute("UPDATE report_params SET as_of_date = '2026-10-28'")

    def seed_core(self):
        for cnp in (DEBTOR, GUARANTOR, NO_HISTORY):
            self.db.execute(
                "INSERT INTO persons(cnp, first_name, last_name, birth_date) VALUES (?, 'Test', 'Person', '1990-01-01')",
                (cnp,),
            )
        self.db.execute("INSERT INTO lenders VALUES (1, 'Fictional Bank', 'BANK')")
        self.db.execute("INSERT INTO employers VALUES (1, 'Fictional Employer', 'TEST1', NULL)")

    def product(self, ident=1, amount=25000, kind="CONSUMER_LOAN", opened="2020-01-01",
                status="ACTIVE", closed=None, cnp=DEBTOR, role="DEBTOR"):
        self.db.execute(
            """INSERT INTO credit_products
               (id, lender, product_type, opened_on, term_months, amount_granted,
                amount_granted_ron, rate_type, status, closed_on)
               VALUES (?, 1, ?, ?, ?, ?, ?, 'FIXED', ?, ?)""",
            (ident, kind, opened, None if kind in ("CREDIT_CARD", "OVERDRAFT") else 360,
             amount, amount, status, closed),
        )
        self.db.execute("INSERT INTO product_participants VALUES (?, ?, ?)", (ident, cnp, role))

    def history(self, product=1, month="2026-09-01", owed=20000, instalment=2340, dpd=0):
        self.db.execute(
            """INSERT INTO payment_history
               (product, month, amount_owed, instalment_due, amount_paid,
                overdue_amount, overdue_instalments, days_past_due)
               VALUES (?, ?, ?, ?, 0, 0, 0, ?)""",
            (product, month, owed, instalment, dpd),
        )

    def row(self, view, cnp=DEBTOR):
        return self.db.execute(f"SELECT * FROM {view} WHERE cnp = ?", (cnp,)).fetchone()

    def rejected(self, sql, args=()):
        with self.assertRaises(sqlite3.IntegrityError, msg=sql):
            self.db.execute(sql, args)


class CreditSourcesTests(DatabaseTestCase):
    def test_empty_schema_and_singleton(self):
        verify_empty(self.db)
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.rejected("INSERT INTO report_params(id) VALUES (2)")
        self.rejected("DELETE FROM report_params")
        self.rejected("UPDATE report_params SET id = 2")

    def test_parameter_default_today_and_duplicate_id(self):
        fresh = new_database()
        try:
            self.assertEqual(fresh.execute("SELECT as_of_date = CURRENT_DATE FROM report_params").fetchone()[0], 1)
        finally:
            fresh.close()
        self.rejected("INSERT INTO report_params(id) VALUES (1)")
        self.rejected("UPDATE report_params SET as_of_date=NULL")

    def test_required_invalid_inserts(self):
        self.seed_core()
        for cnp in ("123456789012", "123456789012A", "12345678901234"):
            self.rejected("INSERT INTO persons VALUES (?, 'A', 'B', '1990-01-01', NULL, NULL, NULL)", (cnp,))
        for score, status in ((900, "SCORED"), (None, "SCORED"), (500, "NO_SCORE")):
            self.rejected("INSERT INTO fico_scores(cnp, calculated_on, score, status) VALUES (?, '2026-10-01', ?, ?)",
                          (DEBTOR, score, status))
        with self.assertRaises(sqlite3.IntegrityError):
            self.product(status="CLOSED")
        self.product()
        with self.assertRaises(sqlite3.IntegrityError):
            self.history(month="2026-10-15")
        self.rejected("INSERT INTO product_participants VALUES (999, ?, 'DEBTOR')", (DEBTOR,))

    def test_date_integer_money_and_enum_constraints(self):
        self.seed_core()
        self.product()
        for value in ("2026-02-30", "2026-13-01", "2026-1-01", "not-a-date", "2026-10-28 12:00:00"):
            self.rejected("UPDATE report_params SET as_of_date = ?", (value,))
        self.db.execute("UPDATE report_params SET as_of_date = '2024-02-29'")
        for month in ("2026-00-01", "2026-13-01", "2026-2-01"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.history(month=month)
        for assignment in ("term_months = NULL", "term_months = 0", "term_months = 1.5",
                           "amount_granted = -1", "amount_granted_ron = 'abc'", "currency = 'GBP'",
                           "closed_on = '2026-01-01'", "status = 'UNKNOWN'"):
            self.rejected("UPDATE credit_products SET " + assignment)
        self.rejected("INSERT INTO employments VALUES (1, ?, 1, '2026-02-01', '2026-01-01', 'INDEFINITE')", (DEBTOR,))
        self.rejected("INSERT INTO monthly_salary_declarations VALUES (?, 1, '2026-10-15', 100, 80, 20)", (DEBTOR,))
        self.rejected("INSERT INTO monthly_salary_declarations VALUES (?, 1, '2026-10-01', 100, 101, 0)", (DEBTOR,))
        self.rejected("INSERT INTO income_records VALUES (1, ?, 2025, 'SALARY', 'Test', NULL, 100, 101)", (DEBTOR,))

    def test_income_window_and_dsti(self):
        self.seed_core()
        self.product()
        self.history()
        for year in range(2022, 2027):
            self.db.execute(
                """INSERT INTO income_records(cnp, fiscal_year, income_type, source_name, gross_amount_ron, net_amount_ron)
                   VALUES (?, ?, 'SALARY', 'Test', 100000, 71955)""", (DEBTOR, year))
        years = [r[0] for r in self.db.execute("SELECT fiscal_year FROM v_anaf_income ORDER BY fiscal_year")]
        self.assertEqual(years, [2023, 2024, 2025])
        dsti = self.row("v_dsti_inputs")
        self.assertEqual((dsti["fiscal_year"], dsti["average_net_monthly_income_ron"], dsti["current_dsti_pct"]),
                         (2025, 5996.25, 39.0))
        self.assertIsNone(self.row("v_dsti_inputs", NO_HISTORY)["current_dsti_pct"])
        self.db.execute("UPDATE income_records SET net_amount_ron = 0")
        self.assertIsNone(self.row("v_dsti_inputs")["current_dsti_pct"])

    def test_income_types_are_distinct_and_ordered(self):
        self.seed_core()
        for kind, source in (("SALARY", "A"), ("RENTAL", "B"), ("SALARY", "C")):
            self.db.execute("INSERT INTO income_records VALUES (NULL, ?, 2025, ?, ?, NULL, 12000, 12000)",
                            (DEBTOR, kind, source))
        row = self.row("v_anaf_income_by_year")
        self.assertEqual((row["total_net_income_ron"], row["average_net_monthly_income_ron"], row["income_types"]),
                         (36000, 3000, "RENTAL, SALARY"))

    def test_bureau_vs_crc_months_and_threshold(self):
        self.seed_core()
        self.product()
        self.product(2, amount=8000, kind="CREDIT_CARD")
        self.product(3, amount=20000)
        self.product(4, opened="2026-10-01")
        self.history(month="2026-09-01", owed=20000)
        self.history(month="2026-10-01", owed=19000)
        self.history(month="2026-11-01", owed=18000)
        self.history(product=3, month="2026-08-01")
        bureau = self.db.execute("SELECT * FROM v_bureau_products WHERE product = 1").fetchone()
        self.assertEqual((bureau["payment_month"], bureau["amount_owed"]), ("2026-10-01", 19000))
        crc = self.db.execute("SELECT * FROM v_crc_exposures ORDER BY product").fetchall()
        self.assertEqual([r["product"] for r in crc], [1, 3])
        self.assertEqual((crc[0]["snapshot_date"], crc[0]["payment_month"], crc[0]["amount_owed"]),
                         ("2026-09-30", "2026-09-01", 20000))
        self.assertIsNone(crc[1]["payment_month"])
        self.assertIsNone(crc[1]["amount_owed"])

    def test_retention_boundaries_and_future_products(self):
        self.seed_core()
        closures = ("2018-01-01", "2022-10-28", "2022-10-27", "2019-10-28", "2019-10-27")
        for ident, closed in enumerate(closures, 1):
            self.product(ident, opened="2010-01-01", status="CLOSED", closed=closed)
        self.product(6, opened="2027-01-01")
        self.assertEqual([r[0] for r in self.db.execute("SELECT product FROM v_bureau_products ORDER BY product")], [2])
        self.assertEqual([r[0] for r in self.db.execute("SELECT product FROM v_crc_exposures ORDER BY product")], [2, 3, 4])

    def test_guarantees_closed_debts_and_no_history(self):
        self.seed_core()
        self.product(kind="MORTGAGE")
        self.db.execute("INSERT INTO product_participants VALUES (1, ?, 'GUARANTOR')", (GUARANTOR,))
        self.history(instalment=2340)
        self.product(2, status="CLOSED", closed="2026-09-30")
        self.history(product=2, instalment=9000, dpd=60)
        for view in ("v_bureau_products", "v_crc_exposures"):
            self.assertEqual(self.row(view, GUARANTOR)["role"], "GUARANTOR")
        debtor = self.row("v_bureau_summary")
        self.assertEqual((debtor["active_products"], debtor["total_monthly_instalments_ron"], debtor["current_max_days_past_due"],
                          debtor["worst_days_past_due_24m"]), (1, 2340, 0, 60))
        guarantor = self.row("v_bureau_summary", GUARANTOR)
        self.assertEqual((guarantor["active_products"], guarantor["active_guarantees"], guarantor["total_owed_ron"],
                          guarantor["total_monthly_instalments_ron"]), (0, 1, 0, 0))
        empty = self.row("v_bureau_summary", NO_HISTORY)
        self.assertEqual((empty["active_products"], empty["has_insolvency"], empty["inquiry_count_6m"]), (0, 0, 0))
        self.assertIsNone(empty["latest_score"])

    def test_historical_closure_is_not_effective_early(self):
        self.seed_core()
        self.product(status="CLOSED", closed="2026-12-01")
        self.history()
        self.assertEqual(self.row("v_bureau_products")["status"], "ACTIVE")
        self.assertIsNone(self.row("v_bureau_products")["closed_on"])
        self.assertEqual(self.row("v_bureau_summary")["active_products"], 1)
        self.db.execute("UPDATE report_params SET as_of_date = '2026-12-01'")
        self.assertEqual(self.row("v_bureau_summary")["total_monthly_instalments_ron"], 0)

    def test_inquiries_scores_reason_order_and_no_fanout(self):
        self.seed_core()
        self.product()
        self.history()
        for date, kind in (("2026-10-20", "SOFT"), ("2025-01-01", "HARD"), ("2026-04-28", "HARD"),
                           ("2026-04-27", "HARD"), ("2026-10-28", "HARD"), ("2026-10-29", "HARD")):
            self.db.execute("INSERT INTO bureau_inquiries VALUES (NULL, ?, 1, ?, ?)", (DEBTOR, date, kind))
        for ident, date, score in ((1, "2026-01-01", 600), (2, "2026-10-28", 700), (3, "2026-10-29", 800)):
            self.db.execute("INSERT INTO fico_scores VALUES (?, ?, ?, ?, 'SCORED')", (ident, DEBTOR, date, score))
        self.db.execute("INSERT INTO fico_reason_codes VALUES (2, 2, 'B', 'Second')")
        self.db.execute("INSERT INTO fico_reason_codes VALUES (2, 1, 'A', 'First')")
        self.assertEqual(self.row("v_bureau_latest_score")["reason_descriptions"], "First; Second")
        summary = self.row("v_bureau_summary")
        self.assertEqual((summary["inquiry_count_6m"], summary["latest_score"], summary["total_monthly_instalments_ron"]),
                         (2, 700, 2340))
        self.db.execute("UPDATE fico_scores SET score = NULL, status = 'NO_SCORE' WHERE id = 2")
        self.assertEqual(self.row("v_bureau_summary")["latest_score_status"], "NO_SCORE")
        self.assertIsNone(self.row("v_bureau_summary")["latest_score"])

    def test_delay_categories_and_24_month_window(self):
        self.seed_core()
        self.product()
        for month, dpd, category in (("2024-10-01", 999, "180+"), ("2024-11-01", 181, "180+"),
                                     ("2026-01-01", 180, "91-180"), ("2026-02-01", 91, "91-180"),
                                     ("2026-03-01", 90, "61-90"), ("2026-04-01", 61, "61-90"),
                                     ("2026-05-01", 60, "31-60"), ("2026-06-01", 31, "31-60"),
                                     ("2026-07-01", 30, "1-30"), ("2026-08-01", 1, "1-30"),
                                     ("2026-09-01", 0, "CURRENT"), ("2026-11-01", 999, "180+")):
            self.history(month=month, dpd=dpd)
            self.assertEqual(self.db.execute("SELECT delay_category FROM payment_history WHERE month = ?", (month,)).fetchone()[0], category)
        self.assertEqual(self.row("v_bureau_products")["worst_days_past_due_24m"], 181)

    def test_activity_events_insolvency_and_fraud_windows(self):
        self.seed_core()
        self.product()
        for ident, end in enumerate((None, "2023-10-28", "2023-10-27"), 1):
            self.db.execute("INSERT INTO income_activity_forms VALUES (?, ?, 'PFA', 'Test', NULL, NULL, '2020-01-01', ?)",
                            (ident, DEBTOR, end))
        self.db.execute("INSERT INTO income_activity_forms VALUES (4, ?, 'PFA', 'Future', NULL, NULL, '2027-01-01', NULL)", (DEBTOR,))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM v_anaf_activity_form").fetchone()[0], 2)
        for date in ("2022-10-28", "2022-10-27", "2026-10-28", "2026-10-29"):
            self.db.execute("INSERT INTO credit_events VALUES (NULL, 1, ?, 'RESTRUCTURING', NULL)", (date,))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM v_bureau_events").fetchone()[0], 2)
        for end in (None, "2022-10-28", "2022-10-27"):
            self.db.execute("INSERT INTO insolvency_records VALUES (NULL, ?, 'SIMPLIFIED', '2020-01-01', ?, 'Test')", (DEBTOR, end))
        self.db.execute("INSERT INTO insolvency_records VALUES (NULL, ?, 'SIMPLIFIED', '2027-01-01', NULL, 'Test')", (NO_HISTORY,))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM v_bureau_insolvency").fetchone()[0], 2)
        self.assertEqual(self.row("v_bureau_summary")["has_insolvency"], 1)
        self.assertEqual(self.row("v_bureau_summary", NO_HISTORY)["has_insolvency"], 0)
        for date in ("2019-10-28", "2019-10-27", "2026-10-28", "2026-10-29"):
            self.db.execute("INSERT INTO card_fraud_records VALUES (NULL, ?, NULL, ?, 'Test')", (DEBTOR, date))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM v_crc_fraud").fetchone()[0], 2)

    def test_product_and_score_cascades(self):
        self.seed_core()
        self.product()
        self.history()
        self.db.execute("INSERT INTO credit_events VALUES (1, 1, '2026-01-01', 'RESTRUCTURING', NULL)")
        self.db.execute("DELETE FROM credit_products WHERE id = 1")
        for table in ("product_participants", "payment_history", "credit_events"):
            self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.db.execute("INSERT INTO fico_scores VALUES (1, ?, '2026-01-01', 700, 'SCORED')", (DEBTOR,))
        self.db.execute("INSERT INTO fico_reason_codes VALUES (1, 1, 'A', 'Test')")
        self.db.execute("DELETE FROM fico_scores")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM fico_reason_codes").fetchone()[0], 0)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])


class ExtendedReportTests(DatabaseTestCase):
    def income(self, cnp=DEBTOR, year=2025, net=12000, source="Test"):
        self.db.execute("INSERT INTO income_records VALUES (NULL, ?, ?, 'SALARY', ?, NULL, ?, ?)",
                        (cnp, year, source, net, net))

    def test_year_change_shifts_income_and_exact_crc_month(self):
        self.seed_core()
        self.product()
        for year in range(2023, 2028):
            self.income(year=year)
        self.history(month="2026-12-01", owed=12000)
        self.history(month="2027-01-01", owed=11000)
        for day, years, snapshot in (
                ("2026-12-31", [2023, 2024, 2025], "2026-11-30"),
                ("2027-01-01", [2024, 2025, 2026], "2026-12-31"),
                ("2027-01-05", [2024, 2025, 2026], "2026-12-31")):
            with self.subTest(day=day):
                self.db.execute("UPDATE report_params SET as_of_date=?", (day,))
                self.assertEqual([r[0] for r in self.db.execute(
                    "SELECT fiscal_year FROM v_anaf_income ORDER BY fiscal_year")], years)
                crc = self.row("v_crc_exposures")
                self.assertEqual(crc["snapshot_date"], snapshot)
                if day.startswith("2027"):
                    self.assertEqual((crc["payment_month"], crc["amount_owed"]), ("2026-12-01", 12000))

    def test_leap_and_nonleap_crc_snapshots(self):
        self.seed_core()
        self.product()
        for day, month, snapshot in (("2024-03-01", "2024-02-01", "2024-02-29"),
                                     ("2025-03-01", "2025-02-01", "2025-02-28"),
                                     ("2024-02-29", "2024-01-01", "2024-01-31")):
            with self.subTest(day=day):
                self.history(month=month)
                self.db.execute("UPDATE report_params SET as_of_date=?", (day,))
                row = self.row("v_crc_exposures")
                self.assertEqual((row["payment_month"], row["snapshot_date"]), (month, snapshot))

    def test_month_end_and_leap_day_retention_arithmetic(self):
        self.seed_core()
        # Explicit expectations for SQLite's calendar overflow semantics, not fixed days.
        for day, cutoff, before in (("2026-08-31", "2026-03-03", "2026-03-02"),
                                    ("2024-02-29", "2023-08-29", "2023-08-28")):
            with self.subTest(day=day):
                self.db.execute("DELETE FROM bureau_inquiries")
                self.db.execute("UPDATE report_params SET as_of_date=?", (day,))
                for inquiry_day in (cutoff, before):
                    self.db.execute("INSERT INTO bureau_inquiries VALUES (NULL, ?, 1, ?, 'HARD')", (DEBTOR, inquiry_day))
                self.assertEqual([r[0] for r in self.db.execute("SELECT inquiry_date FROM v_bureau_inquiries_6m")], [cutoff])
        self.db.execute("UPDATE report_params SET as_of_date='2024-02-29'")
        for ident, closed in enumerate(("2020-02-29", "2020-02-28", "2017-03-01", "2017-02-28"), 1):
            self.product(ident, opened="2010-01-01", status="CLOSED", closed=closed)
        self.assertEqual([r[0] for r in self.db.execute("SELECT product FROM v_bureau_products ORDER BY product")], [1])
        self.assertEqual([r[0] for r in self.db.execute("SELECT product FROM v_crc_exposures ORDER BY product")], [1, 2, 3])

    def test_time_travel_all_views_are_reversible(self):
        self.seed_core()
        self.product()
        self.product(2, opened="2026-09-01")
        self.history(month="2026-07-01", owed=21000)
        self.history(month="2026-09-01", owed=19000)
        for day, score in (("2026-07-01", 600), ("2026-09-01", 700)):
            self.db.execute("INSERT INTO fico_scores VALUES (NULL, ?, ?, ?, 'SCORED')", (DEBTOR, day, score))
        self.db.execute("UPDATE report_params SET as_of_date='2026-08-15'")
        views = [r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='view'")]
        def snapshot():
            return {v: sorted([tuple(r) for r in self.db.execute(f'SELECT * FROM {v}')], key=repr) for v in views}
        before = snapshot()
        self.assertEqual(len(before["v_bureau_products"]), 1)
        self.assertEqual(self.row("v_bureau_products")["payment_month"], "2026-07-01")
        self.assertEqual(self.row("v_bureau_latest_score")["score"], 600)
        self.db.execute("UPDATE report_params SET as_of_date='2026-10-28'")
        self.assertEqual(len(snapshot()["v_bureau_products"]), 2)
        self.assertEqual(self.row("v_bureau_latest_score")["score"], 700)
        self.db.execute("UPDATE report_params SET as_of_date='2026-08-15'")
        self.assertEqual(snapshot(), before)

    def test_cross_source_figures_agree_and_follow_updates(self):
        self.seed_core()
        self.product()
        self.history()
        columns = ("payment_month", "amount_owed", "instalment_due", "amount_paid", "overdue_amount",
                   "overdue_instalments", "days_past_due", "delay_category")
        for dpd in (0, 31):
            self.db.execute("UPDATE payment_history SET days_past_due=?, overdue_amount=?, amount_owed=?", (dpd, dpd * 10, 19000))
            bureau, crc = self.row("v_bureau_products"), self.row("v_crc_exposures")
            self.assertEqual(tuple(bureau[k] for k in columns), tuple(crc[k] for k in columns))
            self.assertEqual(bureau["amount_owed"], 19000)

    def test_crc_currency_and_cent_thresholds_not_outstanding_balance(self):
        self.seed_core()
        for ident, amount in enumerate((19999.99, 20000, 20000.01, 25000), 1):
            self.product(ident, amount=amount)
            self.history(product=ident, owed=1)
        self.db.execute("UPDATE credit_products SET currency='EUR', amount_granted=5000 WHERE id=4")
        self.assertEqual([r[0] for r in self.db.execute("SELECT product FROM v_crc_exposures ORDER BY product")], [2, 3, 4])

    def test_codebtors_mixed_roles_and_person_isolation(self):
        self.seed_core()
        self.product()
        self.history(instalment=1000, dpd=30)
        self.db.execute("INSERT INTO product_participants VALUES (1, ?, 'CODEBTOR')", (GUARANTOR,))
        self.db.execute("INSERT INTO product_participants VALUES (1, ?, 'GUARANTOR')", (NO_HISTORY,))
        self.product(2, cnp=NO_HISTORY)
        self.history(product=2, instalment=200, dpd=0)
        self.db.execute("INSERT INTO product_participants VALUES (2, ?, 'GUARANTOR')", (DEBTOR,))
        for cnp, net, year, score in ((DEBTOR, 24000, 2025, 600), (GUARANTOR, 12000, 2024, 700), (NO_HISTORY, 48000, 2023, 800)):
            self.income(cnp, year, net)
            self.db.execute("INSERT INTO fico_scores VALUES (NULL, ?, '2026-01-01', ?, 'SCORED')", (cnp, score))
        self.db.execute("INSERT INTO bureau_inquiries VALUES (NULL, ?, 1, '2026-10-01', 'HARD')", (DEBTOR,))
        for cnp, instalment, guarantees, dpd, score, inquiries, ratio in (
                (DEBTOR, 1000, 1, 30, 600, 1, 50.0), (GUARANTOR, 1000, 0, 30, 700, 0, 100.0),
                (NO_HISTORY, 200, 1, 0, 800, 0, 5.0)):
            with self.subTest(cnp=cnp):
                s = self.row("v_bureau_summary", cnp)
                self.assertEqual(tuple(s[k] for k in ("active_products", "total_monthly_instalments_ron", "active_guarantees",
                    "current_max_days_past_due", "latest_score", "inquiry_count_6m")), (1, instalment, guarantees, dpd, score, inquiries))
                self.assertEqual(self.row("v_dsti_inputs", cnp)["current_dsti_pct"], ratio)

    def test_missing_partial_and_future_only_history(self):
        self.seed_core()
        for ident in (1, 2, 3):
            self.product(ident)
        self.history(product=2, month="2026-11-01")
        self.history(product=3, instalment=100)
        rows = self.db.execute("SELECT * FROM v_bureau_products ORDER BY product").fetchall()
        self.assertEqual([r["payment_month"] for r in rows], [None, None, "2026-09-01"])
        s = self.row("v_bureau_summary")
        self.assertEqual((s["active_products"], s["total_monthly_instalments_ron"]), (3, 100))
        self.db.execute("DELETE FROM payment_history")
        self.assertEqual(self.row("v_bureau_summary")["total_monthly_instalments_ron"], 0)

    def test_old_income_no_debt_and_all_empty_summary_fields(self):
        self.seed_core()
        s = self.row("v_bureau_summary")
        for key in ("active_products", "active_guarantees", "total_owed_ron", "total_monthly_instalments_ron",
                    "current_max_days_past_due", "worst_days_past_due_24m", "inquiry_count_6m", "has_insolvency"):
            self.assertEqual(s[key], 0, key)
        for key in ("latest_score", "latest_score_status", "latest_score_date"):
            self.assertIsNone(s[key], key)
        self.income(year=2022)
        self.assertIsNone(self.row("v_dsti_inputs")["current_dsti_pct"])
        self.income(year=2024)
        self.assertEqual(self.row("v_dsti_inputs")["current_dsti_pct"], 0.0)
        self.assertEqual(self.row("v_dsti_inputs")["fiscal_year"], 2024)

    def test_multiple_loans_dsti_rounding_and_over_100_percent(self):
        self.seed_core()
        self.product()
        self.product(2)
        self.history(instalment=100)
        self.history(product=2, instalment=200)
        self.income(net=12000)
        self.assertEqual(self.row("v_dsti_inputs")["current_dsti_pct"], 30.0)
        for payment in (Decimal("199.49"), Decimal("199.51"), Decimal("1200.01")):
            self.db.execute("UPDATE payment_history SET instalment_due=? WHERE product=2", (float(payment),))
            expected = ((Decimal(100) + payment) / Decimal(1000) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            self.assertEqual(self.row("v_dsti_inputs")["current_dsti_pct"], float(expected))

    def test_nonclosed_statuses_remain_obligations(self):
        self.seed_core()
        for ident, status in enumerate(("ACTIVE", "ASSIGNED", "WRITTEN_OFF", "IN_INSOLVENCY_PROCEDURE"), 1):
            self.product(ident, status=status)
            self.history(product=ident, instalment=100)
        s = self.row("v_bureau_summary")
        self.assertEqual((s["active_products"], s["total_monthly_instalments_ron"]), (4, 400))

    def test_dsti_income_matches_annual_view_with_fractional_multiple_sources(self):
        self.seed_core()
        for cnp, year in ((DEBTOR, 2025), (GUARANTOR, 2024), (NO_HISTORY, 2023)):
            self.income(cnp, year, 12345.67, "Employer A")
            self.income(cnp, year, 23456.78, "Employer B")
            annual = self.row("v_anaf_income_by_year", cnp)
            dsti = self.row("v_dsti_inputs", cnp)
            self.assertEqual((dsti["fiscal_year"], dsti["average_net_monthly_income_ron"]),
                             (annual["fiscal_year"], annual["average_net_monthly_income_ron"]))

    def test_score_without_reasons_and_future_only_score(self):
        self.seed_core()
        self.db.execute("INSERT INTO fico_scores VALUES (1, ?, '2026-10-29', 700, 'SCORED')", (DEBTOR,))
        self.assertIsNone(self.row("v_bureau_latest_score"))
        self.db.execute("UPDATE fico_scores SET calculated_on='2026-10-28'")
        self.assertIsNone(self.row("v_bureau_latest_score")["reason_descriptions"])

    def test_product_opening_on_reference_date_and_preopening_history(self):
        self.seed_core()
        self.product(opened="2026-10-28")
        self.history(month="2026-09-01", dpd=181)
        self.assertIsNone(self.row("v_bureau_products")["payment_month"])
        self.assertIsNone(self.row("v_crc_exposures"))
        self.history(month="2026-10-01", dpd=0)
        self.assertEqual(self.row("v_bureau_products")["worst_days_past_due_24m"], 0)
        self.db.execute("UPDATE report_params SET as_of_date='2026-10-27'")
        self.assertIsNone(self.row("v_bureau_products"))


class ExtendedConstraintTests(DatabaseTestCase):
    def seed_all_tables(self):
        self.seed_core()
        self.product()
        self.history()
        statements = (
            ("INSERT INTO employments VALUES (1, ?, 1, '2020-01-01', NULL, 'INDEFINITE')", (DEBTOR,)),
            ("INSERT INTO income_activity_forms VALUES (1, ?, 'PFA', 'Test', 'TEST2', NULL, '2020-01-01', NULL)", (DEBTOR,)),
            ("INSERT INTO income_records VALUES (1, ?, 2025, 'SALARY', 'Test', 'TEST1', 12000, 10000)", (DEBTOR,)),
            ("INSERT INTO monthly_salary_declarations VALUES (?, 1, '2026-09-01', 1000, 800, 200)", (DEBTOR,)),
            ("INSERT INTO credit_events VALUES (1, 1, '2026-09-01', 'RESTRUCTURING', NULL)", ()),
            ("INSERT INTO bureau_inquiries VALUES (1, ?, 1, '2026-09-01', 'HARD')", (DEBTOR,)),
            ("INSERT INTO fico_scores VALUES (1, ?, '2026-09-01', 700, 'SCORED')", (DEBTOR,)),
            ("INSERT INTO fico_reason_codes VALUES (1, 1, 'A', 'Test')", ()),
            ("INSERT INTO insolvency_records VALUES (1, ?, 'SIMPLIFIED', '2020-01-01', NULL, 'Test')", (DEBTOR,)),
            ("INSERT INTO card_fraud_records VALUES (1, ?, 1, '2026-09-01', 'Test')", (DEBTOR,)),
        )
        for sql, args in statements:
            self.db.execute(sql, args)

    def test_all_business_unique_keys(self):
        self.seed_all_tables()
        for table in ("persons", "employers", "lenders", "income_records", "monthly_salary_declarations",
                      "product_participants", "payment_history", "fico_scores", "fico_reason_codes"):
            columns = [r[1] for r in self.db.execute(f'PRAGMA table_info({table})') if r[1] != "id"]
            names = ", ".join(columns)
            with self.subTest(table=table):
                self.rejected(f"INSERT INTO {table} ({names}) SELECT {names} FROM {table}")
        self.rejected("INSERT INTO product_participants VALUES (1, ?, 'GUARANTOR')", (DEBTOR,))

    def test_fico_and_reason_rank_boundaries(self):
        self.seed_all_tables()
        for score in (300, 850):
            self.db.execute("UPDATE fico_scores SET score=?", (score,))
        for score in (299, 851, 300.5, "invalid"):
            self.rejected("UPDATE fico_scores SET score=?", (score,))
        for rank in (1, 5):
            self.db.execute("UPDATE fico_reason_codes SET rank=?", (rank,))
        for rank in (0, 6, 1.5):
            self.rejected("UPDATE fico_reason_codes SET rank=?", (rank,))

    def test_every_enum_accepts_legal_and_rejects_unknown_values(self):
        self.seed_all_tables()
        enums = {
            ("employments", "contract_type"): ("INDEFINITE", "FIXED_TERM", "PART_TIME"),
            ("lenders", "lender_type"): ("BANK", "IFN", "LEASING", "INSURER", "DEBT_COLLECTOR"),
            ("income_activity_forms", "form_type"): ("PFA", "II", "IF", "LIBERAL_PROFESSION"),
            ("income_records", "income_type"): ("SALARY", "INDEPENDENT_ACTIVITY", "PENSION", "SOCIAL_INSURANCE", "RENTAL", "INVESTMENT", "OTHER"),
            ("credit_products", "product_type"): ("CONSUMER_LOAN", "MORTGAGE", "CREDIT_CARD", "OVERDRAFT", "LEASING", "OTHER"),
            ("credit_products", "currency"): ("RON", "EUR", "USD", "CHF"),
            ("credit_products", "rate_type"): ("FIXED", "VARIABLE"),
            ("credit_products", "status"): ("ACTIVE", "CLOSED", "WRITTEN_OFF", "ASSIGNED", "IN_INSOLVENCY_PROCEDURE"),
            ("product_participants", "role"): ("DEBTOR", "CODEBTOR", "GUARANTOR"),
            ("credit_events", "event_type"): ("RESTRUCTURING", "REFINANCING", "DATION_IN_PAYMENT", "CONTRACT_ASSIGNMENT", "DEBT_ASSIGNMENT", "PAYMENT_SUSPENSION"),
            ("bureau_inquiries", "inquiry_type"): ("SOFT", "HARD"),
            ("fico_scores", "status"): ("SCORED", "NO_SCORE"),
            ("insolvency_records", "procedure_type"): ("DEBT_REPAYMENT_PLAN", "ASSET_LIQUIDATION", "SIMPLIFIED"),
        }
        for (table, column), values in enums.items():
            for value in values:
                with self.subTest(table=table, column=column, value=value):
                    self.db.execute("SAVEPOINT enum_case")
                    extra = ""
                    if (table, column) == ("credit_products", "status"):
                        extra = ", closed_on='2026-09-30'" if value == "CLOSED" else ", closed_on=NULL"
                    if (table, column) == ("fico_scores", "status"):
                        extra = ", score=700" if value == "SCORED" else ", score=NULL"
                    self.db.execute(f"UPDATE {table} SET {column}=?{extra}", (value,))
                    self.db.execute("ROLLBACK TO enum_case")
                    self.db.execute("RELEASE enum_case")
            for value in ("UNKNOWN", "", values[0].lower()):
                self.rejected(f"UPDATE {table} SET {column}=?", (value,))

    def test_required_columns_reject_null_on_update(self):
        self.seed_all_tables()
        tables = [r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            for column in self.db.execute(f"PRAGMA table_info({table})").fetchall():
                if column[3]:
                    with self.subTest(table=table, column=column[1]):
                        self.rejected(f'UPDATE {table} SET "{column[1]}"=NULL')

    def test_all_foreign_keys_reject_missing_parents(self):
        self.seed_all_tables()
        tables = [r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            for fk in self.db.execute(f"PRAGMA foreign_key_list({table})").fetchall():
                with self.subTest(table=table, column=fk[3]):
                    missing = "9999999999999" if fk[3] == "cnp" else 999999
                    self.rejected(f'UPDATE {table} SET "{fk[3]}"=?', (missing,))

    def test_parent_deletions_are_blocked_without_partial_changes(self):
        self.seed_all_tables()
        for table in ("persons", "employers", "lenders"):
            before = list(self.db.iterdump())
            self.rejected(f"DELETE FROM {table}")
            self.assertEqual(list(self.db.iterdump()), before)

    def test_money_finite_nonnegative_and_positive_boundaries(self):
        self.seed_all_tables()
        columns = {
            "income_records": ("gross_amount_ron", "net_amount_ron"),
            "monthly_salary_declarations": ("gross_ron", "net_ron", "contributions_ron"),
            "credit_products": ("amount_granted", "amount_granted_ron", "interest_rate"),
            "payment_history": ("amount_owed", "instalment_due", "amount_paid", "overdue_amount"),
        }
        self.db.execute("UPDATE income_records SET net_amount_ron=0")
        self.db.execute("UPDATE monthly_salary_declarations SET net_ron=0")
        for table, fields in columns.items():
            for field in fields:
                for invalid in (-1, float("inf"), -float("inf"), "invalid", b"12"):
                    with self.subTest(table=table, field=field, invalid=invalid):
                        self.rejected(f"UPDATE {table} SET {field}=?", (invalid,))
                if field in ("amount_granted", "amount_granted_ron"):
                    self.rejected(f"UPDATE {table} SET {field}=0")
                else:
                    self.db.execute(f"UPDATE {table} SET {field}=0")
        # The Python adapter turns NaN into NULL; required money rejects it.
        self.rejected("UPDATE credit_products SET amount_granted=?", (float("nan"),))
        self.db.execute("UPDATE credit_products SET amount_granted=1e100, interest_rate=NULL")
        self.assertTrue(math.isfinite(self.db.execute("SELECT amount_granted FROM credit_products").fetchone()[0]))

    def test_net_infinity_rejected_even_when_gross_is_largest_finite(self):
        self.seed_all_tables()
        for table, gross, net in (("income_records", "gross_amount_ron", "net_amount_ron"),
                                  ("monthly_salary_declarations", "gross_ron", "net_ron")):
            self.db.execute(f"UPDATE {table} SET {gross}=1.7976931348623157e308")
            self.rejected(f"UPDATE {table} SET {net}=?", (float("inf"),))

    def test_cnp_ascii_length_hidden_null_and_blob(self):
        for value in ("1234567890123\x00X", b"1234567890123", "１２３４５６７８９０１２３", " 123456789012",
                      "123456789012 ", "123456789012\n", "", None):
            with self.subTest(value=value):
                self.rejected("INSERT INTO persons(cnp, first_name, last_name, birth_date) VALUES (?, 'A', 'B', '1990-01-01')", (value,))
        self.db.execute("INSERT INTO persons(cnp, first_name, last_name, birth_date) VALUES ('0123456789012', 'A', 'B', '1990-01-01')")
        self.assertEqual(self.db.execute("SELECT cnp FROM persons").fetchone()[0], "0123456789012")

    def test_date_validation_on_every_date_column(self):
        self.seed_all_tables()
        columns = {"persons": ("birth_date",), "employments": ("start_date", "end_date"),
                   "income_activity_forms": ("start_date", "end_date"), "report_params": ("as_of_date",),
                   "credit_products": ("opened_on",), "credit_events": ("event_date",),
                   "bureau_inquiries": ("inquiry_date",), "fico_scores": ("calculated_on",),
                   "insolvency_records": ("opened_on", "closed_on"), "card_fraud_records": ("recorded_on",)}
        for table, fields in columns.items():
            for field in fields:
                for invalid in ("2025-02-29", "2026-04-31", "2026-00-01", "2026-01-00", "2026-10-01\x00X", "2026-1-01"):
                    with self.subTest(table=table, field=field, invalid=invalid):
                        self.rejected(f"UPDATE {table} SET {field}=?", (invalid,))

    def test_generated_category_updates_and_cannot_be_overwritten(self):
        self.seed_core()
        self.product()
        self.history()
        for dpd, category in ((0, "CURRENT"), (30, "1-30"), (31, "31-60"), (60, "31-60"),
                              (61, "61-90"), (90, "61-90"), (91, "91-180"), (180, "91-180"), (181, "180+")):
            self.db.execute("UPDATE payment_history SET days_past_due=?", (dpd,))
            self.assertEqual(self.db.execute("SELECT delay_category FROM payment_history").fetchone()[0], category)
        with self.assertRaises(sqlite3.OperationalError):
            self.db.execute("UPDATE payment_history SET delay_category='CURRENT'")
        with self.assertRaises(sqlite3.OperationalError):
            self.db.execute("INSERT INTO payment_history(product, month, delay_category) VALUES (1, '2026-10-01', 'CURRENT')")
        for field in ("days_past_due", "overdue_instalments"):
            for invalid in (-1, 0.5):
                self.rejected(f"UPDATE payment_history SET {field}=?", (invalid,))

    def test_revolving_terms_and_closure_chronology(self):
        self.seed_core()
        for ident, kind in enumerate(("CREDIT_CARD", "OVERDRAFT"), 1):
            self.product(ident, kind=kind)
        self.rejected("UPDATE credit_products SET product_type='MORTGAGE' WHERE id=1")
        self.rejected("UPDATE credit_products SET status='CLOSED', closed_on='2019-12-31' WHERE id=1")
        self.db.execute("UPDATE credit_products SET status='CLOSED', closed_on=opened_on WHERE id=1")


class IntegrationTests(DatabaseTestCase):
    def test_failed_import_transaction_rolls_back_entire_batch(self):
        self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                self.seed_core()
                self.product()
                self.history()
                self.history()  # Duplicate key aborts import; context rolls back.
        verify_empty(self.db)

    def test_persistence_reopen_and_connection_foreign_keys(self):
        self.seed_core()
        self.product()
        self.history(dpd=31)
        self.db.commit()
        before = tuple(self.row("v_bureau_summary"))
        with tempfile.TemporaryDirectory(prefix="credit_sources_test_") as directory:
            target = Path(directory) / "persistent.db"
            saved = sqlite3.connect(target)
            self.db.backup(saved)
            saved.close()
            reopened = sqlite3.connect(target)
            try:
                reopened.execute("PRAGMA foreign_keys=ON")
                self.assertEqual(reopened.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                with self.assertRaises(sqlite3.IntegrityError):
                    reopened.execute("INSERT INTO product_participants VALUES (999, ?, 'DEBTOR')", (DEBTOR,))
                self.assertEqual(reopened.execute("SELECT delay_category FROM payment_history").fetchone()[0], "31-60")
                self.assertEqual(reopened.execute("SELECT * FROM v_bureau_summary WHERE cnp=?", (DEBTOR,)).fetchone(), before)
                self.assertEqual(reopened.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(reopened.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                reopened.close()


class FictionalDataQualityTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.cnp = "1900115010011"  # Fictional syntax/date-consistent identifier; no checksum claim.
        self.db.execute("INSERT INTO persons VALUES (?, 'Test', 'Person', '1990-01-15', NULL, NULL, NULL)", (self.cnp,))
        self.db.execute("INSERT INTO lenders VALUES (1, 'Fictional Bank', 'BANK')")
        self.db.execute("INSERT INTO employers VALUES (1, 'Fictional Employer', 'TEST1', NULL)")
        self.product(cnp=self.cnp, opened="2025-01-15", status="CLOSED", closed="2025-03-15")
        self.history(month="2025-01-01", owed=25000)
        self.history(month="2025-02-01", owed=24000)
        self.history(month="2025-03-01", owed=0)
        self.db.execute("INSERT INTO employments VALUES (1, ?, 1, '2025-01-15', '2025-03-15', 'FIXED_TERM')", (self.cnp,))
        for month in ("2025-01-01", "2025-03-01"):
            self.db.execute("INSERT INTO monthly_salary_declarations VALUES (?, 1, ?, 1000, 800, 200)", (self.cnp, month))
        self.db.execute("INSERT INTO income_records VALUES (1, ?, 2025, 'SALARY', 'Fictional Employer', 'TEST1', 3000, 2400)", (self.cnp,))

    def issues(self):
        return fictional_data_issues(self.db, {self.cnp: "M"}, (1,))

    def test_valid_fixture_accepts_partial_opening_closing_and_employment_months(self):
        self.assertEqual(self.issues(), [])

    def test_history_outside_lifetime_and_event_before_opening_flagged(self):
        self.history(month="2024-12-01")
        self.history(month="2025-04-01")
        self.db.execute("INSERT INTO credit_events VALUES (1, 1, '2025-01-14', 'RESTRUCTURING', NULL)")
        codes = [code for code, _ in self.issues()]
        self.assertEqual(codes.count("history_outside_product_months"), 2)
        self.assertIn("event_before_opening", codes)

    def test_delinquency_requires_positive_overdue_in_generated_data(self):
        self.db.execute("UPDATE payment_history SET days_past_due=31 WHERE month='2025-02-01'")
        self.assertIn("delinquency_without_overdue", [code for code, _ in self.issues()])
        self.db.execute("UPDATE payment_history SET overdue_amount=100 WHERE days_past_due>0")
        self.assertEqual(self.issues(), [])

    def test_amortizer_increase_requires_explanatory_event(self):
        self.db.execute("UPDATE payment_history SET amount_owed=26000 WHERE month='2025-02-01'")
        self.assertIn("unexplained_balance_increase", [code for code, _ in self.issues()])
        for event in ("RESTRUCTURING", "REFINANCING"):
            self.db.execute("DELETE FROM credit_events")
            self.db.execute("INSERT INTO credit_events VALUES (1, 1, '2025-02-15', ?, NULL)", (event,))
            self.assertEqual(self.issues(), [])
        self.db.execute("UPDATE credit_events SET event_date='2025-03-01'")
        self.assertIn("unexplained_balance_increase", [code for code, _ in self.issues()])

    def test_revolving_and_fx_increases_are_not_universal_errors(self):
        self.product(2, kind="CREDIT_CARD", cnp=self.cnp)
        self.history(product=2, month="2025-01-01", owed=100)
        self.history(product=2, month="2025-02-01", owed=200)
        self.assertEqual(self.issues(), [])
        with self.assertRaises(ValueError):
            fictional_data_issues(self.db, amortizing_products=(2,))
        self.db.execute("UPDATE credit_products SET currency='EUR' WHERE id=2")
        self.assertEqual(self.issues(), [])

    def test_salary_outside_job_and_wrong_annual_source_flagged(self):
        self.db.execute("INSERT INTO monthly_salary_declarations VALUES (?, 1, '2025-04-01', 1000, 800, 200)", (self.cnp,))
        self.db.execute("UPDATE income_records SET source_fiscal_code='WRONG'")
        codes = [code for code, _ in self.issues()]
        self.assertIn("salary_outside_employment", codes)
        self.assertIn("salary_source_mismatch", codes)

    def test_multiple_employers_same_year_match_fiscal_codes_not_names(self):
        self.db.execute("INSERT INTO employers VALUES (2, 'Second Employer', 'TEST2', NULL)")
        self.db.execute("INSERT INTO employments VALUES (2, ?, 2, '2025-06-01', NULL, 'INDEFINITE')", (self.cnp,))
        self.db.execute("INSERT INTO income_records VALUES (2, ?, 2025, 'SALARY', 'Alternative spelling', 'TEST2', 12000, 10000)", (self.cnp,))
        self.assertEqual(self.issues(), [])

    def test_cnp_birth_date_and_external_sex_metadata(self):
        self.db.execute("UPDATE persons SET birth_date='1991-01-15'")
        self.assertIn("cnp_identity_mismatch", [code for code, _ in self.issues()])
        self.db.execute("UPDATE persons SET birth_date='1990-01-15'")
        issues = fictional_data_issues(self.db, {self.cnp: "F"})
        self.assertIn("cnp_identity_mismatch", [code for code, _ in issues])
        # Test the supported century/sex categories independently of schema syntax.
        for prefix, birth, sex in (("2", "1990-01-15", "F"), ("3", "1890-01-15", "M"),
                                    ("4", "1890-01-15", "F"), ("5", "2090-01-15", "M"), ("6", "2090-01-15", "F")):
            cnp = prefix + self.cnp[1:]
            self.db.execute("INSERT INTO persons VALUES (?, 'Test', 'Person', ?, NULL, NULL, NULL)", (cnp, birth))
            metadata = {r[0]: ("M" if int(r[0][0]) % 2 else "F") for r in self.db.execute("SELECT cnp FROM persons")}
            self.assertEqual(fictional_data_issues(self.db, metadata), [])

    def test_exactly_one_debtor_checked_after_complete_load(self):
        self.db.execute("UPDATE product_participants SET role='GUARANTOR'")
        self.assertIn("debtor_count", [code for code, _ in self.issues()])
        self.db.execute("UPDATE product_participants SET role='DEBTOR'")
        self.db.execute("INSERT INTO persons VALUES (?, 'Test', 'Other', '1990-01-01', NULL, NULL, NULL)", (DEBTOR,))
        self.db.execute("INSERT INTO product_participants VALUES (1, ?, 'DEBTOR')", (DEBTOR,))
        self.assertIn("debtor_count", [code for code, _ in fictional_data_issues(self.db)])
        self.db.execute("UPDATE product_participants SET role='CODEBTOR' WHERE cnp=?", (DEBTOR,))
        self.assertEqual(fictional_data_issues(self.db), [])

    def test_unsupported_cnp_category_is_reported_not_guessed(self):
        cnp = "7900115010011"
        self.db.execute("INSERT INTO persons VALUES (?, 'Test', 'Person', '1990-01-15', NULL, NULL, NULL)", (cnp,))
        issues = fictional_data_issues(self.db, {self.cnp: "M", cnp: "M"})
        self.assertIn(("cnp_unsupported_or_invalid", (cnp,)), issues)


class GeneratedFixtureTests(DatabaseTestCase):
    """Validate delivered-style datasets, never the user's on-disk database."""

    def setUp(self):
        super().setUp()
        self.manifest = fixtures.build_fixture(self.db, random_people=12)
        self.cnps = {item["tag"]: item["cnp"] for item in self.manifest["scenarios"]}

    @staticmethod
    def snapshot(db):
        return {table: sorted([tuple(row) for row in db.execute(f"SELECT * FROM {table}")], key=repr)
                for table in ("report_params",) + fixtures.TABLES}

    def test_generated_dataset_passes_quality_and_every_view_has_rows(self):
        counts = fixtures.validate_fixture(self.db, self.manifest)
        self.assertEqual(len(counts), 12)
        self.assertTrue(all(count > 0 for count in counts.values()))
        self.assertEqual(len(self.manifest["scenarios"]), 73)
        self.assertEqual(self.manifest["table_counts"]["persons"], 85)
        self.assertEqual(fictional_data_issues(self.db, self.manifest["sex_by_cnp"],
                                             self.manifest["amortizing_products"]), [])

    def test_same_seed_reproduces_data_and_different_seed_changes_background(self):
        for seed in (fixtures.DEFAULT_SEED, fixtures.DEFAULT_SEED + 1):
            other = fixtures.new_database()
            try:
                manifest = fixtures.build_fixture(other, seed=seed, random_people=12)
                fixtures.validate_fixture(other, manifest)
                if seed == fixtures.DEFAULT_SEED:
                    self.assertEqual(manifest, self.manifest)
                    self.assertEqual(fixtures.export_data_sql(other), fixtures.export_data_sql(self.db))
                else:
                    self.assertNotEqual(self.snapshot(other)["persons"], self.snapshot(self.db)["persons"])
            finally:
                other.close()

    def test_export_round_trip_preserves_every_table_and_generated_value(self):
        sql = fixtures.export_data_sql(self.db)
        self.assertIn("Employer''s Studio", sql)
        self.assertNotIn("delay_category", sql)
        replay = fixtures.new_database()
        try:
            replay.executescript(sql)
            fixtures.validate_fixture(replay, self.manifest)
            self.assertEqual(self.snapshot(replay), self.snapshot(self.db))
        finally:
            replay.close()

    def test_second_sql_import_is_rejected_without_modifying_data(self):
        before = self.snapshot(self.db)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.executescript(fixtures.export_data_sql(self.db))
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.snapshot(self.db), before)

    def test_all_product_currency_status_income_and_delay_variants_are_present(self):
        expectations = {
            ("credit_products", "product_type"): {"CONSUMER_LOAN", "MORTGAGE", "CREDIT_CARD", "OVERDRAFT", "LEASING", "OTHER"},
            ("credit_products", "currency"): {"RON", "EUR", "USD", "CHF"},
            ("credit_products", "status"): {"ACTIVE", "CLOSED", "WRITTEN_OFF", "ASSIGNED", "IN_INSOLVENCY_PROCEDURE"},
            ("credit_products", "rate_type"): {"FIXED", "VARIABLE"},
            ("lenders", "lender_type"): {"BANK", "IFN", "LEASING", "INSURER", "DEBT_COLLECTOR"},
            ("product_participants", "role"): {"DEBTOR", "CODEBTOR", "GUARANTOR"},
            ("income_records", "income_type"): {"SALARY", "INDEPENDENT_ACTIVITY", "PENSION", "SOCIAL_INSURANCE", "RENTAL", "INVESTMENT", "OTHER"},
            ("income_activity_forms", "form_type"): {"PFA", "II", "IF", "LIBERAL_PROFESSION"},
            ("employments", "contract_type"): {"INDEFINITE", "FIXED_TERM", "PART_TIME"},
            ("payment_history", "delay_category"): {"CURRENT", "1-30", "31-60", "61-90", "91-180", "180+"},
            ("fico_reason_codes", "rank"): {1, 2, 3, 4, 5},
            ("fico_scores", "status"): {"SCORED", "NO_SCORE"},
        }
        for (table, column), expected in expectations.items():
            with self.subTest(table=table, column=column):
                self.assertEqual({r[0] for r in self.db.execute(f"SELECT DISTINCT {column} FROM {table}")}, expected)

    def test_generated_delay_boundaries_and_same_month_cross_source_figures(self):
        for dpd, category in ((0, "CURRENT"), (1, "1-30"), (30, "1-30"), (31, "31-60"), (60, "31-60"),
                              (61, "61-90"), (90, "61-90"), (91, "91-180"), (180, "91-180"), (181, "180+")):
            row = self.row("v_bureau_products", self.cnps[f"DELAY_{dpd:03d}"])
            self.assertEqual((row["days_past_due"], row["delay_category"]), (dpd, category))
        rows = self.db.execute("""SELECT b.amount_owed,c.amount_owed,b.instalment_due,c.instalment_due,
            b.days_past_due,c.days_past_due,b.overdue_amount,c.overdue_amount
            FROM v_bureau_products b JOIN v_crc_exposures c
            ON b.cnp=c.cnp AND b.product=c.product AND b.payment_month=c.payment_month""").fetchall()
        self.assertGreater(len(rows), 10)
        for row in rows:
            self.assertEqual(tuple(row[::2]), tuple(row[1::2]))

    def test_generated_calendar_history_score_and_income_time_travel(self):
        cnp = self.cnps["CALENDAR_TIME_TRAVEL"]
        baseline = self.snapshot(self.db)
        for day, month, snapshot in (("2024-03-01", "2024-02-01", "2024-02-29"),
                                     ("2025-03-01", "2025-02-01", "2025-02-28"),
                                     ("2027-01-05", "2026-12-01", "2026-12-31")):
            with self.subTest(day=day):
                self.db.execute("UPDATE report_params SET as_of_date=?", (day,))
                row = self.row("v_crc_exposures", cnp)
                self.assertEqual((row["payment_month"], row["snapshot_date"]), (month, snapshot))
        years = [r[0] for r in self.db.execute("SELECT fiscal_year FROM v_anaf_income WHERE cnp=? ORDER BY fiscal_year", (cnp,))]
        self.assertEqual(years, [2024, 2025, 2026])
        self.db.execute("UPDATE report_params SET as_of_date='2026-08-15'")
        self.assertEqual(self.row("v_bureau_latest_score", self.cnps["SCORE_TIME_TRAVEL"])["score"], 300)
        self.assertEqual(self.row("v_bureau_products", cnp)["payment_month"], "2026-08-01")
        self.assertIsNone(self.row("v_bureau_products", self.cnps["OPENED_ON_D"]))
        self.db.execute("UPDATE report_params SET as_of_date=?", (fixtures.AS_OF_DATE,))
        self.assertEqual(self.snapshot(self.db), baseline)
        fixtures.validate_fixture(self.db, self.manifest)

    def test_cnp_metadata_fictional_contacts_and_invalid_official_checksums(self):
        for row in self.db.execute("SELECT cnp, last_name, phone FROM persons"):
            checksum = sum(int(a) * int(b) for a, b in zip(row["cnp"][:12], "279146358279")) % 11
            checksum = 1 if checksum == 10 else checksum
            self.assertNotEqual(int(row["cnp"][-1]), checksum)
            self.assertTrue(row["last_name"].startswith("FICTIV_"))
            self.assertIsNone(row["phone"])
        self.assertEqual(len(self.manifest["sex_by_cnp"]), self.manifest["table_counts"]["persons"])

    def test_seed_parameters_and_populated_builder_are_rejected_safely(self):
        before = self.snapshot(self.db)
        for count in (-1, 5001, 0):
            with self.assertRaises(ValueError):
                fixtures.build_fixture(self.db, random_people=count)
        self.assertEqual(self.snapshot(self.db), before)

    def test_loader_backs_up_empty_database_and_refuses_populated_target(self):
        with tempfile.TemporaryDirectory(prefix="credit_fixture_loader_") as directory:
            target = Path(directory) / "target.db"
            db = sqlite3.connect(target)
            db.executescript(SCHEMA)
            db.close()
            sql = fixtures.export_data_sql(self.db)
            backup = fixtures.load_empty_target(target, sql, self.manifest)
            saved = sqlite3.connect(backup)
            try:
                verify_empty(saved)
            finally:
                saved.close()
            with self.assertRaisesRegex(ValueError, "populated"):
                fixtures.load_empty_target(target, sql, self.manifest)
            populated = sqlite3.connect(target)
            try:
                self.assertEqual(self.snapshot(populated), self.snapshot(self.db))
            finally:
                populated.close()

    def test_loader_rolls_back_when_postload_validation_fails(self):
        with tempfile.TemporaryDirectory(prefix="credit_fixture_rollback_") as directory:
            target = Path(directory) / "target.db"
            db = sqlite3.connect(target)
            db.executescript(SCHEMA)
            db.execute("UPDATE report_params SET as_of_date='2025-01-01'")
            db.commit()
            db.close()
            bad_manifest = dict(self.manifest, table_counts=dict(self.manifest["table_counts"], persons=-1))
            with self.assertRaisesRegex(ValueError, "Row count mismatch"):
                fixtures.load_empty_target(target, fixtures.export_data_sql(self.db), bad_manifest)
            unchanged = sqlite3.connect(target)
            try:
                verify_empty(unchanged)
                self.assertEqual(unchanged.execute("SELECT as_of_date FROM report_params").fetchone()[0], "2025-01-01")
            finally:
                unchanged.close()


class OrganizedLayoutTests(unittest.TestCase):
    def test_entry_points_resolve_paths_from_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory(prefix="credit_layout_") as directory:
            commands = (
                [sys.executable, "-B", str(ROOT / "scripts" / "credit_sources" / "generate_credit_sources.py"), "--help"],
                [sys.executable, "-B", str(ROOT / "scripts" / "credit_sources" / "generate_credit_sources.py"),
                 "--random-people", "0", "--output-dir", directory],
                [sys.executable, "-B", str(ROOT / "scripts" / "credit_sources" / "verify_credit_sources.py"), "--help"],
                [sys.executable, "-B", str(ROOT / "tests" / "credit_sources" / "test_credit_sources.py"),
                 "CreditSourcesTests.test_empty_schema_and_singleton"],
            )
            for command in commands:
                with self.subTest(entry=command[2]):
                    result = subprocess.run(command, cwd=directory, capture_output=True, text=True,
                                            encoding="utf-8", errors="replace", timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((Path(directory) / "sample_data_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["table_counts"]["persons"], 73)
        self.assertEqual(fixtures.SCHEMA_PATH, ROOT / "data" / "synthetic" / "credit_sources" / "credit_sources.sql")
        self.assertEqual(fixtures.SAMPLE_DIR, ROOT / "data" / "synthetic" / "credit_sources")

    def test_readonly_verifier_roundtrip_and_mismatch_detection(self):
        with tempfile.TemporaryDirectory(prefix="credit_saved_verification_") as directory:
            root = Path(directory)
            target = root / "fixture.db"
            db = sqlite3.connect(target)
            db.row_factory = sqlite3.Row
            try:
                db.executescript(SCHEMA)
                manifest = fixtures.build_fixture(db, random_people=0)
                (root / "sample_data_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                (root / "credit_sources_sample_data.sql").write_text(fixtures.export_data_sql(db), encoding="utf-8")
            finally:
                db.close()
            baseline = hashlib.sha256(target.read_bytes()).hexdigest()
            self.assertEqual(len(verify_saved_database(target, root, replay=True)), 12)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), baseline)
            db = sqlite3.connect(target)
            try:
                db.execute("UPDATE persons SET address='Changed fictional address' WHERE persona_tag='NO_HISTORY'")
                db.commit()
            finally:
                db.close()
            changed = hashlib.sha256(target.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "Saved rows differ"):
                verify_saved_database(target, root, replay=True)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), changed)

    def test_verifier_does_not_create_missing_database_or_change_reference_date(self):
        with tempfile.TemporaryDirectory(prefix="credit_readonly_") as directory:
            root = Path(directory)
            (root / "sample_data_manifest.json").write_text("{}", encoding="utf-8")
            missing = root / "missing.db"
            with self.assertRaises(sqlite3.OperationalError):
                verify_saved_database(missing, root)
            self.assertFalse(missing.exists())
            target = root / "fixture.db"
            db = sqlite3.connect(target)
            db.row_factory = sqlite3.Row
            try:
                db.executescript(SCHEMA)
                manifest = fixtures.build_fixture(db, random_people=0)
                db.execute("UPDATE report_params SET as_of_date='2025-01-01'")
                db.commit()
                (root / "sample_data_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            finally:
                db.close()
            before = hashlib.sha256(target.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "reference date"):
                verify_saved_database(target, root)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)


class PerformanceTests(DatabaseTestCase):
    def test_all_views_per_cnp_at_realistic_volume(self):
        if os.environ.get("CREDIT_SOURCES_BENCHMARK") != "1":
            self.skipTest("opt-in: --benchmark")
        self.seed_core()
        people = 3000
        cnps = [f"1900115{i:06d}" for i in range(1, people + 1)]
        self.db.executemany("INSERT INTO persons(cnp, first_name, last_name, birth_date) VALUES (?, 'Test', 'Person', '1990-01-15')", [(c,) for c in cnps])
        self.db.executemany("""INSERT INTO credit_products(id,lender,product_type,opened_on,term_months,
            amount_granted,amount_granted_ron,rate_type) VALUES (?,1,'CONSUMER_LOAN','2024-01-01',60,50000,50000,'FIXED')""",
            [(i,) for i in range(1, people * 2 + 1)])
        self.db.executemany("INSERT INTO product_participants VALUES (?, ?, 'DEBTOR')",
                            [(i, cnps[(i-1)//2]) for i in range(1, people * 2 + 1)])
        months = [f"{2024 + m//12}-{m%12+1:02d}-01" for m in range(34)]
        self.db.executemany("""INSERT INTO payment_history(product,month,amount_owed,instalment_due,amount_paid,
            overdue_amount,overdue_instalments,days_past_due) VALUES (?,?,?,500,500,0,0,0)""",
            ((i, month, 50000 - m * 500) for i in range(1, people * 2 + 1) for m, month in enumerate(months)))
        for table, sql, rows in (
            ("income", "INSERT INTO income_records VALUES (NULL, ?, ?, 'SALARY', 'Test', 'TEST1', 90000, 60000)", ((c, y) for c in cnps for y in (2023, 2024, 2025))),
            ("activity", "INSERT INTO income_activity_forms VALUES (NULL, ?, 'PFA', 'Test', NULL, NULL, '2020-01-01', NULL)", ((c,) for c in cnps)),
            ("inquiries", "INSERT INTO bureau_inquiries VALUES (NULL, ?, 1, '2026-10-01', 'HARD')", ((c,) for c in cnps)),
            ("scores", "INSERT INTO fico_scores VALUES (?, ?, '2026-10-01', 700, 'SCORED')", enumerate(cnps, 1)),
            ("reasons", "INSERT INTO fico_reason_codes VALUES (?, 1, 'A', 'Test')", ((i,) for i in range(1, people+1))),
            ("events", "INSERT INTO credit_events VALUES (NULL, ?, '2026-09-01', 'RESTRUCTURING', NULL)", ((i,) for i in range(1, people*2+1))),
            ("insolvency", "INSERT INTO insolvency_records VALUES (NULL, ?, 'SIMPLIFIED', '2020-01-01', NULL, 'Test')", ((c,) for c in cnps)),
            ("fraud", "INSERT INTO card_fraud_records VALUES (NULL, ?, 1, '2026-09-01', 'Test')", ((c,) for c in cnps)),
        ):
            self.db.executemany(sql, rows)
        self.db.commit()
        self.db.execute("ANALYZE")
        print(f"\nBenchmark: SQLite {sqlite3.sqlite_version}; {platform.platform()}; {platform.machine()}; "
              f"{people} people, {people*2} products, {people*2*len(months)} history rows; in-memory, warm cache")
        limit = float(os.environ.get("CREDIT_SOURCES_MAX_P95_MS", "0"))
        for (view,) in self.db.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name").fetchall():
            sql = f"SELECT * FROM {view} WHERE cnp=?"
            plan = [r[3] for r in self.db.execute("EXPLAIN QUERY PLAN " + sql, (cnps[0],))]
            self.assertTrue(any("SEARCH" in step and ("INDEX" in step or "PRIMARY KEY" in step) for step in plan), (view, plan))
            if view in ("v_bureau_summary", "v_dsti_inputs"):
                # Aliases from the schema: no full participant/income/inquiry/score
                # scan for a single CNP. Small lender/parameter scans are fine.
                forbidden = {"pp", "i", "q", "s", "s2", "y", "h", "h2", "w"}
                self.assertFalse([p for p in plan if p.startswith("SCAN ") and p.split()[1] in forbidden], (view, plan))
            samples = []
            for cnp in (cnps[0], cnps[1500], cnps[-1]):
                self.db.execute(sql, (cnp,)).fetchall()  # Warmup.
                for _ in range(7):
                    start = time.perf_counter()
                    rows = self.db.execute(sql, (cnp,)).fetchall()
                    samples.append((time.perf_counter() - start) * 1000)
                    self.assertTrue(rows, view)
                    self.assertTrue(all(r["cnp"] == cnp for r in rows), view)
            p95 = sorted(samples)[math.ceil(len(samples)*0.95)-1]
            print(f"{view}: median={statistics.median(samples):.3f}ms p95={p95:.3f}ms; "
                  f"scans={[p for p in plan if 'SCAN' in p]}")
            if limit:
                self.assertLessEqual(p95, limit, f"{view}: configured p95 budget exceeded")
        for view in ("v_bureau_summary", "v_dsti_inputs"):
            start = time.perf_counter()
            rows = self.db.execute(f"SELECT * FROM {view}").fetchall()
            self.assertEqual(len(rows), people + 3)
            print(f"{view}: full-report={1000*(time.perf_counter()-start):.3f}ms ({len(rows)} rows)")


if __name__ == "__main__":
    if "--benchmark" in sys.argv:
        sys.argv.remove("--benchmark")
        os.environ["CREDIT_SOURCES_BENCHMARK"] = "1"
    create = "--create" in sys.argv
    if create:
        sys.argv.remove("--create")
    if sqlite3.sqlite_version_info < (3, 35, 0):
        raise SystemExit("SQLite 3.35 or newer is required")
    print(f"Testing with SQLite {sqlite3.sqlite_version}", flush=True)
    result = unittest.main(verbosity=2, exit=False, testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2)).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if create:
        target = ROOT / "data" / "local" / "credit_sources.db"
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental replacement of user data.
        with target.open("xb"):
            pass
        with sqlite3.connect(target) as db:
            db.executescript(SCHEMA)
            verify_empty(db)
        db.close()
        print(f"Created and verified empty database: {target}")