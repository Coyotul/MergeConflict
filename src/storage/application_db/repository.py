"""SQLite local adapter with atomic workflow/audit/idempotency transactions.

SQL indexes own access relationships. JSON payloads retain typed aggregate models.
This is a synthetic, single-host adapter, not the planned Supabase database.
"""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TypeVar

from src.core.catalogue import FixtureConfiguration
from src.core.errors import DomainError
from src.models.banking import (
    Actor,
    AuditEvent,
    ChatMessage,
    Consent,
    Customer,
    Loan,
    LoanApplication,
    Notification,
    Role,
    SupportRequest,
)
from src.models.common import WireModel


T = TypeVar("T", bound=WireModel)


def encode(value: WireModel) -> str:
    return value.model_dump_json(by_alias=True, exclude_none=True)


class UnitOfWork:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def customer(self, customer_id: str) -> Customer:
        row = self.connection.execute(
            "SELECT payload FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "Synthetic customer not found.", 404)
        return Customer.model_validate_json(row[0])

    def loans(self, customer_id: str) -> list[Loan]:
        return [Loan.model_validate_json(row[0]) for row in self.connection.execute(
            "SELECT payload FROM loans WHERE customer_id = ? ORDER BY rowid", (customer_id,)
        )]

    def loan(self, loan_id: str, customer_id: str) -> Loan:
        row = self.connection.execute(
            "SELECT payload FROM loans WHERE id = ? AND customer_id = ?", (loan_id, customer_id)
        ).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "Synthetic loan not found.", 404)
        return Loan.model_validate_json(row[0])

    def application(self, application_id: str, actor: Actor) -> LoanApplication:
        column = "customer_id" if actor.role == Role.CUSTOMER else "reviewer_id"
        row = self.connection.execute(
            f"SELECT payload FROM applications WHERE id = ? AND {column} = ?",
            (application_id, actor.id),
        ).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "Application not found.", 404)
        return LoanApplication.model_validate_json(row[0])

    def applications(self, actor: Actor) -> list[LoanApplication]:
        column = "customer_id" if actor.role == Role.CUSTOMER else "reviewer_id"
        return [LoanApplication.model_validate_json(row[0]) for row in self.connection.execute(
            f"SELECT payload FROM applications WHERE {column} = ? ORDER BY rowid DESC", (actor.id,)
        )]

    def save_application(self, application: LoanApplication) -> None:
        row = self.connection.execute("SELECT payload FROM applications WHERE id = ?", (application.id,)).fetchone()
        if row is not None:
            previous = LoanApplication.model_validate_json(row[0])
            if application.revision != previous.revision:
                raise DomainError("APPLICATION_CHANGED", "Application changed; reload before retrying.", 409)
            application.revision += 1
        self.connection.execute(
            """INSERT INTO applications(id, customer_id, reviewer_id, payload) VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET payload = excluded.payload""",
            (application.id, application.customer_id, application.reviewer_id, encode(application)),
        )

    def application_for_eligibility(self, application_id: str) -> LoanApplication | None:
        """Internal trusted port; the eligibility service independently checks principal access."""
        row = self.connection.execute("SELECT payload FROM applications WHERE id = ?", (application_id,)).fetchone()
        return LoanApplication.model_validate_json(row[0]) if row is not None else None

    def next_reference(self) -> str:
        count = self.connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        return f"LM-{1001 + count}"

    def consent(self, customer_id: str) -> Consent:
        row = self.connection.execute(
            "SELECT payload FROM consents WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "Customer consent record not found.", 404)
        return Consent.model_validate_json(row[0])

    def save_consent(self, customer_id: str, consent: Consent) -> None:
        self.connection.execute(
            """INSERT INTO consents(customer_id, payload) VALUES (?, ?)
               ON CONFLICT(customer_id) DO UPDATE SET payload = excluded.payload""",
            (customer_id, encode(consent)),
        )

    def notifications(self, customer_id: str) -> list[Notification]:
        return [Notification.model_validate_json(row[0]) for row in self.connection.execute(
            "SELECT payload FROM notifications WHERE customer_id = ? ORDER BY rowid DESC", (customer_id,)
        )]

    def save_notification(self, notification: Notification) -> None:
        self.connection.execute(
            """INSERT INTO notifications(id, customer_id, application_id, payload) VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET payload = excluded.payload""",
            (notification.id, notification.customer_id, notification.application_id, encode(notification)),
        )

    def add_audit(self, event: AuditEvent) -> None:
        self.connection.execute(
            "INSERT INTO audit_events(id, actor_id, object_id, action, payload) VALUES (?, ?, ?, ?, ?)",
            (event.id, event.actor_id, event.object_id, event.action, encode(event)),
        )

    def audit(self, actor: Actor) -> list[AuditEvent]:
        column = "customer_id" if actor.role == Role.CUSTOMER else "reviewer_id"
        private_filter = "AND action != 'INTERNAL_NOTE_ADDED'" if actor.role == Role.CUSTOMER else ""
        rows = self.connection.execute(
            f"""SELECT payload FROM audit_events
                WHERE (actor_id = ? OR object_id IN
                    (SELECT id FROM applications WHERE {column} = ?))
                {private_filter} ORDER BY rowid DESC""",
            (actor.id, actor.id),
        )
        events = [AuditEvent.model_validate_json(row[0]) for row in rows]
        has_eligibility = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'eligibility_audit'"
        ).fetchone()
        if has_eligibility:
            from src.models.eligibility import AuditEvent as EligibilityAuditEvent

            for row in self.connection.execute(
                f"SELECT payload FROM eligibility_audit WHERE application_id IN (SELECT id FROM applications WHERE {column} = ?)",
                (actor.id,),
            ):
                event = EligibilityAuditEvent.model_validate_json(row[0])
                if event.action == "eligibility.assessed":
                    events.append(AuditEvent(
                        id=event.event_id, actor_id=event.actor_id, actor=event.actor_id, action="PRELIMINARY_ELIGIBILITY_CHECKED",
                        object_id=event.application_id, at=event.timestamp, result=event.result, correlation_id=event.correlation_id,
                    ))
        return sorted(events, key=lambda event: event.at, reverse=True)

    def messages(self, customer_id: str) -> list[ChatMessage]:
        return [ChatMessage.model_validate_json(row[0]) for row in self.connection.execute(
            "SELECT payload FROM conversation_messages WHERE customer_id = ? ORDER BY rowid", (customer_id,)
        )]

    def add_message(self, customer_id: str, message: ChatMessage) -> None:
        self.connection.execute(
            "INSERT INTO conversation_messages(id, customer_id, payload) VALUES (?, ?, ?)",
            (message.id, customer_id, encode(message)),
        )

    def clear_messages(self, customer_id: str) -> None:
        self.connection.execute("DELETE FROM conversation_messages WHERE customer_id = ?", (customer_id,))

    def add_support_request(self, request: SupportRequest) -> None:
        self.connection.execute(
            "INSERT INTO support_requests(id, customer_id, application_id, payload) VALUES (?, ?, ?, ?)",
            (request.id, request.customer_id, request.application_id, encode(request)),
        )

    def idempotent(
        self,
        actor: Actor,
        key: str,
        operation: str,
        payload: WireModel,
        result_type: type[T],
        action: Callable[[], T],
    ) -> T:
        canonical = json.dumps(
            {"operation": operation, "payload": payload.model_dump(
                mode="json", by_alias=True, exclude={"idempotency_key"}, exclude_none=True
            )},
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        )
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        existing = self.connection.execute(
            "SELECT fingerprint, response FROM idempotency_records WHERE actor_id = ? AND key = ?",
            (actor.id, key),
        ).fetchone()
        if existing is not None:
            if existing[0] != fingerprint:
                raise DomainError(
                    "IDEMPOTENCY_CONFLICT", "This request key was already used with different inputs.", 409
                )
            return result_type.model_validate_json(existing[1])
        result = action()
        self.connection.execute(
            "INSERT INTO idempotency_records(actor_id, key, fingerprint, response) VALUES (?, ?, ?, ?)",
            (actor.id, key, fingerprint, encode(result)),
        )
        return result


