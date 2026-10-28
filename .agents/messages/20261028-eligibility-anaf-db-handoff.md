# Handoff: Eligibility Check ANAF SQLite adapter

Branch: `feature/eligibility-anaf-db`, based on `main` `411ad6d`.
Task: `ELIGIBILITY-ANAF-02`. No main push or merge is authorized for this task.

The owner's supplied SQL, sample SQL, manifest, catalogue and source tools/tests
remain unchanged. Only the previous eligibility implementation and its own
tests/contracts/runbook are adapted; frontend and `backend-routes` are untouched.

## Implemented boundary

- `src/integrations/anaf/sqlite.py`: `SqliteAnafProvider` implements the existing
  `VerificationProvider` contract and opens `data/local/credit_sources.db` read-only.
  One consistent source transaction, bound parameters, short SQLite timeout and
  cancellation/deadline handling; no SQL writes, resets or database creation.
- `config/rules/eligibility_anaf_bindings.json`: explicit server-side fictional
  customer/CNP bindings. `AnafIdentityBindings` can be injected for other trusted
  applications. No CNP, role, income or consent is added to the public request.
  Known fictional manifest identities only; response evidence IDs do not expose CNP.
- Monthly amounts come from the latest completed `monthly_salary_declarations`
  period, with employer/job coverage and consecutive-month recurrence checks.
  Sum using Decimal/cent rounding after all employers, not SQLite REAL totals.
- Annual-only data uses the latest completed year in `v_anaf_income`. It remains
  `ANNUAL_AVERAGE`, `recurring=false`, with fiscal-year/source-date metadata.
  `ANAF_HISTORICAL_INCOME_ONLY` requires review; it is never promoted to current
  verified salary. Existing policy separately checks monthly income freshness.
- `build_demo_service` now defaults to SQLite ANAF. Existing dictionary ANAF
  provider remains a test double only; no fallback when the database is absent.
  Bureau/internal-loan providers and financial rules are otherwise unchanged.

## Demo / operational contract

Reconstruct with `python -B -m scripts.credit_sources.setup` only when no local
database exists. Existing files are never overwritten; verify them with the
provided read-only `verify_credit_sources --replay` command instead.

Demo cases explicitly bind to `CALENDAR_TIME_TRAVEL`; at D=2026-10-28 it provides
September net salary 5,000.33 RON. These are cloned synthetic demo applications,
not distinct people or inferred mappings of frontend accounts. Current/future
salary rows are excluded. High-DTI varies requested principal, not ANAF data.

The normal API uses the supplied runtime database; demo/smoke/test harnesses
explicitly reconstruct temporary source files. All source queries are authorized
by the existing backend service first; missing consent prevents provider calls.
Missing data stays missing and unavailable DB returns an auditable review result.
Same retry key returns its saved historical result; use a new key for fresh data.

## Validation

- 210 Python tests pass, with only the existing optional benchmark skipped.
  Includes 27 new adapter tests and queries covering all 323 fixture people.
- Generated public OpenAPI/assessment/tool artifacts are unchanged and match the
  executable models. The new internal provider schema is
  `contracts/schemas/anaf-income-verification.schema.json`.
- Seven live HTTP smoke checks and all 16 unchanged Node/domain/API tests pass.
- Tests change salary in a temporary source copy and observe the assessment change.
  Concurrent reads preserve database hashes/report date; future/old/missing/zero/
  partial/multi-employer/overflow/corrupt-source cases do not silently pass.

Future backend callers should inject verified identity bindings/consent and
backend-owned application revisions. This task does not implement bureau/CRC SQL
adapters, production ANAF, public CNP lookup, or new final-decision authority.