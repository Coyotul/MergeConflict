"""ANAF adapter tests over temporary copies of the owner's unchanged SQL fixture."""

import asyncio
import hashlib
import json
import sqlite3
import unittest
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from scripts.credit_sources.setup import create_database
from src.core.eligibility_demo import build_demo_service
from src.integrations.anaf.sqlite import (
    DEFAULT_MANIFEST, AnafIdentityBindings, SqliteAnafProvider,
)
from src.models.eligibility import EvidenceSource, IncomeBasis, ProviderQuery
from src.security.eligibility import ActorContext, ActorRole
from tests.fixtures.eligibility import NOW, changed_model, request, service_fixture


MANIFEST = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
SCENARIOS = {item["tag"]: item["cnp"] for item in MANIFEST["scenarios"]}


def bindings_for(*tags):
    return AnafIdentityBindings.model_validate({
        "version": "test-anaf-bindings-v1", "simulated": True,
        "bindings": [{"customer_id": f"test-{tag}", "cnp": SCENARIOS[tag], "scenario_tag": tag} for tag in tags],
    })


def query_for(tag):
    return ProviderQuery(customer_id=f"test-{tag}", authorization_id="test-income-authorization", correlation_id="test-correlation")


class SqliteAnafTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_directory = TemporaryDirectory(prefix="anaf-source-fixture-")
        try:
            cls.source_path = create_database(Path(cls.fixture_directory.name) / "credit_sources.db")
        except Exception:
            cls.fixture_directory.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.fixture_directory.cleanup()

    def setUp(self):
        self.directory = TemporaryDirectory(prefix="anaf-adapter-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "credit_sources.db"
        with closing(sqlite3.connect(self.source_path.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(self.path)) as target:
                source.backup(target)

    def update(self, statement, values=()):
        with closing(sqlite3.connect(self.path)) as database:
            database.execute("PRAGMA foreign_keys = ON")
            database.execute(statement, values)
            database.commit()

    def provider(self, *tags):
        return SqliteAnafProvider(self.path, bindings_for(*tags))

    async def test_latest_completed_salary_excludes_current_and_future_months(self):
        provider = self.provider("CALENDAR_TIME_TRAVEL")
        result = await provider.verify(query_for("CALENDAR_TIME_TRAVEL"))
        self.assertEqual(result.status.value, "SUCCESS")
        self.assertEqual(result.data.period_end, date(2026, 9, 30))
        self.assertEqual(result.data.net_monthly_income_ron, Decimal("5000.33"))
        self.assertEqual(result.data.reference_date, date(2026, 10, 28))
        self.assertTrue(result.data.recurring)
        self.assertEqual(result.data.observed_salary_months, (date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)))
        self.assertEqual(result.evidence.recorded_at.date(), date(2026, 10, 28))
        self.assertTrue(result.simulated)

    async def test_multiple_employers_are_summed_without_rental_double_counting(self):
        result = await self.provider("MULTI_SOURCE_MULTI_LOAN").verify(query_for("MULTI_SOURCE_MULTI_LOAN"))
        self.assertEqual(result.data.net_monthly_income_ron, Decimal("4000.00"))
        self.assertEqual(result.data.reported_income_types, ("RENTAL", "SALARY"))
        self.assertEqual(result.data.period_end, date(2025, 12, 31))
        self.assertEqual(result.data.income_basis, IncomeBasis.MONTHLY_SALARY)
        self.assertTrue(result.data.recurring)

    async def test_all_income_types_do_not_become_salary(self):
        result = await self.provider("ALL_INCOME_TYPES").verify(query_for("ALL_INCOME_TYPES"))
        self.assertEqual(result.data.net_monthly_income_ron, Decimal("3000.00"))
        self.assertEqual(len(result.data.reported_income_types), 7)

    async def test_zero_income_is_distinct_from_absent_income(self):
        provider = self.provider("ZERO_INCOME", "MISSING_INCOME", "NO_HISTORY", "OLD_INCOME_ONLY")
        zero = await provider.verify(query_for("ZERO_INCOME"))
        self.assertEqual(zero.status.value, "SUCCESS")
        self.assertEqual(zero.data.net_monthly_income_ron, Decimal("0.00"))
        self.assertEqual(zero.data.income_basis, IncomeBasis.ANNUAL_AVERAGE)
        self.assertFalse(zero.data.recurring)
        for tag in ("MISSING_INCOME", "NO_HISTORY", "OLD_INCOME_ONLY"):
            with self.subTest(tag=tag):
                result = await provider.verify(query_for(tag))
                self.assertEqual(result.status.value, "NOT_FOUND")
                self.assertIsNone(result.data)
                self.assertIsNone(result.evidence)

    async def test_latest_available_completed_year_not_assumed_current_year(self):
        result = await self.provider("OLDER_ELIGIBLE_YEAR").verify(query_for("OLDER_ELIGIBLE_YEAR"))
        self.assertEqual(result.data.fiscal_year, 2024)
        self.assertEqual(result.data.net_monthly_income_ron, Decimal("5000.00"))
        self.assertEqual(result.data.period_end, date(2024, 12, 31))
        self.assertFalse(result.data.recurring)

    async def test_fractional_annual_values_are_decimal_and_round_once(self):
        result = await self.provider("FRACTIONAL_ROUNDING").verify(query_for("FRACTIONAL_ROUNDING"))
        self.assertEqual(result.data.net_monthly_income_ron, Decimal("2983.54"))
        self.assertIsInstance(result.data.net_monthly_income_ron, Decimal)
        self.assertIsInstance(result.model_dump(mode="json")["data"]["net_monthly_income_ron"], str)

    async def test_mixed_annual_types_remain_historical(self):
        cnp = SCENARIOS["MULTI_SOURCE_MULTI_LOAN"]
        self.update("DELETE FROM monthly_salary_declarations WHERE cnp = ?", (cnp,))
        result = await self.provider("MULTI_SOURCE_MULTI_LOAN").verify(query_for("MULTI_SOURCE_MULTI_LOAN"))
        self.assertEqual(result.data.net_monthly_income_ron, Decimal("5000.00"))
        self.assertEqual(result.data.income_kind.value, "OTHER")
        self.assertEqual(result.data.income_basis, IncomeBasis.ANNUAL_AVERAGE)
        self.assertFalse(result.data.recurring)

    async def test_month_missing_or_new_employer_prevents_recurring_assertion(self):
        cnp = SCENARIOS["CALENDAR_TIME_TRAVEL"]
        self.update("DELETE FROM monthly_salary_declarations WHERE cnp = ? AND month = ?", (cnp, "2026-08-01"))
        result = await self.provider("CALENDAR_TIME_TRAVEL").verify(query_for("CALENDAR_TIME_TRAVEL"))
        self.assertFalse(result.data.recurring)
        self.update("INSERT INTO employments (cnp, employer, start_date, contract_type) VALUES (?, 2, '2026-09-01', 'INDEFINITE')", (cnp,))
        result = await self.provider("CALENDAR_TIME_TRAVEL").verify(query_for("CALENDAR_TIME_TRAVEL"))
        self.assertFalse(result.data.recurring)

    async def test_employment_ending_before_reporting_date_is_not_current_salary(self):
        self.update("UPDATE employments SET end_date = '2026-09-30' WHERE cnp = ?", (SCENARIOS["CALENDAR_TIME_TRAVEL"],))
        result = await self.provider("CALENDAR_TIME_TRAVEL").verify(query_for("CALENDAR_TIME_TRAVEL"))
        self.assertFalse(result.data.recurring)

    async def test_annual_fallback_is_not_usable_for_automatic_affordability(self):
        cnp = SCENARIOS["CALENDAR_TIME_TRAVEL"]
        self.update("DELETE FROM monthly_salary_declarations WHERE cnp = ?", (cnp,))
        fixture = service_fixture(self.root / "assessments.sqlite3")
        trusted_bindings = AnafIdentityBindings.model_validate({
            "version": "test-service-binding", "simulated": True,
            "bindings": [{"customer_id": "demo-customer", "cnp": cnp, "scenario_tag": "CALENDAR_TIME_TRAVEL"}],
        })
        fixture.service.providers[EvidenceSource.ANAF] = SqliteAnafProvider(self.path, trusted_bindings)
        from tests.fixtures.eligibility import CUSTOMER
        result = await fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(result.status.value, "MANUAL_REVIEW_REQUIRED")
        self.assertIn("ANAF_HISTORICAL_INCOME_ONLY", {check.reason_code for check in result.checks})
        self.assertIsNone(result.financial_assessment)

    async def test_old_monthly_data_preserves_period_and_cannot_pass_freshness(self):
        cnp = SCENARIOS["INCOME_NO_DEBT"]
        fixture = service_fixture(self.root / "assessment-old.sqlite3")
        trusted = AnafIdentityBindings.model_validate({
            "version": "test-old-binding", "simulated": True,
            "bindings": [{"customer_id": "demo-customer", "cnp": cnp, "scenario_tag": "INCOME_NO_DEBT"}],
        })
        fixture.service.providers[EvidenceSource.ANAF] = SqliteAnafProvider(self.path, trusted)
        from tests.fixtures.eligibility import CUSTOMER
        result = await fixture.service.assess(request(), CUSTOMER)
        self.assertIn("INCOME_PERIOD_INVALID", {check.reason_code for check in result.checks})
        self.assertIsNone(result.financial_assessment)

    async def test_report_date_rollover_and_leap_months_use_separate_snapshot(self):
        provider = self.provider("CALENDAR_TIME_TRAVEL")
        for as_of, period in [("2024-03-01", date(2024, 2, 29)), ("2027-01-05", date(2026, 12, 31))]:
            with self.subTest(as_of=as_of):
                self.update("UPDATE report_params SET as_of_date = ? WHERE id = 1", (as_of,))
                result = await provider.verify(query_for("CALENDAR_TIME_TRAVEL"))
                self.assertEqual(result.data.period_end, period)
                self.assertEqual(result.data.reference_date.isoformat(), as_of)

    async def test_unknown_customer_never_defaults_to_a_fixture_person(self):
        provider = self.provider("INCOME_NO_DEBT")
        result = await provider.verify(ProviderQuery(customer_id="unknown", authorization_id="auth", correlation_id="correlation"))
        self.assertEqual(result.status.value, "NOT_FOUND")

    async def test_missing_database_is_not_created_and_has_no_fallback(self):
        target = self.root / "missing" / "not-created.db"
        provider = SqliteAnafProvider(target, bindings_for("INCOME_NO_DEBT"))
        result = await provider.verify(query_for("INCOME_NO_DEBT"))
        self.assertEqual(result.status.value, "UNAVAILABLE")
        self.assertFalse(target.exists())
        self.assertFalse(target.parent.exists())

    async def test_database_and_fixture_bytes_unchanged_after_concurrent_reads(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        provider = self.provider("CALENDAR_TIME_TRAVEL", "INCOME_NO_DEBT", "ZERO_INCOME")
        tags = ("CALENDAR_TIME_TRAVEL", "INCOME_NO_DEBT", "ZERO_INCOME")
        results = await asyncio.gather(*(provider.verify(query_for(tags[index % 3])) for index in range(60)))
        self.assertTrue(all(result.status.value == "SUCCESS" for result in results))
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as database:
            self.assertEqual(database.execute("SELECT as_of_date FROM report_params").fetchone()[0], "2026-10-28")
        self.assertFalse((self.root / "credit_sources.db-journal").exists())

    async def test_validated_response_has_no_raw_cnp_or_contact_data(self):
        tag = "CALENDAR_TIME_TRAVEL"
        result = await self.provider(tag).verify(query_for(tag))
        self.assertNotIn(SCENARIOS[tag], result.model_dump_json())
        self.assertNotIn("first_name", result.model_dump_json())
        self.assertNotIn("address", result.model_dump_json())
        self.assertNotIn("phone", result.model_dump_json())

    async def test_future_salary_only_falls_back_to_completed_year_not_future_values(self):
        cnp = SCENARIOS["CALENDAR_TIME_TRAVEL"]
        self.update("DELETE FROM monthly_salary_declarations WHERE cnp = ? AND month < '2026-10-01'", (cnp,))
        result = await self.provider("CALENDAR_TIME_TRAVEL").verify(query_for("CALENDAR_TIME_TRAVEL"))
        self.assertEqual(result.data.income_basis, IncomeBasis.ANNUAL_AVERAGE)
        self.assertEqual(result.data.fiscal_year, 2025)
        self.assertEqual(result.data.net_monthly_income_ron, Decimal("5000.25"))
        self.assertFalse(result.data.recurring)

    async def test_corrupt_or_incomplete_database_never_yields_success(self):
        target = self.root / "corrupt.db"
        target.write_bytes(b"not a sqlite database")
        result = await SqliteAnafProvider(target, bindings_for("INCOME_NO_DEBT")).verify(query_for("INCOME_NO_DEBT"))
        self.assertEqual(result.status.value, "INVALID_RESPONSE")
        empty = self.root / "empty.db"
        with closing(sqlite3.connect(empty)):
            pass
        result = await SqliteAnafProvider(empty, bindings_for("INCOME_NO_DEBT")).verify(query_for("INCOME_NO_DEBT"))
        self.assertEqual(result.status.value, "UNAVAILABLE")
        self.assertIsNone(result.data)

    async def test_huge_source_income_fails_at_validated_money_boundary(self):
        self.update("UPDATE monthly_salary_declarations SET net_ron = 1e307, gross_ron = 1e308 WHERE cnp = ? AND month = '2026-09-01'", (SCENARIOS["CALENDAR_TIME_TRAVEL"],))
        result = await self.provider("CALENDAR_TIME_TRAVEL").verify(query_for("CALENDAR_TIME_TRAVEL"))
        self.assertEqual(result.status.value, "INVALID_RESPONSE")
        self.assertIsNone(result.data)

    async def test_decimal_sum_rounds_after_all_employers_not_sql_real_sum(self):
        cnp = SCENARIOS["MULTI_SOURCE_MULTI_LOAN"]
        self.update("UPDATE monthly_salary_declarations SET net_ron = 0.005 WHERE cnp = ? AND month = '2025-12-01'", (cnp,))
        result = await self.provider("MULTI_SOURCE_MULTI_LOAN").verify(query_for("MULTI_SOURCE_MULTI_LOAN"))
        self.assertEqual(result.data.net_monthly_income_ron, Decimal("0.01"))

    async def test_partial_employment_uses_latest_employer_not_ended_job(self):
        result = await self.provider("PARTIAL_EMPLOYMENT").verify(query_for("PARTIAL_EMPLOYMENT"))
        self.assertEqual(result.data.net_monthly_income_ron, Decimal("2571.42"))
        self.assertEqual(result.data.period_end, date(2025, 12, 31))
        self.assertTrue(result.data.recurring)

    async def test_source_identity_tag_conflict_is_not_ignored(self):
        self.update("UPDATE persons SET persona_tag = 'OTHER' WHERE cnp = ?", (SCENARIOS["INCOME_NO_DEBT"],))
        result = await self.provider("INCOME_NO_DEBT").verify(query_for("INCOME_NO_DEBT"))
        self.assertEqual(result.status.value, "INVALID_RESPONSE")

    async def test_missing_local_source_still_produces_auditable_review_not_dict_fallback(self):
        missing = self.root / "source-not-created.db"
        service = build_demo_service(self.root / "no-source-assessments.sqlite3", lambda: NOW, anaf_database_path=missing)
        actor = ActorContext("missing-source-actor", ActorRole.CUSTOMER, customer_id="demo-customer", permissions=frozenset({"eligibility:assess"}))
        result = await service.assess(request(), actor)
        self.assertEqual(result.status.value, "MANUAL_REVIEW_REQUIRED")
        self.assertIn("ANAF_UNAVAILABLE", {item.reason_code for item in result.checks})
        self.assertIsNone(result.financial_assessment)
        self.assertFalse(missing.exists())

    async def test_all_323_fixture_people_are_queryable_without_other_source_reads(self):
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as database:
            people = database.execute("SELECT cnp, persona_tag FROM persons ORDER BY cnp").fetchall()
        configured = AnafIdentityBindings.model_validate({
            "version": "test-all-persons-v1", "simulated": True,
            "bindings": [{"customer_id": f"fixture-person-{index}", "cnp": cnp, "scenario_tag": tag}
                         for index, (cnp, tag) in enumerate(people)],
        })
        provider = SqliteAnafProvider(self.path, configured)
        for index, (cnp, _) in enumerate(people):
            query = ProviderQuery(customer_id=f"fixture-person-{index}", authorization_id="test-auth", correlation_id="test-all")
            result = await provider.verify(query)
            self.assertIn(result.status.value, {"SUCCESS", "NOT_FOUND"})
            self.assertNotIn(cnp, result.model_dump_json())
            if result.data is not None:
                self.assertLessEqual(result.data.period_end, result.data.reference_date)
                if result.data.income_basis == IncomeBasis.ANNUAL_AVERAGE:
                    self.assertFalse(result.data.recurring)
        self.assertEqual(provider.calls, 323)

    async def test_changed_database_salary_changes_the_real_assessment(self):
        service = build_demo_service(self.root / "demo-assessments.sqlite3", lambda: NOW, anaf_database_path=self.path)
        actor = ActorContext("test-demo-customer", ActorRole.CUSTOMER, customer_id="demo-customer", permissions=frozenset({"eligibility:assess"}))
        first = await service.assess(request("sqlite-first-0001"), actor)
        self.assertEqual(first.status.value, "PRELIMINARY_REQUIREMENTS_SATISFIED")
        self.assertEqual(first.financial_assessment.verified_net_income_ron, Decimal("5000.33"))
        self.update("UPDATE monthly_salary_declarations SET net_ron = 2500 WHERE cnp = ? AND month = '2026-09-01'", (SCENARIOS["CALENDAR_TIME_TRAVEL"],))
        changed = await service.assess(request("sqlite-second-0001"), actor)
        self.assertEqual(changed.status.value, "MANUAL_REVIEW_REQUIRED")
        self.assertIn("INCOME_AMOUNT_MISMATCH", {check.reason_code for check in changed.checks})
        self.assertIsNone(changed.financial_assessment)
        self.assertNotEqual(
            next(e.evidence_id for e in first.evidence if e.source == EvidenceSource.ANAF),
            next(e.evidence_id for e in changed.evidence if e.source == EvidenceSource.ANAF),
        )

    async def test_identity_and_sql_injection_configuration_is_rejected(self):
        for cnp in ("x' OR 1=1 --", "123", "0" * 13):
            with self.subTest(cnp=cnp), self.assertRaises((ValidationError, ValueError)):
                configured = AnafIdentityBindings.model_validate({
                    "version": "test", "simulated": True,
                    "bindings": [{"customer_id": "bad", "cnp": cnp, "scenario_tag": "INCOME_NO_DEBT"}],
                })
                SqliteAnafProvider(self.path, configured)

    async def test_missing_anaf_consent_prevents_any_database_query(self):
        service = build_demo_service(self.root / "consent.sqlite3", lambda: NOW, anaf_database_path=self.path)
        actor = ActorContext("reviewer", ActorRole.REVIEWER, permissions=frozenset({"eligibility:assess"}),
                             assigned_application_ids=frozenset({"demo-app-missing-consent"}))
        missing = changed_model(request(), application_id="demo-app-missing-consent", pricing_scenario_id="demo-quote-missing-consent")
        result = await service.assess(missing, actor)
        self.assertEqual(service.providers[EvidenceSource.ANAF].calls, 0)
        self.assertIn("ANAF_AUTHORIZATION_REQUIRED", {check.reason_code for check in result.checks})