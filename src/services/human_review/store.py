"""SQLite store for submitted applications: the single source of truth for review status."""
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from src.services.human_review.models import (
    REVIEWER_TRANSITIONS, HistoryEntry, InfoRequest, InvalidTransition, NotFound,
    ReviewApplication, ReviewDocument, ReviewStatus, StaleVersion,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    reference TEXT NOT NULL UNIQUE,
    customer_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    product_code TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    snapshot TEXT NOT NULL,
    current TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS applications_customer ON applications(customer_id);
CREATE TABLE IF NOT EXISTS application_documents (
    application_id TEXT NOT NULL REFERENCES applications(id),
    document_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    origin TEXT NOT NULL,
    status TEXT NOT NULL,
    filename TEXT,
    extracted_fields TEXT NOT NULL,
    validation TEXT,
    sha256 TEXT,
    uploaded_at TEXT NOT NULL,
    superseded_by TEXT,
    PRIMARY KEY (application_id, document_id)
);
CREATE TABLE IF NOT EXISTS application_history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL REFERENCES applications(id),
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS information_requests (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id),
    doc_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    fulfilled_at TEXT,
    fulfilled_document_id TEXT
);
"""


class ReviewStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5)
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # Autocommit mode plus an explicit BEGIN IMMEDIATE: the write lock is taken before the
        # version/status check, so two reviewers acting on the same version cannot both win.
        conn = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    # ---- writes -----------------------------------------------------------

    def create(
        self, *, idempotency_key: str, customer_id: str, session_id: str, product_code: str,
        snapshot: dict[str, Any], documents: list[ReviewDocument], now: datetime,
    ) -> ReviewApplication:
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT id FROM applications WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing:
                return self._load(conn, existing["id"])
            app_id = f"APP-{secrets.token_hex(4)}"
            reference = f"LN-{now:%Y%m%d}-{secrets.token_hex(2).upper()}"
            conn.execute(
                "INSERT INTO applications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (app_id, reference, customer_id, session_id, product_code, ReviewStatus.PENDING_HUMAN_REVIEW,
                 idempotency_key, json.dumps(snapshot), json.dumps(snapshot), now.isoformat(), now.isoformat()),
            )
            for document in documents:
                self._insert_document(conn, app_id, document)
            self._history(conn, app_id, None, ReviewStatus.PENDING_HUMAN_REVIEW, "customer",
                          "Submitted from the assistant", now)
            return self._load(conn, app_id)

    def transition(
        self, app_id: str, *, to: ReviewStatus, actor: str, reason: str, expected_version: int | None,
        now: datetime, request_doc_type: str | None = None,
    ) -> ReviewApplication:
        with self._connection() as conn:
            row = self._row(conn, app_id)
            current = ReviewStatus(row["status"])
            if expected_version is not None and expected_version != row["version"]:
                raise StaleVersion(f"Application {app_id} changed; reload it.")
            if to not in REVIEWER_TRANSITIONS.get(current, set()):
                raise InvalidTransition(f"Cannot move from {current} to {to}.")
            if to == ReviewStatus.MORE_INFORMATION_REQUIRED:
                if not request_doc_type:
                    raise InvalidTransition("A document type is required to request information.")
                conn.execute(
                    "INSERT INTO information_requests VALUES (?, ?, ?, ?, 'open', ?, NULL, NULL)",
                    (f"REQ-{secrets.token_hex(4)}", app_id, request_doc_type, reason, now.isoformat()),
                )
            self._set_status(conn, app_id, current, to, actor, reason, now)
            return self._load(conn, app_id)

    def fulfil_request(
        self, app_id: str, request_id: str, *, document: ReviewDocument, current: dict[str, Any], now: datetime,
    ) -> ReviewApplication:
        with self._connection() as conn:
            row = self._row(conn, app_id)
            request = conn.execute(
                "SELECT * FROM information_requests WHERE id = ? AND application_id = ?", (request_id, app_id)
            ).fetchone()
            if (request is None or request["status"] != "open"
                    or row["status"] != ReviewStatus.MORE_INFORMATION_REQUIRED):
                raise InvalidTransition("There is no open information request to fulfil.")
            conn.execute(
                "UPDATE application_documents SET superseded_by = ? "
                "WHERE application_id = ? AND doc_type = ? AND superseded_by IS NULL",
                (document.document_id, app_id, document.doc_type),
            )
            self._insert_document(conn, app_id, document)
            conn.execute(
                "UPDATE information_requests SET status = 'fulfilled', fulfilled_at = ?, fulfilled_document_id = ? "
                "WHERE id = ?", (now.isoformat(), document.document_id, request_id),
            )
            conn.execute("UPDATE applications SET current = ? WHERE id = ?", (json.dumps(current), app_id))
            self._set_status(conn, app_id, ReviewStatus.MORE_INFORMATION_REQUIRED,
                             ReviewStatus.PENDING_HUMAN_REVIEW, "system",
                             "The requested document was received and checked", now)
            return self._load(conn, app_id)

    # ---- reads ------------------------------------------------------------

    def get(self, app_id: str) -> ReviewApplication:
        with self._connection() as conn:
            return self._load(conn, app_id)

    def list(self, *, customer_id: str | None = None, status: ReviewStatus | None = None) -> list[ReviewApplication]:
        query, args = "SELECT id FROM applications WHERE 1 = 1", []
        if customer_id is not None:
            query, args = query + " AND customer_id = ?", [*args, customer_id]
        if status is not None:
            query, args = query + " AND status = ?", [*args, str(status)]
        with self._connection() as conn:
            ids = [r["id"] for r in conn.execute(query + " ORDER BY updated_at DESC, id", args)]
            return [self._load(conn, app_id) for app_id in ids]

    # ---- helpers ----------------------------------------------------------

    def _row(self, conn: sqlite3.Connection, app_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        if row is None:
            raise NotFound(app_id)
        return row

    def _set_status(self, conn, app_id, from_status, to_status, actor, reason, now) -> None:
        conn.execute(
            "UPDATE applications SET status = ?, version = version + 1, updated_at = ? WHERE id = ?",
            (str(to_status), now.isoformat(), app_id),
        )
        self._history(conn, app_id, from_status, to_status, actor, reason, now)

    @staticmethod
    def _history(conn, app_id, from_status, to_status, actor, reason, now) -> None:
        conn.execute(
            "INSERT INTO application_history (application_id, from_status, to_status, actor, reason, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (app_id, str(from_status) if from_status else None, str(to_status), actor, reason, now.isoformat()),
        )

    @staticmethod
    def _insert_document(conn, app_id: str, d: ReviewDocument) -> None:
        conn.execute(
            "INSERT INTO application_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (app_id, d.document_id, d.doc_type, d.origin, d.status, d.filename, json.dumps(d.extracted_fields),
             json.dumps(d.validation) if d.validation is not None else None, d.sha256,
             d.uploaded_at.isoformat(), d.superseded_by),
        )

    def _load(self, conn: sqlite3.Connection, app_id: str) -> ReviewApplication:
        row = self._row(conn, app_id)
        documents = [
            ReviewDocument(
                document_id=d["document_id"], doc_type=d["doc_type"], origin=d["origin"], status=d["status"],
                filename=d["filename"], extracted_fields=json.loads(d["extracted_fields"]),
                validation=json.loads(d["validation"]) if d["validation"] else None, sha256=d["sha256"],
                uploaded_at=d["uploaded_at"], superseded_by=d["superseded_by"],
            )
            for d in conn.execute(
                "SELECT * FROM application_documents WHERE application_id = ? ORDER BY uploaded_at", (app_id,)
            )
        ]
        history = [
            HistoryEntry(from_status=h["from_status"], to_status=h["to_status"], actor=h["actor"],
                         reason=h["reason"], at=h["at"])
            for h in conn.execute("SELECT * FROM application_history WHERE application_id = ? ORDER BY seq", (app_id,))
        ]
        requests = [
            InfoRequest(**dict(r)) for r in conn.execute(
                "SELECT id, doc_type, reason, status, created_at, fulfilled_at, fulfilled_document_id "
                "FROM information_requests WHERE application_id = ? ORDER BY created_at, id", (app_id,)
            )
        ]
        return ReviewApplication(
            id=row["id"], reference=row["reference"], customer_id=row["customer_id"], session_id=row["session_id"],
            product_code=row["product_code"], status=row["status"], version=row["version"],
            snapshot=json.loads(row["snapshot"]), current=json.loads(row["current"]),
            documents=documents, history=history, requests=requests,
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
