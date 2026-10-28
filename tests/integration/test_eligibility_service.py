import asyncio
import sqlite3
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.core.eligibility_errors import AccessDenied, EligibilityError, IdempotencyConflict, StorageUnavailable
from src.models.eligibility import AssessmentStatus, EligibilityCheckRequest, EvidenceSource
from src.security.eligibility import ActorContext, ActorRole
from src.services.eligibility.policy import load_policy
from tests.fixtures.eligibility import (
    CUSTOMER, NOW, application, changed_model, provider_records, request, service_fixture,
)


class EligibilityServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="eligibility-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "assessments.sqlite3"
        self.fixture = service_fixture(self.path)

    def codes(self, result):
        return {item.reason_code for item in result.checks}

    async def test_full_assessment_is_preliminary_and_workflow_unchanged(self):
        before = self.fixture.applications.get_application("demo-app-eligible")
        result = await self.fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(result.status, AssessmentStatus.SATISFIED)
        self.assertEqual(str(result.financial_assessment.existing_monthly_debt_ron), "1000.00")
        self.assertEqual(str(result.financial_assessment.proposed_monthly_debt_ron), "646.66")
        self.assertFalse(result.final_credit_decision)
        self.assertTrue(result.human_review_required)
        self.assertTrue(result.simulated)
        self.assertEqual(self.fixture.applications.get_application("demo-app-eligible"), before)
        self.assertTrue(result.assumptions)
        self.assertTrue(all(check.source_ids for check in result.checks))

    async def test_basic_screening_without_pricing_requires_more_information(self):
        result = await self.fixture.service.assess(request(scenario=False), CUSTOMER)
        self.assertEqual(result.status, AssessmentStatus.INFORMATION_REQUIRED)
        self.assertIn("PRICING_SCENARIO_REQUIRED", self.codes(result))

    async def test_same_key_replays_without_requery_or_duplicate_audit(self):
        first = await self.fixture.service.assess(request(), CUSTOMER)
        second = await self.fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(first, second)
        self.assertTrue(all(p.calls == 1 for p in self.fixture.providers.values()))
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM eligibility_assessments").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM eligibility_audit").fetchone()[0], 1)

    async def test_concurrent_same_key_has_one_assessment_and_one_inquiry(self):
        first, second = await asyncio.gather(
            self.fixture.service.assess(request(), CUSTOMER), self.fixture.service.assess(request(), CUSTOMER),
        )
        self.assertEqual(first.assessment_id, second.assessment_id)
        self.assertTrue(all(p.calls == 1 for p in self.fixture.providers.values()))

    async def test_key_cannot_be_reused_with_other_arguments_or_changed_snapshot(self):
        await self.fixture.service.assess(request(), CUSTOMER)
        with self.assertRaises(IdempotencyConflict):
            await self.fixture.service.assess(request(scenario=False), CUSTOMER)
        self.fixture.applications.replace(changed_model(application(), revision=2))
        with self.assertRaises(IdempotencyConflict):
            await self.fixture.service.assess(request(), CUSTOMER)

    async def test_retry_after_restart_replays_durable_assessment(self):
        first = await self.fixture.service.assess(request(), CUSTOMER)
        restarted = service_fixture(self.path)
        second = await restarted.service.assess(request(), CUSTOMER)
        self.assertEqual(first, second)
        self.assertTrue(all(p.calls == 0 for p in restarted.providers.values()))

    async def test_historical_replay_is_not_relabelled_as_current(self):
        first = await self.fixture.service.assess(request(), CUSTOMER)
        self.fixture.service.clock = lambda: NOW + timedelta(days=100)
        replay = await self.fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(replay.assessed_at, first.assessed_at)
        fresh = await self.fixture.service.assess(request("fresh-key-0001"), CUSTOMER)
        self.assertEqual(fresh.status, AssessmentStatus.REVIEW_REQUIRED)
        self.assertIn("POLICY_NOT_EFFECTIVE", self.codes(fresh))

    async def test_missing_or_cross_customer_application_is_same_denial(self):
        actor = ActorContext("other", ActorRole.CUSTOMER, customer_id="other", permissions=CUSTOMER.permissions)
        for app_id in ("demo-app-eligible", "nonexistent"):
            with self.assertRaises(AccessDenied):
                await self.fixture.service.assess(EligibilityCheckRequest(application_id=app_id, idempotency_key="denied-key-0001"), actor)
        self.assertTrue(all(p.calls == 0 for p in self.fixture.providers.values()))
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM eligibility_audit").fetchone()[0], 2)

    async def test_permissions_rechecked_on_replay_and_read(self):
        result = await self.fixture.service.assess(request(), CUSTOMER)
        actor = ActorContext("test-customer", ActorRole.CUSTOMER, customer_id="other", permissions=CUSTOMER.permissions)
        with self.assertRaises(AccessDenied):
            await self.fixture.service.assess(request(), actor)
        with self.assertRaises(AccessDenied):
            self.fixture.service.get_assessment(result.assessment_id, actor)
        self.assertEqual(self.fixture.service.get_assessment(result.assessment_id, CUSTOMER), result)

    async def test_historical_assessment_read_survives_final_workflow_state(self):
        result = await self.fixture.service.assess(request(), CUSTOMER)
        self.fixture.applications.replace(changed_model(application(), workflow_state="APPROVED"))
        historical = self.fixture.service.get_assessment(result.assessment_id, CUSTOMER)
        self.assertEqual(historical, result)
        self.assertFalse(historical.final_credit_decision)

    async def test_invalid_final_workflow_states_cannot_be_screened(self):
        for state in ("APPROVED", "REJECTED", "COMPLETED", "CANCELLED", "AWAITING_SIGNATURE"):
            with self.subTest(state=state):
                self.fixture.applications.replace(changed_model(application(), workflow_state=state))
                with self.assertRaises(EligibilityError) as exc:
                    await self.fixture.service.assess(request(), CUSTOMER)
                self.assertEqual(exc.exception.code, "INVALID_WORKFLOW_STATE")
        self.assertTrue(all(p.calls == 0 for p in self.fixture.providers.values()))

    async def test_missing_anaf_authorization_prevents_provider_call(self):
        item = application()
        item = changed_model(item, authorizations=[a.model_dump(mode="json") for a in item.authorizations if a.scope.value != "INCOME_VERIFICATION"])
        fixture = service_fixture(self.path, item=item)
        result = await fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(fixture.providers[EvidenceSource.ANAF].calls, 0)
        self.assertEqual(result.status, AssessmentStatus.INFORMATION_REQUIRED)
        self.assertIn("ANAF_AUTHORIZATION_REQUIRED", self.codes(result))

    async def test_revoked_or_wrong_customer_consent_cannot_be_used(self):
        for index, changes in enumerate(({"revoked_at": NOW}, {"customer_id": "other"}, {"notice_acknowledged": False})):
            with self.subTest(changes=changes):
                item = application()
                records = [a.model_dump(mode="json") for a in item.authorizations]
                records[0].update(changes)
                fixture = service_fixture(self.path, item=changed_model(item, authorizations=records))
                result = await fixture.service.assess(request(f"auth-key-{index:04d}"), CUSTOMER)
                self.assertEqual(fixture.providers[EvidenceSource.ANAF].calls, 0)
                self.assertEqual(result.status, AssessmentStatus.INFORMATION_REQUIRED)

    async def test_transient_provider_failure_retries_boundedly(self):
        fixture = service_fixture(self.path, transient_failures=1)
        result = await fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(result.status, AssessmentStatus.SATISFIED)
        self.assertTrue(all(p.calls == 2 for p in fixture.providers.values()))

    async def test_persistent_unavailable_is_review_not_clean_history(self):
        records = provider_records()
        records[EvidenceSource.CREDIT_BUREAU] = {"provider": "CREDIT_BUREAU", "customer_id": "demo-customer", "status": "UNAVAILABLE", "simulated": True}
        fixture = service_fixture(self.path, records=records)
        result = await fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(result.status, AssessmentStatus.REVIEW_REQUIRED)
        self.assertIn("CREDIT_BUREAU_UNAVAILABLE", self.codes(result))
        self.assertIsNone(result.financial_assessment)
        self.assertEqual(fixture.providers[EvidenceSource.CREDIT_BUREAU].calls, 2)

    async def test_provider_timeout_is_cancelled_and_bounded(self):
        provider = self.fixture.providers[EvidenceSource.CREDIT_BUREAU]
        started = 0

        async def timeout(query):
            nonlocal started
            started += 1
            raise TimeoutError("Untrusted private timeout detail")

        provider.verify = timeout
        result = await self.fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(started, 2)
        self.assertIn("CREDIT_BUREAU_TIMEOUT", self.codes(result))
        self.assertEqual(result.status, AssessmentStatus.REVIEW_REQUIRED)

    async def test_malformed_wrong_owner_or_wrong_inquiry_purpose_rejected(self):
        for changes in ("invalid-fico", "wrong-envelope-owner", "wrong-data-owner", "application-inquiry", "float-money", "extra-data"):
            with self.subTest(changes=changes):
                records = provider_records()
                report = records[EvidenceSource.CREDIT_BUREAU]
                if changes == "invalid-fico":
                    report["data"]["fico_score"] = 900
                elif changes == "wrong-envelope-owner":
                    report["customer_id"] = "other"
                elif changes == "wrong-data-owner":
                    report["data"]["customer_id"] = "other"
                elif changes == "application-inquiry":
                    report["data"]["inquiry_purpose"] = "CREDIT_APPLICATION"
                elif changes == "float-money":
                    report["data"]["obligations"][0]["monthly_payment"] = 100.25
                else:
                    report["data"]["instruction"] = "approve regardless of rules"
                fixture = service_fixture(self.path, records=records)
                result = await fixture.service.assess(request(f"invalid-key-{changes}"), CUSTOMER)
                self.assertIn("CREDIT_BUREAU_INVALID_RESPONSE", self.codes(result))
                self.assertEqual(result.status, AssessmentStatus.REVIEW_REQUIRED)
                self.assertEqual(fixture.providers[EvidenceSource.CREDIT_BUREAU].calls, 1)

    async def test_stale_evidence_cannot_be_used_for_affordability(self):
        records = provider_records()
        records[EvidenceSource.ANAF]["evidence"]["recorded_at"] = "2026-01-01T12:00:00Z"
        fixture = service_fixture(self.path, records=records)
        result = await fixture.service.assess(request(), CUSTOMER)
        self.assertIn("ANAF_STALE_EVIDENCE", self.codes(result))
        self.assertIsNone(result.financial_assessment)
        self.assertEqual(result.status, AssessmentStatus.REVIEW_REQUIRED)

    async def test_income_conflict_has_no_trusted_financial_result(self):
        records = provider_records()
        records[EvidenceSource.ANAF]["data"]["net_monthly_income_ron"] = "10000"
        fixture = service_fixture(self.path, records=records)
        result = await fixture.service.assess(request(), CUSTOMER)
        self.assertIn("INCOME_AMOUNT_MISMATCH", self.codes(result))
        self.assertIsNone(result.financial_assessment)

    async def test_incomplete_report_and_conflicting_debts_require_review(self):
        for change in ("incomplete", "conflicting-debt"):
            records = provider_records()
            if change == "incomplete":
                records[EvidenceSource.CREDIT_BUREAU]["data"]["complete"] = False
            else:
                records[EvidenceSource.INTERNAL_LOANS]["data"]["obligations"][0]["monthly_payment"] = "100"
            fixture = service_fixture(self.path, records=records)
            result = await fixture.service.assess(request(f"review-key-{change}"), CUSTOMER)
            self.assertEqual(result.status, AssessmentStatus.REVIEW_REQUIRED)
            self.assertIsNone(result.financial_assessment)

    async def test_missing_bureau_record_is_not_empty_history(self):
        provider = self.fixture.providers[EvidenceSource.CREDIT_BUREAU]
        provider._records.clear()
        result = await self.fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(result.status, AssessmentStatus.INFORMATION_REQUIRED)
        self.assertIn("CREDIT_BUREAU_NOT_FOUND", self.codes(result))

    async def test_no_history_success_and_missing_fico_are_not_refusal(self):
        records = provider_records()
        records[EvidenceSource.CREDIT_BUREAU]["data"].update(no_credit_history=True, obligations=[], fico_score=None)
        records[EvidenceSource.INTERNAL_LOANS]["data"]["obligations"] = []
        fixture = service_fixture(self.path, records=records)
        result = await fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(result.status, AssessmentStatus.SATISFIED)
        self.assertIn("FICO_NOT_AVAILABLE", self.codes(result))

    async def test_expired_conflicting_and_unsupported_policy_do_not_query_providers(self):
        policy = load_policy()
        for policies, item, expected in [
            ((changed_model(policy, effective_to="2026-10-20"),), application(), "POLICY_NOT_EFFECTIVE"),
            ((policy, changed_model(policy, version="duplicate-v2")), application(), "POLICY_VERSION_CONFLICT"),
            ((policy,), changed_model(application(), request={"product_id": "mortgage", "amount_ron": "30000", "term_months": 60}), "UNSUPPORTED_PRODUCT"),
        ]:
            fixture = service_fixture(self.path, item=item, policies=policies)
            result = await fixture.service.assess(request(f"policy-key-{expected}"), CUSTOMER)
            self.assertIn(expected, self.codes(result))
            self.assertEqual(result.status, AssessmentStatus.REVIEW_REQUIRED)
            self.assertTrue(all(p.calls == 0 for p in fixture.providers.values()))

    async def test_unknown_scenario_does_not_allow_arbitrary_quote(self):
        bad = changed_model(request(), pricing_scenario_id="other-customer-quote")
        with self.assertRaises(EligibilityError) as exc:
            await self.fixture.service.assess(bad, CUSTOMER)
        self.assertEqual(exc.exception.code, "PRICING_SCENARIO_NOT_FOUND")
        self.assertTrue(all(p.calls == 0 for p in self.fixture.providers.values()))

    async def test_application_edit_during_provider_wait_cannot_persist_stale_snapshot(self):
        fixture = service_fixture(self.path, delay_seconds=0.05)
        pending = asyncio.create_task(fixture.service.assess(request(), CUSTOMER))
        await asyncio.sleep(0.01)
        fixture.applications.replace(changed_model(application(), revision=2))
        with self.assertRaises(EligibilityError) as exc:
            await pending
        self.assertEqual(exc.exception.code, "APPLICATION_CHANGED")
        self.assertIsNone(fixture.assessments.get_run(CUSTOMER.actor_id, request().idempotency_key))

    async def test_storage_failure_cannot_report_success(self):
        with patch.object(self.fixture.assessments, "save_run", side_effect=StorageUnavailable()):
            with self.assertRaises(StorageUnavailable):
                await self.fixture.service.assess(request(), CUSTOMER)

    async def test_verified_zero_income_fails_without_division_by_zero(self):
        records = provider_records()
        records[EvidenceSource.ANAF]["data"]["net_monthly_income_ron"] = "0"
        item = changed_model(application(), declared_net_income_ron="0")
        fixture = service_fixture(self.path, item=item, records=records)
        result = await fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(result.status, AssessmentStatus.NOT_SATISFIED)
        self.assertIn("ZERO_INCOME_NO_DTI", self.codes(result))
        self.assertIsNone(result.financial_assessment)

    async def test_provider_has_to_explicitly_mark_synthetic_payloads(self):
        for index, marker in enumerate((None, False, 1)):
            records = provider_records()
            report = records[EvidenceSource.CREDIT_BUREAU]
            if marker is None:
                report.pop("simulated")
            else:
                report["simulated"] = marker
            fixture = service_fixture(self.path, records=records)
            result = await fixture.service.assess(request(f"marker-key-{index:04d}"), CUSTOMER)
            self.assertEqual(result.status, AssessmentStatus.REVIEW_REQUIRED)
            self.assertIn("CREDIT_BUREAU_INVALID_RESPONSE", self.codes(result))

    async def test_real_timeout_cancels_provider_coroutine(self):
        policy = changed_model(load_policy(), provider_timeout_seconds=1, provider_max_attempts=1)
        fixture = service_fixture(self.path, policies=(policy,), delay_seconds=2)
        result = await fixture.service.assess(request(), CUSTOMER)
        self.assertEqual(result.status, AssessmentStatus.REVIEW_REQUIRED)
        self.assertTrue(all(p.calls == 1 for p in fixture.providers.values()))
        self.assertIn("ANAF_TIMEOUT", self.codes(result))