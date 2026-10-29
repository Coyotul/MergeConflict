# Orchestrator Eligibility (SQLite ANAF + Biroul de Credit) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the orchestrator's stub `run_eligibility_check` and `get_customer_profile` with deterministic rules fed by session fields plus SQLite-backed mock ANAF and credit-bureau lookups, for nine new demo customers who can each sign in to the customer app.

**Architecture:** One read-only SQLite adapter (`src/integrations/credit_sources/`) answers ANAF, bureau and person lookups for customers bound by config. A pure rules function (`src/rules/eligibility/credit_check.py`) turns session fields + reports into `EligibilityResult`. `src/core/composition.py` overrides the two stub tools with real handlers. The TypeScript demo server gets one account per demo customer.

**Tech Stack:** Python 3.11+, Pydantic v2, stdlib `sqlite3`, pytest; TypeScript, Next.js, node:test, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-29-orchestrator-eligibility-design.md`

## Global Constraints

- The LLM never computes or overrides any part of the decision.
- Missing/unavailable ANAF or bureau never reads as clean; DB missing or SQLite error → `ToolUnavailable`.
- Customer ID → CNP binding is server config only (`config/orchestrator/customer_bindings.yaml`).
- All time windows are relative to `report_params.as_of_date` (default `2026-10-28`), never the wall clock.
- Money: SQLite REAL → `Decimal(str(x)).quantize(Decimal("0.01"))` at the adapter boundary.
- Handlers stay synchronous; no `asyncio`.
- Do not modify `src/services/eligibility/`, `src/rules/eligibility/engine.py`, `src/core/eligibility_demo.py`, existing curated personas in the generator, or the staff app.
- Precedence: `not_satisfied` > `manual_review` > `more_information_required` > `satisfied`; return all triggered reasons.
- Customer IDs (exact, used by Python and TypeScript):
  `cust-alex-morgan`, `cust-elena-popa`, `cust-radu-mihai`, `cust-dan-ionescu`, `cust-andrei-stan`, `cust-ioana-marin`, `cust-victor-dobre`, `cust-maria-stoica`, `cust-mihai-ilie`.
- Work on branch `feat/orchestrator-eligibility` from `feat/agent-trace`.

## Review Focus

- Bound customer whose CNP is absent from the DB (stale bindings vs regenerated DB) → `not_found` from both, rules give `manual_review` (`anaf_income_not_found`), not a crash. Test in Task 2.
- Unbound customer ID (e.g. old `cust-001` from a stale browser session) → profile tool fails cleanly (`tool_failed`, "unknown customer"), eligibility `manual_review`; frontend drops stored sessions whose customer ID is not the signed-in one. Tests in Tasks 2 and 4.
- Product payments in the future relative to `as_of_date` (dataset has intentional future rows) are ignored for current DPD/instalment. Test in Task 2.
- DTI exactly 40% passes; 90 days current DPD rejects, 89 reviews; income exactly 2,500 passes. Tests in Task 2.
- Declared obligations higher than the bureau total → the declared figure is used. Test in Task 2.

---

### Task 1: Demo people in the credit-source dataset

**Files:**
- Modify: `scripts/credit_sources/generate_credit_sources.py` (`person()` gains `first_name=None, last_name=None`; new `demo_cases()` called in `build_fixture` after `random_cases`; validation/manifest/catalogue include demo people)
- Regenerate: `data/synthetic/credit_sources/credit_sources_sample_data.sql`, `sample_data_manifest.json`, `SAMPLE_DATA.md`
- Create: `config/orchestrator/customer_bindings.yaml`
- Modify: `tests/credit_sources/test_credit_sources.py`, `tests/credit_sources/test_setup.py` (row counts only)
- Regenerate: `data/synthetic/documents/` (nine folders via `scripts/generate_documents.py --cnp`), `INDEX.md`; delete the five old folders

**Interfaces:**
- Produces: `customer_bindings.yaml` shaped
  ```yaml
  version: "demo-bindings-2026-10-29"
  bindings:
    - {customer_id: cust-alex-morgan, cnp: "<generated>", persona_tag: DEMO_ALEX_MORGAN}
  ```
  and a local DB at `data/local/credit_sources.db` containing the nine `DEMO_*` people.

Demo people (`as_of_date` 2026-10-28). Salary = `salary(c, 2025, 12*m)` and `salary(c, 2026, 12*m)` on an `employment(start="2021-03-01")` unless noted; clean people get `score(c, 750)`:

| Tag | Name | ANAF | Bureau |
|---|---|---|---|
| DEMO_ALEX_MORGAN | Alex Morgan | m=8500 | none |
| DEMO_ELENA_POPA | Elena Popa | m=4500 | none |
| DEMO_RADU_MIHAI | Radu Mihai | employer 1 m=3000, employer 2 m=2000 | two CONSUMER_LOANs, history 2026-01..2026-10 instalment 150 each, dpd 0 |
| DEMO_DAN_IONESCU | Dan Ionescu | m=5996.25 | CONSUMER_LOAN 80000 opened 2026-06-15, history 2026-06..2026-10 instalment 2340 |
| DEMO_ANDREI_STAN | Andrei Stan | m=2300 | none |
| DEMO_LATE_91 | Ioana Marin | m=6000 | CONSUMER_LOAN, history 2026-01..2026-09 dpd 0, 2026-10-01 dpd 91 |
| DEMO_INSOLVENCY | Victor Dobre | m=5500 | `insolvency_records` DEBT_REPAYMENT_PLAN opened 2025-01-01, closed NULL |
| DEMO_RESTRUCTURED | Maria Stoica | m=6500 | CONSUMER_LOAN, history 2026-01..2026-10 dpd 0, `event(p, "RESTRUCTURING", "2026-08-28")` |
| DEMO_SELF_EMPLOYED | Mihai Ilie | no salary; `income(c, "INDEPENDENT_ACTIVITY", 84000, 2025)` + active PFA `income_activity_forms` row started 2022-01-15 | none |

- [ ] **Step 1:** Add `demo_cases()` and the `person()` name parameters; run `python scripts/credit_sources/generate_credit_sources.py` (see its `main()` for flags) to regenerate SQL, manifest and catalogue. Existing curated/random CNPs must be byte-identical (diff the old and new `sample_data_manifest.json` scenarios list: only additions).
- [ ] **Step 2:** Run `python -m pytest tests/credit_sources -q`; update only counts that changed. Expected: all pass.
- [ ] **Step 3:** Build the DB: `python scripts/credit_sources/setup.py`. Expected: `data/local/credit_sources.db` exists; `SELECT count(*) FROM persons WHERE persona_tag LIKE 'DEMO_%'` = 9.
- [ ] **Step 4:** Write `customer_bindings.yaml` with the generated CNPs.
- [ ] **Step 5:** Regenerate PDFs for the nine CNPs with `scripts/generate_documents.py --cnp <cnp>`, remove the five old folders, rewrite `INDEX.md` table.
- [ ] **Step 6:** Commit `agent(credit-sources): add nine demo customers with ANAF records`.

---

### Task 2: SQLite credit-source adapter and deterministic rules

**Files:**
- Create: `src/integrations/credit_sources/__init__.py`, `src/integrations/credit_sources/models.py`, `src/integrations/credit_sources/sqlite.py`
- Create: `src/rules/eligibility/credit_check.py`
- Modify: `src/agent/tools/stubs.py` (move `EligibilityRule` to `credit_check.py`, import it back; add new fields to loader)
- Modify: `config/orchestrator/eligibility.yaml` (per product add `reject_dpd: 90`, `review_dpd: 31`, `min_score: 500`, `income_gap_ratio: 0.10`; `rule_version: "credit-check-2026-10-29"`)
- Test: `tests/unit/orchestrator/test_credit_sources_sqlite.py`, `tests/unit/orchestrator/test_credit_check.py`

**Interfaces:**
- Produces (`models.py`, all Pydantic, `simulated: bool = True`):
  - `CustomerBinding(customer_id: str, cnp: str, persona_tag: str)`; `load_bindings(path: Path) -> dict[str, CustomerBinding]`
  - `PersonRecord(customer_id: str, full_name: str, birth_date: date, as_of: date)`
  - `AnafReport(status: Literal["found","not_found"], net_monthly_income: Decimal | None, income_basis: Literal["monthly_salary","annual_average"] | None, income_kinds: list[str], self_employed: bool, employment_start: date | None, as_of: date)`
  - `BureauReport(status: Literal["found","not_found"], active_products: int, monthly_instalments: Decimal, current_max_dpd: int, max_dpd_12m: int, written_off_or_assigned: bool, open_insolvency: bool, events_12m: list[str], fraud_records: int, score: int | None, score_status: Literal["SCORED","NO_SCORE","NONE"], as_of: date)`
- Produces (`sqlite.py`): `SqliteCreditSources(db_path: Path, bindings: dict[str, CustomerBinding])` with `person(customer_id) -> PersonRecord | None`, `anaf(customer_id) -> AnafReport`, `bureau(customer_id) -> BureauReport`. Opens `mode=ro`; missing file or `sqlite3.Error` → `ToolUnavailable`. Unbound ID or CNP not in `persons` → `status="not_found"` (`person` returns `None`).
- Produces (`credit_check.py`): `EligibilityRule` (existing fields + `reject_dpd: int`, `review_dpd: int`, `min_score: int`, `income_gap_ratio: Decimal`) and
  `evaluate(fields: dict[str, Any], product: CreditProduct, rule: EligibilityRule, anaf: AnafReport, bureau: BureauReport) -> EligibilityResult`
  where `fields` holds `amount, term_months, age, employment_type, employment_months, monthly_net_income, existing_monthly_obligations` (missing keys allowed).

Adapter semantics (all relative to `as_of`): monthly salary = sum of `net_ron` of the latest `monthly_salary_declarations` month `< as_of` month start; else annual average = latest `income_records` year within `as_of` year −3 summed /12; `self_employed` = `INDEPENDENT_ACTIVITY` is the largest latest-year kind or an activity form is open at `as_of`; `employment_start` = earliest start of employments open at `as_of`. Bureau counts products where the CNP is DEBTOR/CODEBTOR and status ≠ CLOSED; instalment and current DPD from each product's latest `payment_history` month `<= as_of`; `max_dpd_12m` over months in `(as_of − 12 months, as_of]`; events and insolvency/fraud with dates `<= as_of`; latest score `<= as_of`.

Rules — reason codes (exact):
- not_satisfied: `amount_out_of_range`, `term_out_of_range`, `age_out_of_range` (age < min_age or age + ceil(term/12) > max_age_at_maturity), `income_below_minimum` (ANAF < min_monthly_income), `employment_too_short` (months from ANAF `employment_start` to `as_of`, else declared), `dti_above_limit` ((annuity_installment(amount, product rate, term) + max(declared, bureau.monthly_instalments)) / ANAF income > max_dti), `bureau_current_delinquency` (current_max_dpd ≥ reject_dpd), `bureau_written_off_or_assigned`, `bureau_open_insolvency`.
- manual_review: `self_employed` (declared or ANAF), `bureau_past_delinquency` (review_dpd ≤ max_dpd_12m, and current < reject_dpd), `bureau_recent_restructuring` (RESTRUCTURING or PAYMENT_SUSPENSION in events_12m), `bureau_fraud_record`, `bureau_low_score` (score < min_score), `anaf_income_not_found` (then skip income and DTI rules).
- more_information_required: `missing_field` (one reason; names in `missing_fields`).
- informational: `income_gap` (|declared − ANAF| / ANAF > income_gap_ratio; message shows both), `dti_computed` (message with percent), `bureau_obligations_counted`, `no_credit_history` (found, 0 products), `no_score`; `all_preliminary_rules_passed` when satisfied.
- `annuity_installment` stays in `stubs.py`; move it to `credit_check.py` and re-export from `stubs.py`.

- [ ] **Step 1: Write failing rules tests** in `test_credit_check.py` using hand-built reports (no DB):
  `test_clean_customer_satisfied`, `test_income_exactly_minimum_passes` (2500), `test_income_below_minimum_rejects` (2499.99), `test_dti_exactly_limit_passes`, `test_dti_above_limit_rejects`, `test_declared_obligations_win_when_higher`, `test_current_dpd_90_rejects`, `test_current_dpd_89_reviews`, `test_cured_90_dpd_in_12m_reviews`, `test_insolvency_rejects`, `test_restructuring_reviews`, `test_self_employed_reviews`, `test_anaf_not_found_reviews_and_skips_income_rules`, `test_missing_field_more_information`, `test_reject_beats_review` (both triggered → `not_satisfied`, both codes present), `test_income_gap_reason_message` (declared 7000 vs ANAF 5000 → `income_gap` with "7000" and "5000" in message), `test_no_credit_history_is_neutral`.
- [ ] **Step 2: Write failing adapter tests** in `test_credit_sources_sqlite.py`: build a temp DB with `scripts.credit_sources.setup.create_database(tmp_path/"cs.db", empty=True)` and insert rows directly. Tests: `test_monthly_salary_sums_latest_month`, `test_future_history_ignored`, `test_unbound_customer_not_found`, `test_bound_cnp_missing_not_found`, `test_missing_db_raises_tool_unavailable`, `test_no_products_found_empty`, `test_person_full_name_and_birth_date`.
- [ ] **Step 3:** Run `python -m pytest tests/unit/orchestrator/test_credit_check.py tests/unit/orchestrator/test_credit_sources_sqlite.py -q`. Expected: FAIL (modules missing).
- [ ] **Step 4:** Implement `models.py`, `sqlite.py`, `credit_check.py`; update `stubs.py` imports and the YAML loader for the new rule fields.
- [ ] **Step 5:** Run the two files plus `python -m pytest tests/unit/orchestrator -q`. Expected: new tests PASS; pre-existing tests unaffected.
- [ ] **Step 6:** Commit `agent(orchestrator): deterministic credit check over SQLite ANAF and bureau`.

---

### Task 3: Wire real tools into the orchestrator and retire `cust-00x` (after Tasks 1 and 2)

**Files:**
- Modify: `src/core/settings.py` (`credit_sources_db: Path = Path("data/local/credit_sources.db")`, `customer_bindings_path: Path = Path("config/orchestrator/customer_bindings.yaml")`; env `ORCHESTRATOR_CREDIT_SOURCES_DB`)
- Modify: `src/core/composition.py` (`build_registry(settings, stub_data, policy_search) -> ToolRegistry`: calls `build_stub_registry`, then re-registers `get_customer_profile` and `run_eligibility_check` with the same `ToolSpec` fields but real handlers)
- Create: `src/agent/tools/credit_check.py` (`make_profile_handler(sources)`, `make_eligibility_handler(sources, data: StubData)`)
- Modify: `config/orchestrator/customers.yaml` (keys = nine customer IDs; `stated` and `documents` values matching Task 1 data; Radu's chat/doc payslip income 6500 to show the gap)
- Modify: `tests/unit/orchestrator/*.py`, `tests/e2e/test_chat_scenarios.py`, `scripts/export_chat_contract.py`, `contracts/http/README.md`, `contracts/http/examples/chat/*` (regenerate via the export script)
- Test: `tests/integration/orchestrator/test_credit_check_demo_customers.py`

**Interfaces:**
- Consumes: `SqliteCreditSources`, `load_bindings`, `evaluate`, `EligibilityRule` (Task 2); bindings + DB (Task 1).
- Profile handler: `CustomerProfileOutput(customer_id, full_name, age=completed years from birth_date to as_of)`; unknown → `ValueError("unknown customer")`.
- Eligibility handler: reads `ctx.state.application.fields[*].value`, the product and rule from `StubData`, calls `sources.anaf/bureau`, returns `evaluate(...)`; sets `ctx.state.used_stubs = True`.

- [ ] **Step 1: Failing integration test** `test_credit_check_demo_customers.py`: session-scoped fixture builds the DB in a tmp dir with `create_database()`; parametrized over the nine customers with request 30,000 RON / 60 months on `personal_loan` and fields from `customers.yaml`; asserts statuses: alex/elena/radu `satisfied`, dan/andrei/ioana/victor `not_satisfied`, maria/mihai `manual_review`; Radu's reasons include `income_gap`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement settings, `build_registry`, handlers; `build_orchestrator` uses `build_registry`.
- [ ] **Step 4:** Replace `cust-001`→`cust-alex-morgan`, `cust-002`→`cust-andrei-stan`, `cust-003`→`cust-mihai-ilie` in tests/scripts/contracts; update expected names/values to the new `customers.yaml`. e2e `make_settings` sets `credit_sources_db` to a DB built once per session with `create_database()`. In `test_happy_path`, ANAF 8500 vs declared 7000 is fine (satisfied with `income_gap`).
- [ ] **Step 5:** Run `python -m pytest -q`. Expected: all pass.
- [ ] **Step 6:** Commit `agent(orchestrator): use SQLite credit sources for eligibility and profile`.

---

### Task 4: One sign-in per demo customer (parallel with Tasks 1–3)

**Files:**
- Modify: `packages/banking/src/demo-accounts.ts` — add `export interface DemoCustomerAccount { customerId: string; name: string; email: string; password: string; scenario: string; monthlyIncome: string }` and `export const DEMO_CUSTOMERS: DemoCustomerAccount[]` (nine entries; emails `<first>@example.test`, Alex keeps `alex@example.test`; password `ClientDemo123!` for all; scenario labels: "Eligible", "Eligible, no debt", "Eligible, existing loans", "Debt over 40%", "Income too low", "91 days late", "Open insolvency", "Restructured loan – review", "Self-employed – review"). Keep `DEMO_ACCOUNTS.customer` = Alex, `.reviewer` unchanged.
- Modify: `packages/banking/server/auth.ts` (customer login matches any `DEMO_CUSTOMERS` email; actor `{ id: customerId, name, role: "customer" }`)
- Modify: `packages/banking/src/seed.ts` (`CUSTOMER_ACTOR.id = "cust-alex-morgan"`; seed one customer record, empty message list and consents for each demo customer; loans/application/notification stay Alex-only)
- Modify: `packages/ui/src/session-gate.tsx` (optional `demoAccounts?: DemoCustomerAccount[]`; when present render a list "Name — scenario" whose buttons fill email/password)
- Modify: `apps/customer/src/components/customer-shell.tsx` (pass `DEMO_CUSTOMERS`)
- Modify: `packages/banking/src/orchestrator-state.ts` (remove `SYNTHETIC_CUSTOMERS`/`pickCustomer`; `isValidCustomerId(id) => /^cust-[a-z0-9-]+$/.test(id)`)
- Modify: `packages/banking/src/orchestrator-react.tsx` (use `lumaCustomerId` for the orchestrator client; ignore a stored session whose `customerId !== lumaCustomerId`)
- Modify: `packages/banking/test/*.test.ts`, `tests/e2e/frontend.spec.ts`

- [ ] **Step 1: Failing tests:** `auth.test.ts` — `each demo customer can sign in and gets its own actor id` (loop over `DEMO_CUSTOMERS`, `actor.id === customerId`); `orchestrator-state.test.ts` — replace `pickCustomer` tests with `isValidCustomerId("cust-dan-ionescu") === true`, `isValidCustomerId("../x") === false`.
- [ ] **Step 2:** Run `npm test --workspace packages/banking` (check `package.json` for the exact script). Expected: FAIL.
- [ ] **Step 3:** Implement the changes above.
- [ ] **Step 4:** Run the banking tests and `npm run build` for both apps. Expected: PASS / build succeeds.
- [ ] **Step 5:** Update `tests/e2e/frontend.spec.ts`: sign in as Alex and as Dan Ionescu; assert the chat session is created with `X-Customer-Id` equal to the signed-in customer ID (replace the pinned `cust-001`). Run Playwright if the stack is available; otherwise note it was not run.
- [ ] **Step 6:** Commit `agent(frontend): sign in as any demo credit customer`.
