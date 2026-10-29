"""Tests for credit application persistence in SQLite and synchronization with frontend demo store."""

import json
from pathlib import Path
import pytest

from src.storage.application_db.repository import SqliteApplicationRepository


def test_sqlite_repository_save_and_retrieve(tmp_path):
    db_file = tmp_path / "test-eligibility.sqlite3"
    frontend_file = tmp_path / "test-frontend.json"

    # Seed minimal frontend file
    frontend_file.write_text(
        json.dumps({
            "version": 1,
            "customers": [],
            "applications": [],
            "products": [],
            "loans": [],
            "messages": {},
            "notifications": [],
            "audit": [],
            "consents": {},
            "idempotency": [],
        }),
        encoding="utf-8",
    )

    repo = SqliteApplicationRepository(db_path=db_file, frontend_path=frontend_file)

    app_id = repo.save_application(
        idempotency_key="idemp-key-100",
        customer_id="customer-alex",
        session_id="session-xyz",
        product_code="personal_loan",
        amount=30000.0,
        term_months=36,
        monthly_installment=952.60,
        total_repayment=34293.60,
        total_cost=4293.60,
        nominal_rate=8.90,
        dae=9.58,
        status="PENDING_HUMAN_REVIEW",
        customer_name="Alex Morgan",
        employer_name="Northstar Studio",
        monthly_net_income=8500.0,
        documents=[
            {"doc_type": "id_card", "filename": "buletin.pdf", "document_id": "doc-1"},
            {"doc_type": "payslip", "filename": "adeverinta.pdf", "document_id": "doc-2"},
            {"doc_type": "bank_statement", "filename": "extras.pdf", "document_id": "doc-3"},
        ],
    )

    assert app_id.startswith("APP-")

    # Verify retrieval from SQLite
    saved = repo.get_application(app_id)
    assert saved is not None
    assert saved["customer_id"] == "customer-alex"
    assert saved["status"] == "PENDING_HUMAN_REVIEW"
    assert float(saved["amount"]) == 30000.0
    assert float(saved["monthly_installment"]) == 952.60
    assert len(saved["history"]) == 4
    assert saved["history"][-1]["status"] == "PENDING_HUMAN_REVIEW"

    # Verify idempotency
    same_id = repo.save_application(
        idempotency_key="idemp-key-100",
        customer_id="customer-alex",
        session_id="session-xyz",
        product_code="personal_loan",
        amount=30000.0,
        term_months=36,
        monthly_installment=952.60,
        total_repayment=34293.60,
        total_cost=4293.60,
    )
    assert same_id == app_id

    # Verify sync to frontend demo file
    frontend_data = json.loads(frontend_file.read_text(encoding="utf-8"))
    assert len(frontend_data["applications"]) == 1
    ui_app = frontend_data["applications"][0]
    assert ui_app["id"] == app_id
    assert ui_app["status"] == "PENDING_HUMAN_REVIEW"
    assert ui_app["customer"]["name"] == "Alex Morgan"
    assert ui_app["amount"] == "30000.00"
    assert ui_app["months"] == 36
    assert ui_app["quote"]["installment"] == "952.60"
    assert len(ui_app["documents"]) == 3
