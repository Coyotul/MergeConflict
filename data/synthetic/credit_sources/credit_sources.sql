PRAGMA foreign_keys = ON;
-- Fictional external credit sources, SQLite >= 3.35. CNP links all sources;
-- bureau and CRC share credit products and dated monthly payment history.
-- Empty schema: only the mandatory configuration row is inserted.
-- Change the reference date: UPDATE report_params SET as_of_date = '2026-10-28' WHERE id = 1;
-- Payment-history money is RON; amount_granted retains the product currency.

-- 0. Singleton reference date (SQLite CURRENT_DATE uses UTC).
CREATE TABLE report_params (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    as_of_date TEXT NOT NULL DEFAULT (CURRENT_DATE)
        CHECK (as_of_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
               AND date(as_of_date, '+0 days') IS as_of_date)
);
INSERT INTO report_params (id) VALUES (1);
CREATE TRIGGER report_params_keep_singleton
BEFORE DELETE ON report_params
BEGIN
    SELECT RAISE(ABORT, 'report_params must retain its single row; update as_of_date instead');
END;

-- 1. Shared core. Contact fields are optional; CNP validation is syntactic only.
CREATE TABLE persons (
    cnp TEXT PRIMARY KEY NOT NULL
        CHECK (typeof(cnp) = 'text' AND length(cnp) = 13
               AND instr(cnp, char(0)) = 0 AND cnp NOT GLOB '*[^0-9]*'),
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    birth_date TEXT NOT NULL
        CHECK (birth_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
               AND date(birth_date, '+0 days') IS birth_date),
    address TEXT,
    phone TEXT,
    persona_tag TEXT
);
CREATE TABLE employers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    fiscal_code TEXT NOT NULL UNIQUE,
    address TEXT
);
CREATE TABLE employments (
    id INTEGER PRIMARY KEY,
    cnp TEXT NOT NULL REFERENCES persons(cnp),
    employer INTEGER NOT NULL REFERENCES employers(id),
    start_date TEXT NOT NULL
        CHECK (start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
               AND date(start_date, '+0 days') IS start_date),
    end_date TEXT
        CHECK (end_date IS NULL OR
               (end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                AND date(end_date, '+0 days') IS end_date AND end_date >= start_date)),
    contract_type TEXT NOT NULL CHECK (contract_type IN ('INDEFINITE', 'FIXED_TERM', 'PART_TIME'))
);
CREATE TABLE lenders (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    lender_type TEXT NOT NULL CHECK (lender_type IN ('BANK', 'IFN', 'LEASING', 'INSURER', 'DEBT_COLLECTOR'))
);

-- 2. ANAF: annual income, activity forms and monthly salary declarations.
CREATE TABLE income_activity_forms (
    id INTEGER PRIMARY KEY,
    cnp TEXT NOT NULL REFERENCES persons(cnp),
    form_type TEXT NOT NULL CHECK (form_type IN ('PFA', 'II', 'IF', 'LIBERAL_PROFESSION')),
    name TEXT NOT NULL,
    fiscal_code TEXT,
    address TEXT,
    start_date TEXT NOT NULL
        CHECK (start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
               AND date(start_date, '+0 days') IS start_date),
    end_date TEXT
        CHECK (end_date IS NULL OR
               (end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                AND date(end_date, '+0 days') IS end_date AND end_date >= start_date))
);
CREATE TABLE income_records (
    id INTEGER PRIMARY KEY,
    cnp TEXT NOT NULL REFERENCES persons(cnp),
    fiscal_year INTEGER NOT NULL CHECK (typeof(fiscal_year) = 'integer' AND fiscal_year BETWEEN 1 AND 9999),
    income_type TEXT NOT NULL CHECK (income_type IN
        ('SALARY', 'INDEPENDENT_ACTIVITY', 'PENSION', 'SOCIAL_INSURANCE', 'RENTAL', 'INVESTMENT', 'OTHER')),
    source_name TEXT NOT NULL,
    source_fiscal_code TEXT,
    gross_amount_ron REAL NOT NULL CHECK (typeof(gross_amount_ron) IN ('integer', 'real') AND gross_amount_ron >= 0),
    net_amount_ron REAL NOT NULL CHECK (typeof(net_amount_ron) IN ('integer', 'real')
                                      AND net_amount_ron >= 0 AND net_amount_ron <= gross_amount_ron),
    UNIQUE (cnp, fiscal_year, income_type, source_name),
    -- Reject infinity without imposing a business-specific monetary ceiling.
    CHECK (gross_amount_ron <= 1.7976931348623157e308 AND net_amount_ron <= 1.7976931348623157e308)
);
CREATE TABLE monthly_salary_declarations (
    cnp TEXT NOT NULL REFERENCES persons(cnp),
    employer INTEGER NOT NULL REFERENCES employers(id),
    month TEXT NOT NULL
        CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-01'
               AND date(month, '+0 days') IS month),
    gross_ron REAL NOT NULL CHECK (typeof(gross_ron) IN ('integer', 'real') AND gross_ron >= 0),
    net_ron REAL NOT NULL CHECK (typeof(net_ron) IN ('integer', 'real') AND net_ron >= 0 AND net_ron <= gross_ron),
    contributions_ron REAL NOT NULL CHECK (typeof(contributions_ron) IN ('integer', 'real') AND contributions_ron >= 0),
    PRIMARY KEY (cnp, employer, month),
    CHECK (gross_ron <= 1.7976931348623157e308 AND net_ron <= 1.7976931348623157e308
           AND contributions_ron <= 1.7976931348623157e308)
);

