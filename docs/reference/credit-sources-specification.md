# Task: Create the empty "credit sources" database schema

You are a senior database engineer. Write the complete DDL for an **empty SQLite database (version 3.35 or newer)** that simulates the data Romanian banks receive from three external sources during a personal-loan application:

1. **ANAF** (tax authority): a person's declared income by type, source and amount.
2. **Biroul de Credit** (private credit bureau): credit report, FICO score with reason codes, inquiries.
3. **CRC – Centrala Riscului de Credit** (central bank credit register run by the BNR): exposures of 20,000 lei or more.

The database is for a prototype of an AI credit assistant. All data that will later be loaded into it is fictional. **Create the schema only: do not insert any people, loans or other sample data.** The only row you may insert is the single parameter row described in section 0.

## Design principles you must follow

- **The CNP (13-digit personal numeric code) is the key that links all sources.**
- **Credit products are stored only once.** The credit bureau report and the CRC view must both be *derived* from the same credit tables, so the two sources can never contradict each other. Do not create separate loan tables per source.
- **Model time, not just current state.** Loans have monthly payment history; inquiries, scores and events are dated. Views are evaluated "as of" a configurable date.
- **The database represents the external sources only.** Do not add tables for consents, applications, offers, users or audit logs; those belong to a different database.
- Use foreign keys, CHECK constraints and enumerated values (via CHECK ... IN) wherever listed below. Store dates as ISO text (`YYYY-MM-DD`). Store monthly periods as the first day of the month (`YYYY-MM-01`) and enforce that format.
- Start the script with `PRAGMA foreign_keys = ON;`.

## Tables

### 0. Parameters
- `report_params`: exactly one row (enforce `id = 1`), column `as_of_date` defaulting to today. Insert that one row. All views read their reference date from here, because SQLite views cannot take parameters.

### 1. Shared core
- `persons`: `cnp` (PK, exactly 13 digits, digits only), first_name, last_name, birth_date, address, phone, `persona_tag` (nullable text used to label test scenarios).
- `employers`: id, name, fiscal_code (unique), address.
- `employments`: id, cnp → persons, employer → employers, start_date, end_date (nullable = current job, must be ≥ start_date), contract_type in (INDEFINITE, FIXED_TERM, PART_TIME).
- `lenders`: id, name (unique), lender_type in (BANK, IFN, LEASING, INSURER, DEBT_COLLECTOR). IFN = non-bank financial institution.

### 2. ANAF
- `income_activity_forms`: how a person earns non-salary income. id, cnp, form_type in (PFA, II, IF, LIBERAL_PROFESSION), name, fiscal_code, address, start_date, end_date.
- `income_records`: annual declared income. id, cnp, fiscal_year, income_type in (SALARY, INDEPENDENT_ACTIVITY, PENSION, SOCIAL_INSURANCE, RENTAL, INVESTMENT, OTHER), source_name, source_fiscal_code, gross_amount_ron, net_amount_ron. Amounts ≥ 0 and net ≤ gross. Unique on (cnp, fiscal_year, income_type, source_name).
- `monthly_salary_declarations`: monthly salary as declared by employers. cnp, employer, month, gross_ron, net_ron, contributions_ron. Primary key (cnp, employer, month).

### 3. Credit data (single source of truth)
- `credit_products`: id, lender, product_type in (CONSUMER_LOAN, MORTGAGE, CREDIT_CARD, OVERDRAFT, LEASING, OTHER), currency in (RON, EUR, USD, CHF) default RON, opened_on, term_months (nullable for revolving products, otherwise > 0), amount_granted (in the product currency, > 0), **amount_granted_ron** (> 0, used for the CRC threshold), interest_rate (annual %, nullable), rate_type in (FIXED, VARIABLE), status in (ACTIVE, CLOSED, WRITTEN_OFF, ASSIGNED, IN_INSOLVENCY_PROCEDURE) default ACTIVE, closed_on. Enforce: closed_on ≥ opened_on, and status is CLOSED **if and only if** closed_on is set.
- `product_participants`: product → credit_products, cnp → persons, role in (DEBTOR, CODEBTOR, GUARANTOR). Primary key (product, cnp). This is how one loan links to several people.
- `payment_history`: one row per product per month. product, month, amount_owed, instalment_due, amount_paid, overdue_amount, overdue_instalments, days_past_due (all ≥ 0). Add a **stored generated column** `delay_category` derived from days_past_due: 0 → CURRENT, 1–30, 31–60, 61–90, 91–180, over 180 → 180+. Primary key (product, month).
- `credit_events`: id, product, event_date, event_type in (RESTRUCTURING, REFINANCING, DATION_IN_PAYMENT, CONTRACT_ASSIGNMENT, DEBT_ASSIGNMENT, PAYMENT_SUSPENSION), details.

