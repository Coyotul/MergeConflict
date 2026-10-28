"""Read-only quality checks shared by the fixture generator and test suite.

These are explicit fictional-dataset policies, not universal banking rules.
"""

from datetime import date


def fictional_data_issues(db, sex_by_cnp=None, amortizing_products=()):
    """Return (issue_code, record_key) findings without modifying the database.

    Opening/closing months may contain history; post-closure months may not.
    Salary months overlap employment; annual salary sources match an employer's
    fiscal code in that year. CNP checks cover categories 1-6 and external sex
    metadata, not checksum validity. Decreasing balances apply only to explicitly
    selected fixed-rate RON amortizers with no unexplained fees/capitalization.
    """
    checks = {
        "history_outside_product_months": """SELECT h.product, h.month FROM payment_history h
            JOIN credit_products p ON p.id=h.product
            WHERE h.month < date(p.opened_on, 'start of month')
               OR (p.closed_on IS NOT NULL AND h.month > date(p.closed_on, 'start of month'))""",
        "event_before_opening": """SELECT e.id FROM credit_events e JOIN credit_products p ON p.id=e.product
            WHERE e.event_date < p.opened_on""",
        "delinquency_without_overdue": "SELECT product, month FROM payment_history WHERE days_past_due>0 AND overdue_amount<=0",
        "debtor_count": """SELECT p.id FROM credit_products p LEFT JOIN product_participants pp ON pp.product=p.id
            GROUP BY p.id HAVING SUM(CASE WHEN pp.role='DEBTOR' THEN 1 ELSE 0 END)<>1""",
        "salary_outside_employment": """SELECT s.cnp, s.employer, s.month FROM monthly_salary_declarations s
            WHERE NOT EXISTS (SELECT 1 FROM employments e WHERE e.cnp=s.cnp AND e.employer=s.employer
                AND e.start_date<=date(s.month, '+1 month', '-1 day')
                AND (e.end_date IS NULL OR e.end_date>=s.month))""",
        "salary_source_mismatch": """SELECT i.id FROM income_records i WHERE i.income_type='SALARY'
            AND NOT EXISTS (SELECT 1 FROM employments e JOIN employers er ON er.id=e.employer
                WHERE e.cnp=i.cnp AND er.fiscal_code=i.source_fiscal_code
                AND e.start_date<=printf('%04d-12-31', i.fiscal_year)
                AND (e.end_date IS NULL OR e.end_date>=printf('%04d-01-01', i.fiscal_year)))""",
    }
    issues = [(code, tuple(row)) for code, sql in checks.items() for row in db.execute(sql)]
    if sex_by_cnp is not None:
        for cnp, birth_date in db.execute("SELECT cnp, birth_date FROM persons"):
            try:
                century = {"1": 1900, "2": 1900, "3": 1800, "4": 1800, "5": 2000, "6": 2000}[cnp[0]]
                encoded = date(century + int(cnp[1:3]), int(cnp[3:5]), int(cnp[5:7])).isoformat()
                sex = "M" if int(cnp[0]) % 2 else "F"
                if encoded != birth_date or sex_by_cnp.get(cnp) != sex:
                    issues.append(("cnp_identity_mismatch", (cnp,)))
            except (KeyError, ValueError, IndexError):
                issues.append(("cnp_unsupported_or_invalid", (cnp,)))
    for product in amortizing_products:
        kind = db.execute("SELECT product_type, currency, rate_type FROM credit_products WHERE id=?", (product,)).fetchone()
        if not kind or kind[0] not in ("CONSUMER_LOAN", "MORTGAGE", "LEASING") or tuple(kind[1:]) != ("RON", "FIXED"):
            raise ValueError("Monotonic balances require an explicitly selected fixed-rate RON amortizing product")
        previous = None
        for month, owed in db.execute("SELECT month, amount_owed FROM payment_history WHERE product=? ORDER BY month", (product,)):
            if previous and owed > previous[1]:
                events = db.execute("""SELECT 1 FROM credit_events WHERE product=?
                    AND event_type IN ('RESTRUCTURING', 'REFINANCING')
                    AND event_date>=date(?, '+1 month') AND event_date<=date(?, '+1 month', '-1 day')""",
                    (product, previous[0], month)).fetchone()
                if not events:
                    issues.append(("unexplained_balance_increase", (product, month)))
            previous = (month, owed)
    return issues