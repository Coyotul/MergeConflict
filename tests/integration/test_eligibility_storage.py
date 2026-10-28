import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from src.core.eligibility_errors import IdempotencyConflict, StorageUnavailable
from src.models.eligibility import AuditEvent, EligibilityAssessment, PolicyReference
from src.rules.eligibility.engine import check
from src.models.eligibility import RuleStatus
from src.services.eligibility.policy import load_policy
from src.storage.application_db.eligibility import SqliteAssessmentRepository
from tests.fixtures.eligibility import NOW, changed_model


def assessment_and_audit():
    policy = load_policy()
    result = EligibilityAssessment(
        assessment_id=str(uuid4()), application_id="demo-app-eligible", customer_id="demo-customer",
        status="PRELIMINARY_REQUIREMENTS_SATISFIED", assessed_at=NOW, correlation_id=str(uuid4()),
        policy=PolicyReference(policy_id=policy.policy_id, version=policy.version, sha256=policy.digest(),
                               effective_from=policy.effective_from, effective_to=policy.effective_to),
        checks=(check(policy, "POLICY", RuleStatus.PASS, "TEST", "Synthetic storage fixture."),),
        source_references=policy.sources, assumptions=policy.assumptions,
    )
    audit = AuditEvent(event_id=str(uuid4()), actor_id="test-customer", action="eligibility.assessed",
                       application_id=result.application_id, assessment_id=result.assessment_id,
                       timestamp=NOW, result=result.status.value, correlation_id=result.correlation_id)
    return result, audit


class EligibilityStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="eligibility-storage-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "storage.sqlite3"
        self.repository = SqliteAssessmentRepository(self.path)

    def save(self, result=None, audit=None, actor="test-customer", key="storage-key", request_hash="a" * 64, input_hash="b" * 64):
        if result is None:
            result, audit = assessment_and_audit()
        return self.repository.save_run(actor, key, request_hash, input_hash, result, audit)

    def test_atomic_assessment_audit_and_hashed_idempotency_key(self):
        result = self.save()
        self.assertEqual(self.repository.get_assessment(result.assessment_id), result)
        self.assertEqual(self.repository.get_run("test-customer", "storage-key").assessment, result)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM eligibility_audit").fetchone()[0], 1)
            stored = connection.execute("SELECT key_sha256 FROM eligibility_runs").fetchone()[0]
            self.assertNotEqual(stored, "storage-key")
            self.assertEqual(len(stored), 64)

    def test_key_is_actor_scoped(self):
        first = self.save()
        result, audit = assessment_and_audit()
        audit = changed_model(audit, actor_id="another-actor")
        second = self.save(result, audit, actor="another-actor")
        self.assertNotEqual(first.assessment_id, second.assessment_id)

    def test_replay_and_conflict(self):
        first = self.save()
        result, audit = assessment_and_audit()
        self.assertEqual(self.save(result, audit), first)
        with self.assertRaises(IdempotencyConflict):
            self.save(result, audit, input_hash="c" * 64)

    def test_snapshot_and_audit_survive_restart(self):
        first = self.save()
        restarted = SqliteAssessmentRepository(self.path)
        self.assertEqual(restarted.get_run("test-customer", "storage-key").assessment, first)
        self.assertTrue(restarted.healthcheck())

    def test_assessment_updates_are_blocked(self):
        first = self.save()
        with closing(sqlite3.connect(self.path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE eligibility_assessments SET status = ? WHERE assessment_id = ?",
                                   ("MANUAL_REVIEW_REQUIRED", first.assessment_id))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE eligibility_audit SET timestamp = ?", ("different",))

    def test_audit_insert_failure_rolls_back_entire_operation(self):
        first, audit = assessment_and_audit()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON eligibility_audit BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(StorageUnavailable):
            self.save(first, audit)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM eligibility_assessments").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM eligibility_runs").fetchone()[0], 0)

    def test_audit_mismatch_not_persisted(self):
        first, audit = assessment_and_audit()
        with self.assertRaises(ValueError):
            self.save(first, changed_model(audit, assessment_id="wrong-assessment"))
        self.assertIsNone(self.repository.get_assessment(first.assessment_id))

    def test_corrupt_snapshot_does_not_leak_payload(self):
        first = self.save()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DROP TRIGGER eligibility_assessment_immutable")
            connection.execute("UPDATE eligibility_assessments SET payload = ?", ('{"private":"should not leak"}',))
            connection.commit()
        with self.assertRaises(StorageUnavailable) as exc:
            self.repository.get_assessment(first.assessment_id)
        self.assertNotIn("private", str(exc.exception))

    def test_independent_writers_same_key_produce_one_snapshot(self):
        pairs = [assessment_and_audit(), assessment_and_audit()]

        def write(pair):
            repo = SqliteAssessmentRepository(self.path)
            return repo.save_run("test-customer", "parallel-key", "a" * 64, "b" * 64, *pair)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(write, pairs))
        self.assertEqual(results[0].assessment_id, results[1].assessment_id)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM eligibility_assessments").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM eligibility_audit").fetchone()[0], 1)