Child rows of credit_products should be deleted when the product is deleted (ON DELETE CASCADE).

### 4. Biroul de Credit only
- `bureau_inquiries`: id, cnp, lender, inquiry_date, inquiry_type in (SOFT, HARD).
- `fico_scores`: id, cnp, calculated_on, score (nullable, 300–850), status in (SCORED, NO_SCORE). Enforce: status is SCORED **if and only if** score is not null. Unique on (cnp, calculated_on).
- `fico_reason_codes`: score → fico_scores, rank (1–5), code, description. Primary key (score, rank).
- `insolvency_records`: id, cnp, procedure_type in (DEBT_REPAYMENT_PLAN, ASSET_LIQUIDATION, SIMPLIFIED), opened_on, closed_on, source.

### 5. CRC only
- `card_fraud_records`: id, cnp, lender (nullable), recorded_on, fraud_type.

### 6. Indexes
Index every foreign-key column used for lookups by person, and the (cnp, date) pairs on inquiries, scores and income.

## Views

All views use `report_params.as_of_date` as the reference date (referred to below as *D*).

**ANAF**
- `v_anaf_income`: income records for the last **3 completed fiscal years** (year of D minus 3 to year of D minus 1).
- `v_anaf_income_by_year`: per cnp and fiscal year: total net income, average net monthly income (total / 12, rounded to 2 decimals), and the list of income types.
- `v_anaf_activity_form`: activity forms that started on or before D and are still active or ended within the last 3 years.

**Biroul de Credit**
- `v_bureau_products`: one row per (person, product) for every participant role. Include lender name and type, product details, and the figures from the **latest payment_history row on or before D** (amount owed, monthly instalment, overdue amount and instalments, days past due, delay category), plus `worst_days_past_due_24m` (max days past due in the 24 months up to D). Exclude products opened after D and products **closed more than 4 years** before D.
- `v_bureau_events`: credit events per participant within the last 4 years.
- `v_bureau_inquiries_6m`: **HARD inquiries only**, from the last 6 months. Soft inquiries are never visible.
- `v_bureau_latest_score`: the most recent score on or before D per person, with its reason code descriptions concatenated in rank order.
- `v_bureau_insolvency`: insolvency records opened on or before D, still open or closed within the last 4 years.
- `v_bureau_summary`: one row per person with: active products as debtor/co-debtor, active guarantees (counted separately), total owed and total monthly instalments (**excluding guarantor roles and closed products**), current max days past due, worst days past due in 24 months, inquiry count (6 months), latest score and status, and a has_insolvency flag. Persons with no credit history must still appear.

**CRC**
- `v_crc_exposures`: products where `amount_granted_ron ≥ 20,000`, for every participant role (including guarantors), using the payment_history row for the **last completed month** (snapshot date = last day of the month before D). Exclude products closed more than 7 years before D.
- `v_crc_fraud`: card-fraud records from the last 7 years.

**Helper for the eligibility engine**
- `v_dsti_inputs`: per person, the latest fiscal year's average net monthly income from `v_anaf_income_by_year`, total monthly instalments from `v_bureau_summary`, and `current_dsti_pct` = instalments / income × 100, rounded to 1 decimal (null when income is missing or zero).

## Acceptance checks

Before giving your answer, verify the script against these cases (you may test them in a scratch database, but do not include the test data in the final script):

1. The script runs on an empty database without errors and leaves exactly one row in `report_params` and zero rows in every other table.
2. These inserts are rejected: a CNP with 12 digits or containing a letter; a FICO score of 900; status SCORED with a null score; a CLOSED product without closed_on; a payment_history month of `2026-10-15`; a product_participants row pointing to a non-existent product.
3. With D = 2026-10-28:
   - income for fiscal year 2022 does not appear in `v_anaf_income`, while 2023–2025 do;
   - a loan closed on 2018-01-01 does not appear in `v_bureau_products`;
   - a SOFT inquiry dated 2026-10-20 and a HARD inquiry dated 2025-01-01 do not appear in `v_bureau_inquiries_6m`;
   - an 8,000 lei credit card does not appear in `v_crc_exposures`, while a 25,000 lei loan does, with snapshot date 2026-09-30;
   - a person who is only a guarantor on a mortgage shows it in `v_bureau_products` and `v_crc_exposures`, but its instalment is not counted in their `v_bureau_summary` totals;
   - a person with instalments of 2,340 lei/month and 2025 net income of 71,955 lei has `current_dsti_pct` = 39.0.

## Output

Return a single SQL script in one code block, ordered as: pragma, parameters table, tables (sections 1–5), indexes, views. Start it with a short comment header explaining the design principles and how to change the as-of date. Comment each section briefly. After the code block, list in a few bullet points any assumption you had to make.
