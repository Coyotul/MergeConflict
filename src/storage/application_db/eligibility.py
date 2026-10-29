"""Transactional, local-only synthetic assessment/audit persistence using SQLite."""

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from src.core.eligibility_errors import IdempotencyConflict, StorageUnavailable
from src.models.eligibility import AuditEvent, EligibilityAssessment
from src.services.eligibility.interfaces import StoredAssessment


MIGRATION_PATH = Path(__file__).resolve().parent / "migrations" / "0001_eligibility_demo.sql"


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class SqliteAssessmentRepository:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection:
                connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
        except (OSError, sqlite3.Error) as exc:
            raise StorageUnavailable() from exc

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        except (sqlite3.Error, OSError, ValidationError) as exc:
            raise StorageUnavailable() from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _get_run(connection: sqlite3.Connection, actor_id: str, key: str) -> StoredAssessment | None:
        row = connection.execute(
            "SELECT r.request_fingerprint, r.input_fingerprint, a.payload "
            "FROM eligibility_runs r JOIN eligibility_assessments a "
            "ON a.assessment_id = r.assessment_id WHERE r.actor_id = ? AND r.key_sha256 = ?",
            (actor_id, _key_hash(key)),
        ).fetchone()
        if row is None:
            return None
        return StoredAssessment(
            row["request_fingerprint"], row["input_fingerprint"],
            EligibilityAssessment.model_validate_json(row["payload"]),
        )

    def get_run(self, actor_id: str, key: str) -> StoredAssessment | None:
        with self._connection() as connection:
            return self._get_run(connection, actor_id, key)

    def get_assessment(self, assessment_id: str) -> EligibilityAssessment | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM eligibility_assessments WHERE assessment_id = ?",
                (assessment_id,),
            ).fetchone()
            return EligibilityAssessment.model_validate_json(row["payload"]) if row else None

    def save_run(
        self, actor_id: str, key: str, request_fingerprint: str,
        input_fingerprint: str, assessment: EligibilityAssessment, audit: AuditEvent,
    ) -> EligibilityAssessment:
        assessment = EligibilityAssessment.model_validate(assessment)
        audit = AuditEvent.model_validate(audit)
        if (
            audit.assessment_id != assessment.assessment_id
            or audit.application_id != assessment.application_id
            or audit.actor_id != actor_id or audit.action != "eligibility.assessed"
            or audit.result != assessment.status.value
            or audit.correlation_id != assessment.correlation_id
        ):
            raise ValueError("An assessment and its audit event must describe the same operation.")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._get_run(connection, actor_id, key)
            if existing is not None:
                if (
                    existing.request_fingerprint != request_fingerprint
                    or existing.input_fingerprint != input_fingerprint
                ):
                    raise IdempotencyConflict()
                return existing.assessment
            connection.execute(
                "INSERT INTO eligibility_assessments VALUES (?, ?, ?, ?, ?, ?)",
                (assessment.assessment_id, assessment.application_id, assessment.customer_id,
                 assessment.assessed_at.isoformat(), assessment.status.value, assessment.model_dump_json()),
            )
            connection.execute(
                "INSERT INTO eligibility_runs VALUES (?, ?, ?, ?, ?)",
                (actor_id, _key_hash(key), request_fingerprint, input_fingerprint, assessment.assessment_id),
            )
            self._insert_audit(connection, audit)
            return assessment

    @staticmethod
    def _insert_audit(connection: sqlite3.Connection, event: AuditEvent) -> None:
        connection.execute(
            "INSERT INTO eligibility_audit VALUES (?, ?, ?, ?, ?)",
            (event.event_id, event.assessment_id, event.application_id,
             event.timestamp.isoformat(), event.model_dump_json()),
        )

    def append_audit(self, event: AuditEvent) -> None:
        event = AuditEvent.model_validate(event)
        with self._connection() as connection:
            self._insert_audit(connection, event)

    def healthcheck(self) -> bool:
        try:
            with self._connection() as connection:
                for query in (
                    "SELECT count(*) FROM eligibility_assessments",
                    "SELECT count(*) FROM eligibility_runs",
                    "SELECT count(*) FROM eligibility_audit",
                ):
                    connection.execute(query).fetchone()
            return True
        except StorageUnavailable:
            return False