-- 3. Credit data: one source of truth, with cascading product children.
CREATE TABLE credit_products (
    id INTEGER PRIMARY KEY,
    lender INTEGER NOT NULL REFERENCES lenders(id),
    product_type TEXT NOT NULL CHECK (product_type IN
        ('CONSUMER_LOAN', 'MORTGAGE', 'CREDIT_CARD', 'OVERDRAFT', 'LEASING', 'OTHER')),
    currency TEXT NOT NULL DEFAULT 'RON' CHECK (currency IN ('RON', 'EUR', 'USD', 'CHF')),
    opened_on TEXT NOT NULL
        CHECK (opened_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
               AND date(opened_on, '+0 days') IS opened_on),
    term_months INTEGER CHECK (term_months IS NULL OR (typeof(term_months) = 'integer' AND term_months > 0)),
    amount_granted REAL NOT NULL CHECK (typeof(amount_granted) IN ('integer', 'real') AND amount_granted > 0),
    amount_granted_ron REAL NOT NULL CHECK (typeof(amount_granted_ron) IN ('integer', 'real') AND amount_granted_ron > 0),
    interest_rate REAL CHECK (interest_rate IS NULL OR (typeof(interest_rate) IN ('integer', 'real') AND interest_rate >= 0)),
    rate_type TEXT NOT NULL CHECK (rate_type IN ('FIXED', 'VARIABLE')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN
        ('ACTIVE', 'CLOSED', 'WRITTEN_OFF', 'ASSIGNED', 'IN_INSOLVENCY_PROCEDURE')),
    closed_on TEXT
        CHECK (closed_on IS NULL OR
               (closed_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                AND date(closed_on, '+0 days') IS closed_on AND closed_on >= opened_on)),
    CHECK (term_months IS NOT NULL OR product_type IN ('CREDIT_CARD', 'OVERDRAFT')),
    CHECK ((status = 'CLOSED') = (closed_on IS NOT NULL)),
    CHECK (amount_granted <= 1.7976931348623157e308 AND amount_granted_ron <= 1.7976931348623157e308
           AND (interest_rate IS NULL OR interest_rate <= 1.7976931348623157e308))
);
CREATE TABLE product_participants (
    product INTEGER NOT NULL REFERENCES credit_products(id) ON DELETE CASCADE,
    cnp TEXT NOT NULL REFERENCES persons(cnp),
    role TEXT NOT NULL CHECK (role IN ('DEBTOR', 'CODEBTOR', 'GUARANTOR')),
    PRIMARY KEY (product, cnp)
);
CREATE TABLE payment_history (
    product INTEGER NOT NULL REFERENCES credit_products(id) ON DELETE CASCADE,
    month TEXT NOT NULL
        CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-01'
               AND date(month, '+0 days') IS month),
    amount_owed REAL NOT NULL CHECK (typeof(amount_owed) IN ('integer', 'real') AND amount_owed >= 0),
    instalment_due REAL NOT NULL CHECK (typeof(instalment_due) IN ('integer', 'real') AND instalment_due >= 0),
    amount_paid REAL NOT NULL CHECK (typeof(amount_paid) IN ('integer', 'real') AND amount_paid >= 0),
    overdue_amount REAL NOT NULL CHECK (typeof(overdue_amount) IN ('integer', 'real') AND overdue_amount >= 0),
    overdue_instalments INTEGER NOT NULL CHECK (typeof(overdue_instalments) = 'integer' AND overdue_instalments >= 0),
    days_past_due INTEGER NOT NULL CHECK (typeof(days_past_due) = 'integer' AND days_past_due >= 0),
    delay_category TEXT GENERATED ALWAYS AS (
        CASE WHEN days_past_due = 0 THEN 'CURRENT'
             WHEN days_past_due <= 30 THEN '1-30'
             WHEN days_past_due <= 60 THEN '31-60'
             WHEN days_past_due <= 90 THEN '61-90'
             WHEN days_past_due <= 180 THEN '91-180'
             ELSE '180+' END
    ) STORED,
    PRIMARY KEY (product, month),
    CHECK (amount_owed <= 1.7976931348623157e308 AND instalment_due <= 1.7976931348623157e308
           AND amount_paid <= 1.7976931348623157e308 AND overdue_amount <= 1.7976931348623157e308)
);
CREATE TABLE credit_events (
    id INTEGER PRIMARY KEY,
    product INTEGER NOT NULL REFERENCES credit_products(id) ON DELETE CASCADE,
    event_date TEXT NOT NULL
        CHECK (event_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
               AND date(event_date, '+0 days') IS event_date),
    event_type TEXT NOT NULL CHECK (event_type IN
        ('RESTRUCTURING', 'REFINANCING', 'DATION_IN_PAYMENT', 'CONTRACT_ASSIGNMENT', 'DEBT_ASSIGNMENT', 'PAYMENT_SUSPENSION')),
    details TEXT
);

