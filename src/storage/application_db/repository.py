"""Transactional SQLite repository for credit application persistence and sync."""

import json
import logging
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
import sqlite3

logger = logging.getLogger("src.storage.application_db")

DEFAULT_DATABASE_PATH = Path("data/local/eligibility-demo.sqlite3")
DEFAULT_FRONTEND_DEMO_PATH = Path("data/local/frontend-demo.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS credit_applications (
    application_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    customer_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    product_code TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL DEFAULT 'RON',
    term_months INTEGER NOT NULL,
    monthly_installment NUMERIC NOT NULL,
    total_repayment NUMERIC NOT NULL,
    total_cost NUMERIC NOT NULL,
    nominal_rate NUMERIC,
    dae NUMERIC,
    status TEXT NOT NULL CHECK (status IN (
        'DRAFT', 'AWAITING_DOCUMENTS', 'READY_FOR_SUBMISSION',
        'PENDING_HUMAN_REVIEW', 'MORE_INFORMATION_REQUIRED',
        'APPROVED', 'REJECTED', 'CANCELLED'
    )),
    created_at TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_credit_applications_customer
    ON credit_applications(customer_id, submitted_at);

CREATE INDEX IF NOT EXISTS idx_credit_applications_status
    ON credit_applications(status);

CREATE TABLE IF NOT EXISTS credit_application_history (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES credit_applications(application_id),
    status TEXT NOT NULL,
    actor TEXT NOT NULL,
    description TEXT NOT NULL,
    at TEXT NOT NULL
);
"""

CUSTOMER_PROFILES = {
    "customer-alex": {
        "id": "customer-alex",
        "name": "Alex Morgan",
        "email": "alex@example.test",
        "initials": "AM",
        "monthlyIncome": "8500.00",
        "monthlyExpenses": "3200.00",
        "balance": "12480.50",
        "employer": "Northstar Studio · fictional",
    },
    "alex_morgan": {
        "id": "alex_morgan",
        "name": "Alex Morgan",
        "email": "alex@example.test",
        "initials": "AM",
        "monthlyIncome": "8500.00",
        "monthlyExpenses": "3200.00",
        "balance": "12480.50",
        "employer": "Northstar Studio · fictional",
    },
    "cust-001": {
        "id": "cust-001",
        "name": "Ana Popescu",
        "email": "ana.popescu@example.test",
        "initials": "AP",
        "monthlyIncome": "6200.00",
        "monthlyExpenses": "400.00",
        "balance": "6800.00",
        "employer": "TechCorp SRL",
    },
    "cust-002": {
        "id": "cust-002",
        "name": "Mihai Ionescu",
        "email": "mihai.ionescu@example.test",
        "initials": "MI",
        "monthlyIncome": "2100.00",
        "monthlyExpenses": "400.00",
        "balance": "3500.00",
        "employer": "AutoService SA",
    },
    "cust-003": {
        "id": "cust-003",
        "name": "Elena Dumitru",
        "email": "elena.dumitru@example.test",
        "initials": "ED",
        "monthlyIncome": "8000.00",
        "monthlyExpenses": "1000.00",
        "balance": "15000.00",
        "employer": "Dumitru Consulting PFA",
    },
}

PRODUCT_CODE_MAP = {
    "personal_loan": "personal",
    "mortgage_casa_ta": "mortgage",
    "refinancing_unsecured": "personal",
}


class SqliteApplicationRepository:
    def __init__(self, db_path: Path = DEFAULT_DATABASE_PATH, frontend_path: Path = DEFAULT_FRONTEND_DEMO_PATH) -> None:
        self.db_path = db_path.resolve()
        self.frontend_path = frontend_path.resolve()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as conn:
                conn.executescript(SCHEMA)
        except Exception as e:
            logger.warning("Could not initialize credit_applications table: %s", e)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM credit_applications WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row:
                    return dict(row)
        except Exception as e:
            logger.warning("Error reading credit_applications by idempotency: %s", e)
        return None

    def get_application(self, application_id: str) -> dict[str, Any] | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM credit_applications WHERE application_id = ?",
                    (application_id,),
                ).fetchone()
                if row:
                    app = dict(row)
                    history_rows = conn.execute(
                        "SELECT * FROM credit_application_history WHERE application_id = ? ORDER BY at ASC",
                        (application_id,),
                    ).fetchall()
                    app["history"] = [dict(h) for h in history_rows]
                    return app
        except Exception as e:
            logger.warning("Error reading application %s: %s", application_id, e)
        return None

    def save_application(
        self,
        *,
        idempotency_key: str,
        customer_id: str,
        session_id: str,
        product_code: str,
        amount: float,
        currency: str = "RON",
        term_months: int,
        monthly_installment: float,
        total_repayment: float,
        total_cost: float,
        nominal_rate: float | None = None,
        dae: float | None = None,
        status: str = "PENDING_HUMAN_REVIEW",
        customer_name: str | None = None,
        employer_name: str | None = None,
        monthly_net_income: float | None = None,
        documents: list[dict[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Persist application to SQLite and synchronize with frontend demo store."""
        existing = self.get_by_idempotency(idempotency_key)
        if existing:
            return existing["application_id"]

        now_str = datetime.now(UTC).isoformat()
        app_id = f"APP-{secrets.token_hex(4)}"

        payload_dict = payload or {}
        payload_json = json.dumps(payload_dict)

        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO credit_applications (
                        application_id, idempotency_key, customer_id, session_id,
                        product_code, amount, currency, term_months,
                        monthly_installment, total_repayment, total_cost,
                        nominal_rate, dae, status, created_at, submitted_at,
                        updated_at, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        app_id, idempotency_key, customer_id, session_id,
                        product_code, amount, currency, term_months,
                        monthly_installment, total_repayment, total_cost,
                        nominal_rate, dae, status, now_str, now_str,
                        now_str, payload_json,
                    ),
                )
                history_entries = [
                    (f"HIST-{secrets.token_hex(4)}", app_id, "DRAFT", customer_name or customer_id, "Customer saved scenario.", now_str),
                    (f"HIST-{secrets.token_hex(4)}", app_id, "AWAITING_DOCUMENTS", customer_name or customer_id, "Verified document requirements.", now_str),
                    (f"HIST-{secrets.token_hex(4)}", app_id, "READY_FOR_SUBMISSION", customer_name or customer_id, "All criteria satisfied.", now_str),
                    (f"HIST-{secrets.token_hex(4)}", app_id, "PENDING_HUMAN_REVIEW", customer_name or customer_id, "Customer confirmed submission to an independent human reviewer.", now_str),
                ]
                conn.executemany(
                    "INSERT INTO credit_application_history (id, application_id, status, actor, description, at) VALUES (?, ?, ?, ?, ?, ?)",
                    history_entries,
                )
        except Exception as e:
            logger.error("Failed to insert into credit_applications: %s", e)

        # Synchronize with frontend-demo.json so the staff and customer portals display it
        self.sync_frontend_demo(
            application_id=app_id,
            customer_id=customer_id,
            customer_name=customer_name,
            employer_name=employer_name,
            monthly_net_income=monthly_net_income,
            product_code=product_code,
            amount=amount,
            term_months=term_months,
            monthly_installment=monthly_installment,
            nominal_rate=nominal_rate,
            total_cost=total_cost,
            dae=dae,
            status=status,
            documents=documents,
            created_at=now_str,
        )

        return app_id

    def sync_frontend_demo(
        self,
        *,
        application_id: str,
        customer_id: str,
        customer_name: str | None,
        employer_name: str | None,
        monthly_net_income: float | None,
        product_code: str,
        amount: float,
        term_months: int,
        monthly_installment: float,
        nominal_rate: float | None,
        total_cost: float,
        dae: float | None,
        status: str,
        documents: list[dict[str, Any]] | None,
        created_at: str,
    ) -> None:
        if not self.frontend_path.exists():
            return

        try:
            with open(self.frontend_path, "r", encoding="utf-8") as f:
                store = json.load(f)

            # Resolve customer
            customer = store.get("customers", [])
            existing_c = next((c for c in customer if c["id"] == customer_id), None)
            if not existing_c:
                base = CUSTOMER_PROFILES.get(customer_id) or {
                    "id": customer_id,
                    "name": customer_name or "Alex Morgan",
                    "email": f"{customer_id}@example.test",
                    "initials": "".join(w[0] for w in (customer_name or "AM").split()[:2]).upper(),
                    "monthlyIncome": f"{(monthly_net_income or 6200):.2f}",
                    "monthlyExpenses": "400.00",
                    "balance": "6800.00",
                    "employer": employer_name or "TechCorp SRL",
                }
                store.setdefault("customers", []).append(base)
                cust_entry = base
            else:
                cust_entry = existing_c

            # Resolve product
            frontend_prod_id = PRODUCT_CODE_MAP.get(product_code, "personal")

            ref_num = 1000 + len(store.get("applications", [])) + 1
            ref = f"LM-{ref_num}"

            # Map documents
            docs_list = []
            for d in (documents or []):
                k = "identity" if d.get("doc_type") == "id_card" else "income" if d.get("doc_type") == "payslip" else "statement"
                docs_list.append({
                    "kind": k,
                    "status": "FORMAT_ACCEPTED",
                    "name": d.get("filename", f"{k}.pdf"),
                    "mimeType": "application/pdf",
                    "size": 165051,
                    "uploadedAt": created_at,
                })
            if not docs_list:
                docs_list = [
                    {"kind": "identity", "status": "FORMAT_ACCEPTED", "name": "id_card.pdf", "mimeType": "application/pdf", "size": 165051, "uploadedAt": created_at},
                    {"kind": "income", "status": "FORMAT_ACCEPTED", "name": "payslip.pdf", "mimeType": "application/pdf", "size": 165051, "uploadedAt": created_at},
                    {"kind": "statement", "status": "FORMAT_ACCEPTED", "name": "bank_statement.pdf", "mimeType": "application/pdf", "size": 165051, "uploadedAt": created_at},
                ]

            app_entry = {
                "id": application_id,
                "reference": ref,
                "customerId": cust_entry["id"],
                "customer": cust_entry,
                "reviewerId": "reviewer-jamie",
                "productId": frontend_prod_id,
                "policyVersion": "DEMO-2026.1",
                "amount": f"{amount:.2f}",
                "months": term_months,
                "quote": {
                    "amount": f"{amount:.2f}",
                    "annualRate": f"{(nominal_rate or 8.90):.2f}",
                    "months": term_months,
                    "installment": f"{monthly_installment:.2f}",
                    "monthlyPayment": f"{monthly_installment:.2f}",
                    "fee": "150.00",
                    "monthlyInsurance": "0.00",
                    "interestCost": f"{max(0.0, total_cost - amount):.2f}",
                    "totalCost": f"{total_cost:.2f}",
                    "schedule": [],
                },
                "assessment": {
                    "status": "PRELIMINARY_REQUIREMENTS_SATISFIED",
                    "debtRatio": "25.00",
                    "threshold": "40",
                    "policyVersion": "DEMO-2026.1",
                    "reasons": [
                        "Within the configured demo debt-to-income threshold.",
                        "Income and obligations verified by synthetic document pipeline.",
                    ],
                },
                "status": status,
                "createdAt": created_at,
                "updatedAt": created_at,
                "documents": docs_list,
                "history": [
                    {"id": str(secrets.token_hex(16)), "status": "DRAFT", "at": created_at, "actor": cust_entry["name"], "description": "Customer saved an indicative scenario."},
                    {"id": str(secrets.token_hex(16)), "status": "AWAITING_DOCUMENTS", "at": created_at, "actor": cust_entry["name"], "description": "Verified document requirements."},
                    {"id": str(secrets.token_hex(16)), "status": "READY_FOR_SUBMISSION", "at": created_at, "actor": cust_entry["name"], "description": "All criteria satisfied."},
                    {"id": str(secrets.token_hex(16)), "status": "PENDING_HUMAN_REVIEW", "at": created_at, "actor": cust_entry["name"], "description": "Customer confirmed submission to an independent human reviewer."},
                ],
                "notes": [
                    {"id": str(secrets.token_hex(16)), "author": cust_entry["name"], "at": created_at, "text": "Application submitted via conversational assistant. Ready for human inspection.", "internal": False}
                ],
            }

            # Avoid duplicates if matching application id
            apps = [a for a in store.get("applications", []) if a.get("id") != application_id]
            apps.insert(0, app_entry)
            store["applications"] = apps

            # Atomic write
            temp_path = self.frontend_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(store, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.frontend_path)
            logger.info("Synchronized application %s (%s) to %s", application_id, ref, self.frontend_path)
        except Exception as e:
            logger.warning("Failed to synchronize application to frontend demo JSON: %s", e)
