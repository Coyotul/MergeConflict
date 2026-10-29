"""Read-only SQLite adapter answering simulated ANAF, bureau and person lookups.

Customer IDs map to CNPs only through trusted bindings. All time windows are
relative to `report_params.as_of_date`, never the wall clock. Money is converted
from SQLite REAL to Decimal quantized to 0.01 at this boundary.
"""
import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.core.errors import ToolUnavailable
from src.integrations.credit_sources.models import AnafReport, BureauReport, CustomerBinding, PersonRecord
from src.rules.eligibility.calendar import add_months

CENT = Decimal("0.01")
DEBTOR_PRODUCTS = """SELECT p.id, p.status FROM credit_products p
    JOIN product_participants pp ON pp.product = p.id
    WHERE pp.cnp = ? AND pp.role IN ('DEBTOR', 'CODEBTOR') AND p.opened_on <= ?"""


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT)


class SqliteCreditSources:
    """Mock ANAF + Biroul de Credit over the credit-source dataset (opened `mode=ro`)."""

    def __init__(self, db_path: Path, bindings: dict[str, CustomerBinding]):
        self.db_path = Path(db_path)
        self.bindings = bindings

    def _query(self, customer_id: str, fn):
        if not self.db_path.is_file():
            raise ToolUnavailable("credit-source database is not available")
        try:
            with closing(sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
                as_of = date.fromisoformat(conn.execute("SELECT as_of_date FROM report_params WHERE id = 1").fetchone()[0])
                binding = self.bindings.get(customer_id)
                person = binding and conn.execute(
                    "SELECT first_name, last_name, birth_date FROM persons WHERE cnp = ?", (binding.cnp,)).fetchone()
                return fn(conn, binding.cnp if person else None, person, as_of)
        except (sqlite3.Error, TypeError, ValueError) as error:
            raise ToolUnavailable("credit-source database query failed") from error

    def person(self, customer_id: str) -> PersonRecord | None:
        def run(conn, cnp, row, as_of):
            if cnp is None:
                return None
            return PersonRecord(customer_id=customer_id, full_name=f"{row[0]} {row[1]}",
                                birth_date=date.fromisoformat(row[2]), as_of=as_of)
        return self._query(customer_id, run)

    def anaf(self, customer_id: str) -> AnafReport:
        return self._query(customer_id, self._anaf)

    def bureau(self, customer_id: str) -> BureauReport:
        return self._query(customer_id, self._bureau)

    @staticmethod
    def _anaf(conn, cnp, _row, as_of) -> AnafReport:
        if cnp is None:
            return AnafReport(status="not_found", as_of=as_of)
        iso = as_of.isoformat()
        income, basis = None, None
        month = conn.execute("SELECT max(month) FROM monthly_salary_declarations WHERE cnp = ? AND month < ?",
                             (cnp, as_of.replace(day=1).isoformat())).fetchone()[0]
        if month:
            total = conn.execute("SELECT sum(net_ron) FROM monthly_salary_declarations WHERE cnp = ? AND month = ?",
                                 (cnp, month)).fetchone()[0]
            income, basis = _money(total), "monthly_salary"
        year = conn.execute("SELECT max(fiscal_year) FROM income_records WHERE cnp = ? AND fiscal_year BETWEEN ? AND ?",
                            (cnp, as_of.year - 3, as_of.year)).fetchone()[0]
        by_kind = dict(conn.execute(
            "SELECT income_type, sum(net_amount_ron) FROM income_records WHERE cnp = ? AND fiscal_year = ? "
            "GROUP BY income_type", (cnp, year)).fetchall()) if year else {}
        if income is None and by_kind:
            income, basis = (Decimal(str(sum(by_kind.values()))) / 12).quantize(CENT), "annual_average"
        kinds = sorted(set(by_kind) | ({"SALARY"} if month else set()))
        main_kind = max(by_kind, key=by_kind.get) if by_kind else None
        open_form = conn.execute(
            "SELECT 1 FROM income_activity_forms WHERE cnp = ? AND start_date <= ? AND (end_date IS NULL OR end_date >= ?)",
            (cnp, iso, iso)).fetchone()
        start = conn.execute(
            "SELECT min(start_date) FROM employments WHERE cnp = ? AND start_date <= ? AND (end_date IS NULL OR end_date >= ?)",
            (cnp, iso, iso)).fetchone()[0]
        return AnafReport(status="found", net_monthly_income=income, income_basis=basis, income_kinds=kinds,
                          self_employed=main_kind == "INDEPENDENT_ACTIVITY" or open_form is not None,
                          employment_start=date.fromisoformat(start) if start else None, as_of=as_of)

    @staticmethod
    def _bureau(conn, cnp, _row, as_of) -> BureauReport:
        if cnp is None:
            return BureauReport(status="not_found", as_of=as_of)
        iso, window_start = as_of.isoformat(), add_months(as_of, -12).isoformat()
        products = conn.execute(DEBTOR_PRODUCTS, (cnp, iso)).fetchall()
        instalments, current_dpd, max_12m = Decimal("0"), 0, 0
        active = [pid for pid, status in products if status != "CLOSED"]
        for pid in active:
            latest = conn.execute("SELECT instalment_due, days_past_due FROM payment_history "
                                  "WHERE product = ? AND month <= ? ORDER BY month DESC LIMIT 1", (pid, iso)).fetchone()
            if latest:
                instalments += _money(latest[0])
                current_dpd = max(current_dpd, latest[1])
        for pid, _status in products:
            dpd = conn.execute("SELECT max(days_past_due) FROM payment_history WHERE product = ? AND month > ? AND month <= ?",
                               (pid, window_start, iso)).fetchone()[0]
            max_12m = max(max_12m, dpd or 0)
        ids = [pid for pid, _ in products]
        events = [row[0] for row in conn.execute(
            f"SELECT event_type FROM credit_events WHERE product IN ({','.join('?' * len(ids))}) "
            "AND event_date > ? AND event_date <= ? ORDER BY event_date", (*ids, window_start, iso))] if ids else []
        insolvency = conn.execute(
            "SELECT 1 FROM insolvency_records WHERE cnp = ? AND opened_on <= ? AND (closed_on IS NULL OR closed_on > ?)",
            (cnp, iso, iso)).fetchone() is not None
        fraud = conn.execute("SELECT count(*) FROM card_fraud_records WHERE cnp = ? AND recorded_on <= ?",
                             (cnp, iso)).fetchone()[0]
        score = conn.execute("SELECT score, status FROM fico_scores WHERE cnp = ? AND calculated_on <= ? "
                             "ORDER BY calculated_on DESC LIMIT 1", (cnp, iso)).fetchone()
        statuses = {status for _pid, status in products}
        return BureauReport(
            status="found", active_products=len(active), monthly_instalments=instalments.quantize(CENT),
            current_max_dpd=current_dpd, max_dpd_12m=max(max_12m, current_dpd),
            written_off_or_assigned=bool(statuses & {"WRITTEN_OFF", "ASSIGNED"}),
            open_insolvency=insolvency or "IN_INSOLVENCY_PROCEDURE" in statuses,
            events_12m=events, fraud_records=fraud,
            score=score[0] if score else None, score_status=score[1] if score else "NONE", as_of=as_of)