-- 4. Bureau-specific records, including ordered explanations of each score.
CREATE TABLE bureau_inquiries (
    id INTEGER PRIMARY KEY,
    cnp TEXT NOT NULL REFERENCES persons(cnp),
    lender INTEGER NOT NULL REFERENCES lenders(id),
    inquiry_date TEXT NOT NULL
        CHECK (inquiry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
               AND date(inquiry_date, '+0 days') IS inquiry_date),
    inquiry_type TEXT NOT NULL CHECK (inquiry_type IN ('SOFT', 'HARD'))
);
CREATE TABLE fico_scores (
    id INTEGER PRIMARY KEY,
    cnp TEXT NOT NULL REFERENCES persons(cnp),
    calculated_on TEXT NOT NULL
        CHECK (calculated_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
               AND date(calculated_on, '+0 days') IS calculated_on),
    score INTEGER CHECK (score IS NULL OR (typeof(score) = 'integer' AND score BETWEEN 300 AND 850)),
    status TEXT NOT NULL CHECK (status IN ('SCORED', 'NO_SCORE')),
    CHECK ((status = 'SCORED') = (score IS NOT NULL)),
    UNIQUE (cnp, calculated_on)
);
CREATE TABLE fico_reason_codes (
    score INTEGER NOT NULL REFERENCES fico_scores(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL CHECK (typeof(rank) = 'integer' AND rank BETWEEN 1 AND 5),
    code TEXT NOT NULL,
    description TEXT NOT NULL,
    PRIMARY KEY (score, rank)
);
CREATE TABLE insolvency_records (
    id INTEGER PRIMARY KEY,
    cnp TEXT NOT NULL REFERENCES persons(cnp),
    procedure_type TEXT NOT NULL CHECK (procedure_type IN ('DEBT_REPAYMENT_PLAN', 'ASSET_LIQUIDATION', 'SIMPLIFIED')),
    opened_on TEXT NOT NULL
        CHECK (opened_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
               AND date(opened_on, '+0 days') IS opened_on),
    closed_on TEXT
        CHECK (closed_on IS NULL OR
               (closed_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                AND date(closed_on, '+0 days') IS closed_on AND closed_on >= opened_on)),
    source TEXT NOT NULL
);

-- 5. CRC-specific card-fraud records.
CREATE TABLE card_fraud_records (
    id INTEGER PRIMARY KEY,
    cnp TEXT NOT NULL REFERENCES persons(cnp),
    lender INTEGER REFERENCES lenders(id),
    recorded_on TEXT NOT NULL
        CHECK (recorded_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
               AND date(recorded_on, '+0 days') IS recorded_on),
    fraud_type TEXT NOT NULL
);

-- 6. Lookup indexes. PK/UNIQUE indexes already cover income (cnp, fiscal_year),
-- scores (cnp, calculated_on), salary cnp, and product/month history lookups.
CREATE INDEX idx_employments_cnp ON employments(cnp, start_date);
CREATE INDEX idx_employments_employer ON employments(employer);
CREATE INDEX idx_activity_cnp ON income_activity_forms(cnp, start_date);
CREATE INDEX idx_salary_employer ON monthly_salary_declarations(employer, month);
CREATE INDEX idx_products_lender ON credit_products(lender);
CREATE INDEX idx_participants_cnp ON product_participants(cnp, product);
CREATE INDEX idx_events_product_date ON credit_events(product, event_date);
CREATE INDEX idx_inquiries_cnp_date ON bureau_inquiries(cnp, inquiry_date);
CREATE INDEX idx_inquiries_lender ON bureau_inquiries(lender);
CREATE INDEX idx_insolvency_cnp_date ON insolvency_records(cnp, opened_on);
CREATE INDEX idx_fraud_cnp_date ON card_fraud_records(cnp, recorded_on);
CREATE INDEX idx_fraud_lender ON card_fraud_records(lender);

-- 7. ANAF views: completed fiscal years and retained activity forms.
CREATE VIEW v_anaf_income AS
SELECT i.*
FROM income_records AS i CROSS JOIN report_params AS r
WHERE i.fiscal_year BETWEEN CAST(strftime('%Y', r.as_of_date) AS INTEGER) - 3
                        AND CAST(strftime('%Y', r.as_of_date) AS INTEGER) - 1;

CREATE VIEW v_anaf_income_by_year AS
SELECT i.cnp, i.fiscal_year,
       SUM(i.net_amount_ron) AS total_net_income_ron,
       ROUND(SUM(i.net_amount_ron) / 12.0, 2) AS average_net_monthly_income_ron,
       (SELECT group_concat(t.income_type, ', ')
        FROM (SELECT DISTINCT x.income_type FROM v_anaf_income AS x
              WHERE x.cnp = i.cnp AND x.fiscal_year = i.fiscal_year
              ORDER BY x.income_type) AS t) AS income_types
FROM v_anaf_income AS i
GROUP BY i.cnp, i.fiscal_year;

CREATE VIEW v_anaf_activity_form AS
SELECT a.*
FROM income_activity_forms AS a CROSS JOIN report_params AS r
WHERE a.start_date <= r.as_of_date
  AND (a.end_date IS NULL OR a.end_date >= date(r.as_of_date, '-3 years'));

-- 8. Bureau products: latest available history, never a row after D.
-- is_active_as_of means not yet closed; a closure after D is not yet effective.
CREATE VIEW v_bureau_products AS
SELECT pp.cnp, pp.product, pp.role,
       p.lender, l.name AS lender_name, l.lender_type,
       p.product_type, p.currency, p.opened_on, p.term_months,
       p.amount_granted, p.amount_granted_ron, p.interest_rate, p.rate_type,
       CASE WHEN p.closed_on > r.as_of_date THEN 'ACTIVE' ELSE p.status END AS status,
       CASE WHEN p.closed_on <= r.as_of_date THEN p.closed_on END AS closed_on,
       CASE WHEN p.closed_on IS NULL OR p.closed_on > r.as_of_date THEN 1 ELSE 0 END AS is_active_as_of,
       h.month AS payment_month, h.amount_owed, h.instalment_due,
       h.amount_paid, h.overdue_amount, h.overdue_instalments, h.days_past_due, h.delay_category,
       (SELECT MAX(w.days_past_due) FROM payment_history AS w
        WHERE w.product = p.id
          AND w.month BETWEEN date(r.as_of_date, '-24 months') AND r.as_of_date
          AND w.month >= date(p.opened_on, 'start of month')) AS worst_days_past_due_24m
FROM product_participants AS pp
JOIN credit_products AS p ON p.id = pp.product
JOIN lenders AS l ON l.id = p.lender
CROSS JOIN report_params AS r
LEFT JOIN payment_history AS h ON h.product = p.id
 AND h.month = (SELECT MAX(h2.month) FROM payment_history AS h2
                WHERE h2.product = p.id AND h2.month <= r.as_of_date
                  AND h2.month >= date(p.opened_on, 'start of month'))
WHERE p.opened_on <= r.as_of_date
  AND (p.closed_on IS NULL OR p.closed_on >= date(r.as_of_date, '-4 years'));

CREATE VIEW v_bureau_events AS
SELECT pp.cnp, pp.role, e.id, e.product, e.event_date, e.event_type, e.details,
       p.lender, l.name AS lender_name
FROM credit_events AS e
JOIN product_participants AS pp ON pp.product = e.product
JOIN credit_products AS p ON p.id = e.product
JOIN lenders AS l ON l.id = p.lender
CROSS JOIN report_params AS r
WHERE e.event_date BETWEEN date(r.as_of_date, '-4 years') AND r.as_of_date
  AND p.opened_on <= r.as_of_date;

CREATE VIEW v_bureau_inquiries_6m AS
SELECT i.*, l.name AS lender_name, l.lender_type
FROM bureau_inquiries AS i
JOIN lenders AS l ON l.id = i.lender
CROSS JOIN report_params AS r
WHERE i.inquiry_type = 'HARD'
  AND i.inquiry_date BETWEEN date(r.as_of_date, '-6 months') AND r.as_of_date;

CREATE VIEW v_bureau_latest_score AS
SELECT s.*,
       (SELECT group_concat(ordered.description, '; ')
        FROM (SELECT rc.description FROM fico_reason_codes AS rc
              WHERE rc.score = s.id ORDER BY rc.rank) AS ordered) AS reason_descriptions
FROM fico_scores AS s CROSS JOIN report_params AS r
WHERE s.calculated_on = (SELECT MAX(s2.calculated_on) FROM fico_scores AS s2
                         WHERE s2.cnp = s.cnp AND s2.calculated_on <= r.as_of_date);

CREATE VIEW v_bureau_insolvency AS
SELECT i.id, i.cnp, i.procedure_type, i.opened_on,
       CASE WHEN i.closed_on <= r.as_of_date THEN i.closed_on END AS closed_on,
       i.source
FROM insolvency_records AS i CROSS JOIN report_params AS r
WHERE i.opened_on <= r.as_of_date
  AND (i.closed_on IS NULL OR i.closed_on >= date(r.as_of_date, '-4 years'));

-- Correlated, indexed aggregates avoid both join fan-out and materializing every
-- person's debts when an eligibility request filters this view to one CNP.
-- Debt totals/current delinquency exclude guarantees and already closed products.
-- Worst 24m delinquency includes retained closed debtor/co-debtor products.
CREATE VIEW v_bureau_summary AS
SELECT p.cnp,
       (SELECT COUNT(*) FROM v_bureau_products AS d WHERE d.cnp = p.cnp
        AND d.role IN ('DEBTOR', 'CODEBTOR') AND d.is_active_as_of = 1) AS active_products,
       (SELECT COUNT(*) FROM v_bureau_products AS d WHERE d.cnp = p.cnp
        AND d.role = 'GUARANTOR' AND d.is_active_as_of = 1) AS active_guarantees,
       COALESCE((SELECT SUM(d.amount_owed) FROM v_bureau_products AS d WHERE d.cnp = p.cnp
        AND d.role IN ('DEBTOR', 'CODEBTOR') AND d.is_active_as_of = 1), 0.0) AS total_owed_ron,
       COALESCE((SELECT SUM(d.instalment_due) FROM v_bureau_products AS d WHERE d.cnp = p.cnp
        AND d.role IN ('DEBTOR', 'CODEBTOR') AND d.is_active_as_of = 1), 0.0) AS total_monthly_instalments_ron,
       COALESCE((SELECT MAX(d.days_past_due) FROM v_bureau_products AS d WHERE d.cnp = p.cnp
        AND d.role IN ('DEBTOR', 'CODEBTOR') AND d.is_active_as_of = 1), 0) AS current_max_days_past_due,
       COALESCE((SELECT MAX(d.worst_days_past_due_24m) FROM v_bureau_products AS d WHERE d.cnp = p.cnp
        AND d.role IN ('DEBTOR', 'CODEBTOR')), 0) AS worst_days_past_due_24m,
       (SELECT COUNT(*) FROM v_bureau_inquiries_6m AS q WHERE q.cnp = p.cnp) AS inquiry_count_6m,
       s.score AS latest_score, s.status AS latest_score_status,
       s.calculated_on AS latest_score_date,
       EXISTS (SELECT 1 FROM v_bureau_insolvency AS i WHERE i.cnp = p.cnp) AS has_insolvency
FROM persons AS p
LEFT JOIN fico_scores AS s ON s.cnp = p.cnp
 AND s.calculated_on = (SELECT MAX(s2.calculated_on) FROM fico_scores AS s2
                       WHERE s2.cnp = p.cnp AND s2.calculated_on <= (SELECT as_of_date FROM report_params));

-- 9. CRC: exact previous-month snapshot; no fallback to older history.
-- Products opened after the snapshot cannot be exposures at that snapshot.
CREATE VIEW v_crc_exposures AS
WITH reference AS (
    SELECT as_of_date,
           date(as_of_date, 'start of month', '-1 month') AS history_month,
           date(as_of_date, 'start of month', '-1 day') AS snapshot_date
    FROM report_params
)
SELECT pp.cnp, pp.product, pp.role,
       p.lender, l.name AS lender_name, l.lender_type,
       p.product_type, p.currency, p.opened_on, p.term_months,
       p.amount_granted, p.amount_granted_ron, p.interest_rate, p.rate_type,
       CASE WHEN p.closed_on > r.snapshot_date THEN 'ACTIVE' ELSE p.status END AS status,
       CASE WHEN p.closed_on <= r.snapshot_date THEN p.closed_on END AS closed_on,
       r.snapshot_date, h.month AS payment_month,
       h.amount_owed, h.instalment_due, h.amount_paid, h.overdue_amount,
       h.overdue_instalments, h.days_past_due, h.delay_category
FROM credit_products AS p
JOIN product_participants AS pp ON pp.product = p.id
JOIN lenders AS l ON l.id = p.lender
CROSS JOIN reference AS r
LEFT JOIN payment_history AS h ON h.product = p.id AND h.month = r.history_month
WHERE p.amount_granted_ron >= 20000
  AND p.opened_on <= r.snapshot_date
  AND (p.closed_on IS NULL OR p.closed_on >= date(r.as_of_date, '-7 years'));

CREATE VIEW v_crc_fraud AS
SELECT f.*, l.name AS lender_name, l.lender_type
FROM card_fraud_records AS f
LEFT JOIN lenders AS l ON l.id = f.lender
CROSS JOIN report_params AS r
WHERE f.recorded_on BETWEEN date(r.as_of_date, '-7 years') AND r.as_of_date;

-- 10. Eligibility helper: latest available completed fiscal year per person.
-- Compute the same income aggregate as v_anaf_income_by_year with a correlated
-- CNP filter before grouping, avoiding SQLite materializing all people's years.
CREATE VIEW v_dsti_inputs AS
SELECT x.cnp, x.fiscal_year, x.average_net_monthly_income_ron,
       x.total_monthly_instalments_ron,
       ROUND(x.total_monthly_instalments_ron / NULLIF(x.average_net_monthly_income_ron, 0) * 100.0, 1) AS current_dsti_pct
FROM (
    SELECT s.cnp, s.total_monthly_instalments_ron,
           (SELECT MAX(i.fiscal_year) FROM v_anaf_income AS i WHERE i.cnp = s.cnp) AS fiscal_year,
           (SELECT ROUND(SUM(i.net_amount_ron) / 12.0, 2) FROM v_anaf_income AS i
            WHERE i.cnp = s.cnp
              AND i.fiscal_year = (SELECT MAX(y.fiscal_year) FROM v_anaf_income AS y WHERE y.cnp = s.cnp)) AS average_net_monthly_income_ron
    FROM v_bureau_summary AS s
) AS x;