"""Read-only SQLite credit-source adapter over a tiny hand-built database."""
import shutil
import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.credit_sources.setup import create_database
from src.core.errors import ToolUnavailable
from src.integrations.credit_sources import CustomerBinding, SqliteCreditSources, load_bindings

CNP = "1900101000011"
MISSING_CNP = "1900101000099"


@pytest.fixture
def tmp_path():
    """Worktree-local temp dir (the system pytest temp root is not writable here)."""
    path = Path(__file__).parent / ".test_tmp_credit" / uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def db(tmp_path):
    path = create_database(tmp_path / "cs.db", empty=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(f"""
            UPDATE report_params SET as_of_date = '2026-10-28' WHERE id = 1;
            INSERT INTO persons (cnp, first_name, last_name, birth_date, persona_tag)
                VALUES ('{CNP}', 'Radu', 'Mihai', '1990-01-01', 'DEMO_RADU_MIHAI');
            INSERT INTO employers (id, name, fiscal_code) VALUES (1, 'Acme', 'RO1'), (2, 'Beta', 'RO2');
            INSERT INTO employments (cnp, employer, start_date, end_date, contract_type) VALUES
                ('{CNP}', 1, '2019-03-01', NULL, 'INDEFINITE'),
                ('{CNP}', 2, '2015-01-01', '2018-12-31', 'INDEFINITE');
            INSERT INTO monthly_salary_declarations VALUES
                ('{CNP}', 1, '2026-08-01', 5000, 3000, 2000),
                ('{CNP}', 1, '2026-09-01', 5000, 3000, 2000),
                ('{CNP}', 2, '2026-09-01', 3500, 2000.5, 1499.5),
                ('{CNP}', 1, '2026-10-01', 9000, 9000, 0);
            INSERT INTO lenders (id, name, lender_type) VALUES (1, 'Bank', 'BANK');
            INSERT INTO credit_products (id, lender, product_type, opened_on, term_months, amount_granted,
                amount_granted_ron, rate_type, status) VALUES
                (1, 1, 'CONSUMER_LOAN', '2025-01-01', 60, 10000, 10000, 'FIXED', 'ACTIVE');
            INSERT INTO product_participants VALUES (1, '{CNP}', 'DEBTOR');
            INSERT INTO payment_history (product, month, amount_owed, instalment_due, amount_paid,
                overdue_amount, overdue_instalments, days_past_due) VALUES
                (1, '2026-09-01', 8000, 200, 200, 0, 0, 0),
                (1, '2026-10-01', 7800, 200, 0, 200, 1, 15),
                (1, '2026-11-01', 7600, 999, 0, 999, 3, 95);
        """)
        conn.commit()
    return path


def sources(db, **extra):
    bindings = {"cust-radu-mihai": CustomerBinding(customer_id="cust-radu-mihai", cnp=CNP, persona_tag="DEMO_RADU_MIHAI")}
    bindings.update(extra)
    return SqliteCreditSources(db, bindings)


def test_monthly_salary_sums_latest_month(db):
    report = sources(db).anaf("cust-radu-mihai")
    assert report.status == "found"
    assert report.net_monthly_income == Decimal("5000.50")
    assert report.income_basis == "monthly_salary"
    assert report.employment_start == date(2019, 3, 1)
    assert report.as_of == date(2026, 10, 28) and not report.self_employed


def test_future_history_ignored(db):
    report = sources(db).bureau("cust-radu-mihai")
    assert report.status == "found" and report.active_products == 1
    assert report.monthly_instalments == Decimal("200.00")
    assert report.current_max_dpd == 15 and report.max_dpd_12m == 15


def test_unbound_customer_not_found(db):
    s = sources(db)
    assert s.anaf("cust-001").status == "not_found"
    assert s.bureau("cust-001").status == "not_found"
    assert s.person("cust-001") is None


def test_bound_cnp_missing_not_found(db):
    s = sources(db, ghost=CustomerBinding(customer_id="ghost", cnp=MISSING_CNP, persona_tag="X"))
    assert s.anaf("ghost").status == "not_found" and s.anaf("ghost").net_monthly_income is None
    assert s.bureau("ghost").status == "not_found"
    assert s.person("ghost") is None


def test_missing_db_raises_tool_unavailable(tmp_path):
    s = SqliteCreditSources(tmp_path / "nope.db", {})
    with pytest.raises(ToolUnavailable):
        s.anaf("cust-radu-mihai")
    assert not (tmp_path / "nope.db").exists()


def test_no_products_found_empty(db):
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("INSERT INTO persons (cnp, first_name, last_name, birth_date) VALUES (?, 'A', 'B', '1980-05-05')",
                     (MISSING_CNP,))
        conn.commit()
    report = sources(db, ab=CustomerBinding(customer_id="ab", cnp=MISSING_CNP, persona_tag="X")).bureau("ab")
    assert report.status == "found" and report.active_products == 0
    assert report.monthly_instalments == Decimal("0.00") and report.score_status == "NONE"


def test_person_full_name_and_birth_date(db):
    person = sources(db).person("cust-radu-mihai")
    assert person.full_name == "Radu Mihai"
    assert person.birth_date == date(1990, 1, 1) and person.as_of == date(2026, 10, 28)


def test_load_bindings(tmp_path):
    path = tmp_path / "b.yaml"
    path.write_text(f"bindings:\n  - customer_id: cust-radu-mihai\n    cnp: '{CNP}'\n    persona_tag: DEMO_RADU_MIHAI\n",
                    encoding="utf-8")
    assert load_bindings(path)["cust-radu-mihai"].cnp == CNP
