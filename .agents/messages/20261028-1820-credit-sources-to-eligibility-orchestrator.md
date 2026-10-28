# Handoff: external credit-source fixtures to eligibility and orchestration

- **From:** Cline / credit-sources
- **To:** Eligibility, integration, orchestration, frontend and maintainers
- **Task:** CREDIT-SOURCES-01
- **Branch:** feature/credit-sources-db; owner confirmed actual target main (no master exists).
- **Base:** 5e36e6a884f6b4b8aaf9487949e04feecc1283d9; published task claim 9b551b7.
- **Status:** implementation validated; integrate through feature PR, not direct main push.

## What is available

Versioned schema-only SQL and reproducible fictional data at
`C:\Users\msi\Downloads\mergeconflict-integration\data\synthetic\credit_sources`;
stdlib setup/generator/validator under
`C:\Users\msi\Downloads\mergeconflict-integration\scripts\credit_sources`;
73 SQL/fixture/setup tests under
`C:\Users\msi\Downloads\mergeconflict-integration\tests\credit_sources`.

17 tables / 12 reporting views, 323 fictional people (73 fixed scenarios plus
250 random), 422 products, 10,615 history rows, seed 20261028 and default D 2026-10-28.
Includes empty/no-history/partial/future/date-boundary cases and the known 39.0%
descriptive DSTI example. Synthetic CNPs intentionally fail checksum validation.

Run `py -3 -B -m scripts.credit_sources.setup` from the repository root to recreate
the ignored local database. Use `--empty` with a separate absolute output path for
schema only. Setup never overwrites. Verify with
`py -3 -B -m scripts.credit_sources.verify_credit_sources --replay`.
No binary database, credential, local settings or backup file is committed.

## Do not assume provider integration exists

Existing `EligibilityService`, provider composition, auth, workflow, frontend,
Decimal affordability, HTTP contracts and assessment/audit persistence are unchanged.
This is a fixture source, not trusted application evidence or an approval engine.

Before adding an adapter:

1. Bind authorized server-owned customer IDs to fixture CNPs; keep consent/legal
   basis/notices/roles outside this external-source schema.
2. Use deliberate Decimal serialization of RON figures, not raw floats. Original
   product currency is separate; CHF is not currently accepted by the app's debt model.
3. Populate completeness/provenance/freshness/verified evidence. Missing history
   creates zero/partial summary totals, which must not be declared clean evidence.
4. Map canonical liability IDs across internal/bureau sources, debtor/co-debtor and
   guarantee roles. Do not double-count or split co-debtor obligations silently.
5. Preserve existing new-loan and revolving-limit calculations: SQL DSTI describes
   only recorded existing instalments, not the application's full affordability rule.
6. Do not infer enforcement, repeated-delay flags, FICO cutoffs or dispute status
   from incomplete source fields. Do not treat a historical HARD inquiry as consent
   for a new inquiry. Current provider ports remain preliminary/offline only.
7. Isolate the global as-of date across concurrent requests. No automatic per-request
   mutation, real bank calls, application submissions, final decisions or payments.

Full constraints and reference commands:
`C:\Users\msi\Downloads\mergeconflict-integration\docs\runbooks\credit-sources.md`.
Architecture decision:
`C:\Users\msi\Downloads\mergeconflict-integration\docs\decisions\006-credit-sources-fixtures.md`.

## Validation / dependency follow-up

183 Python tests including benchmark pass, along with existing generated-contract
parity, 7 live HTTP checks, 16 Node/API tests, 7 Playwright tests and both frontend
builds. SQL/sample/manifest/source-spec content was preserved byte-for-byte.

Fresh baseline installation exposed existing dependency drift: FastAPI 0.162 adds
ValidationError fields to generated OpenAPI. Reference regression versions are
FastAPI 0.115.12, Pydantic 2.11.10, Uvicorn 0.34.0; these are within existing
requirements. No lockfile, requirement range or generated contract was changed to
hide the failure. **Maintainer follow-up:** lock/review backend dependency upgrades
in a separate change. SQLite 3.35.x runtime compatibility is still untested here.