class Repository:
    def __init__(self, path: Path):
        self.path = path.resolve()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def read(self) -> Iterator[UnitOfWork]:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            yield UnitOfWork(connection)
        finally:
            connection.rollback()
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[UnitOfWork]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield UnitOfWork(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self, fixtures: FixtureConfiguration) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise ValueError("Unsupported backend database version; restore or migrate explicitly.")
            if version == 0:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if tables:
                    raise ValueError("Unversioned database will not be overwritten.")
                migration = (Path(__file__).parent / "migrations/001_demo.sql").read_text(encoding="utf-8")
                connection.executescript(f"BEGIN IMMEDIATE;\n{migration}\nPRAGMA user_version = 1;\nCOMMIT;")
            connection.execute("PRAGMA journal_mode = WAL")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Backend database integrity check failed.")
        finally:
            connection.close()
        with self.transaction() as unit:
            seeded = unit.connection.execute("SELECT value FROM metadata WHERE key = 'seeded'").fetchone()
            if seeded is None:
                if unit.connection.execute("SELECT COUNT(*) FROM actors").fetchone()[0]:
                    raise ValueError("Existing backend identities have no seed marker; restore explicitly.")
                for account in fixtures.accounts:
                    unit.connection.execute(
                        "INSERT INTO actors(id, payload) VALUES (?, ?)", (account.actor.id, encode(account.actor))
                    )
                for customer in fixtures.customers:
                    unit.connection.execute(
                        "INSERT INTO customers(id, payload) VALUES (?, ?)", (customer.id, encode(customer))
                    )
                    unit.save_consent(customer.id, Consent())
                for loan in fixtures.loans:
                    unit.connection.execute(
                        "INSERT INTO loans(id, customer_id, payload) VALUES (?, ?, ?)",
                        (loan.id, loan.customer_id, encode(loan)),
                    )
                unit.connection.execute("INSERT INTO metadata(key, value) VALUES ('seeded', '1')")
            elif seeded != ("1",):
                raise ValueError("Unsupported synthetic database fixture version.")
            self._validate_records(unit)

    @staticmethod
    def _validate_records(unit: UnitOfWork) -> None:
        models = {
            "actors": Actor, "customers": Customer, "loans": Loan, "applications": LoanApplication,
            "consents": Consent, "notifications": Notification, "audit_events": AuditEvent,
            "conversation_messages": ChatMessage, "support_requests": SupportRequest,
        }
        for table, model in models.items():
            for row in unit.connection.execute(f"SELECT id, payload FROM {table}" if table != "consents" else "SELECT customer_id, payload FROM consents"):
                item = model.model_validate_json(row[1])
                if table != "consents" and item.id != row[0]:
                    raise ValueError("Stored record identifiers are inconsistent.")
        for row in unit.connection.execute("SELECT customer_id, reviewer_id, payload FROM applications"):
            application = LoanApplication.model_validate_json(row[2])
            if application.customer_id != row[0] or application.reviewer_id != row[1] or application.customer.id != row[0]:
                raise ValueError("Application ownership or reviewer assignment is inconsistent.")
        for table, model in (("loans", Loan), ("notifications", Notification), ("support_requests", SupportRequest)):
            for row in unit.connection.execute(f"SELECT customer_id, payload FROM {table}"):
                if model.model_validate_json(row[1]).customer_id != row[0]:
                    raise ValueError("Stored customer relationship is inconsistent.")
        if unit.connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Backend database relationships are inconsistent.")

    def available(self) -> bool:
        if not self.path.is_file():
            return False
        try:
            with self.read() as unit:
                return unit.connection.execute(
                    "SELECT value FROM metadata WHERE key = 'seeded'"
                ).fetchone() == ("1",)
        except (sqlite3.Error, OSError):
            return False