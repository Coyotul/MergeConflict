# Synthetic ANAF / bureau / CRC database runbook

## Purpose and repository integration

This is an **offline fictional external-source fixture**, not the application,
assessment/audit database or a live bank adapter. It was imported on
`feature/credit-sources-db` from the separately validated database prototype,
against `main` revision `5e36e6a884f6b4b8aaf9487949e04feecc1283d9`.
The owner confirmed `main` as the integration target; the remote has no `master`.
Integration follows the repository's agent board and PR workflow.

Existing frontend and Python eligibility composition, security, HTTP/model
contracts, rules and storage are deliberately unchanged. The SQL view named
`v_dsti_inputs` is a **descriptive existing-debt ratio**, not a replacement for
the application's preliminary affordability calculation or a final decision.

## Files / sources of truth

Absolute examples below use the integration checkout. Python resolves paths
from the repository location, not the shell's working directory.

| Location | Meaning |
| --- | --- |
| `C:\Users\msi\Downloads\mergeconflict-integration\data\synthetic\credit_sources\credit_sources.sql` | Canonical empty schema: 17 tables, 12 views, indexes and singleton protection. Only the parameter row is inserted. |
| `C:\Users\msi\Downloads\mergeconflict-integration\data\synthetic\credit_sources\credit_sources_sample_data.sql` | Data-only SQL, loaded after schema into an empty target. |
| `C:\Users\msi\Downloads\mergeconflict-integration\data\synthetic\credit_sources\sample_data_manifest.json` | Seed, CNP/scenario mappings, sex metadata, product IDs and counts. |
| `C:\Users\msi\Downloads\mergeconflict-integration\data\synthetic\credit_sources\SAMPLE_DATA.md` | Guaranteed scenario catalogue and query examples. |
| `C:\Users\msi\Downloads\mergeconflict-integration\scripts\credit_sources` | Standard-library setup, generation and read-only verification commands. |
| `C:\Users\msi\Downloads\mergeconflict-integration\tests\credit_sources` | Original 67 tests plus 6 repository-setup/reproducibility tests. Writable fixtures use temporary databases. |
| `C:\Users\msi\Downloads\mergeconflict-integration\docs\reference\credit-sources-specification.md` | Original empty-schema specification, preserved verbatim. |
| `C:\Users\msi\Downloads\mergeconflict-integration\data\local\credit_sources.db` | Reconstructed runtime/demo SQLite file; intentionally ignored and NOT committed. |

The SQL and sample files were copied without changing their content. Binary
databases, local agent settings, tokens and backups from the original workspace
were not imported. Source fixtures are versioned; runtime database files are not.

## Create, verify and test

The database tools need only Python 3.11+ with SQLite >=3.35, no new dependencies.
Locally validated with Python 3.13.7 / SQLite 3.50.4; minimum SQLite 3.35.x runtime
execution is not yet verified.

```powershell
Set-Location 'C:\Users\msi\Downloads\mergeconflict-integration'
py -3 -B -m scripts.credit_sources.setup
py -3 -B -m scripts.credit_sources.verify_credit_sources --replay
py -3 -B -m unittest discover -s 'C:\Users\msi\Downloads\mergeconflict-integration\tests' -v
py -3 -B 'C:\Users\msi\Downloads\mergeconflict-integration\tests\credit_sources\test_credit_sources.py' --benchmark
```

`setup` reconstructs the default 323-person fixture in ignored local storage and
compares its rows against SQL replay. It refuses an existing file, including a
populated database: no `--force`, reset or overwrite option exists. Do not delete
an existing database just to rerun setup. To check it, use the verifier instead.

For a separate empty schema:

```powershell
py -3 -B -m scripts.credit_sources.setup --empty --database 'C:\Users\msi\Downloads\mergeconflict-integration\data\local\credit_sources_empty.db'
```

The empty schema has one `report_params` row with SQLite's UTC current date and
zero people/products. The saved sample loader instead fixes D to `2026-10-28`.
Tests preserve both contracts; the originally requested empty schema was not
changed into an unconditional sample-data script.

The verifier opens a database in read-only mode, never implicitly creates it,
checks all views/integrity/FKs/dataset policies, and with `--replay` compares all
rows and schema objects. It expects the default sample date; use a copy for time
travel instead of changing a shared runtime database underneath concurrent readers.

Alternative random fixtures (0-5,000 random people plus fixed cases):

```powershell
New-Item -ItemType Directory -Path 'C:\Users\msi\Downloads\mergeconflict-integration\data\local\credit_sources_variant_42'
py -3 -B -m scripts.credit_sources.generate_credit_sources --seed 42 --random-people 1000 --output-dir 'C:\Users\msi\Downloads\mergeconflict-integration\data\local\credit_sources_variant_42'
```

Output directories must exist; existing output files are never overwritten. The
generator validates in memory, exports explicit-column inserts in FK order, and
replays the export into a second database before saving. An optional `--load`
accepts only an existing empty target with matching schema, creates a backup,
validates before commit and verifies again after reopening. Manual SQL clients
must stop at the first error and roll back failed imports. The sample export is
not an incremental importer or a production migration.

## Dataset and covered scenarios

Seed **20261028**, D **2026-10-28**: **73 guaranteed labelled cases + 250 random
people**, **422 products**, **10,615 monthly history rows**, **597 annual income
records**, **5,866 monthly salary declarations**, **378 inquiries**, **257 scores**.
All 16 data tables are populated and every view returns data at the default date.

Cases cover no history/debt, zero/missing/old income, 39.0% and >100% DSTI,
multiple sources/jobs/loans, debtor/co-debtor/guarantor combinations, all delay
categories, inclusive retention boundaries, 19,999.99/20,000/20,000.01 CRC
thresholds, foreign currencies, future records/time travel, leap-month and year
rollovers, missing/partial history, events, insolvency and fraud. Invalid dates,
duplicates, invalid CNP syntax/scores, orphan rows and unsafe deletes stay in
rejection tests, not in the data. Missing and future rows are intentional cases.

All identities/organizations/addresses are fictional, labelled FICTIV; phones
are NULL. CNPs are 13 ASCII digits with fictional birth-date/sex/century metadata,
but **deliberately invalid checksums**. Never use them for real provider calls.
Monthly and annual salary totals reconcile. Other histories are prototype
scenarios, not a legally accurate or production fixed-point accounting ledger.

## Database rules and known limitations

- CNP links sources; products are stored once. Bureau and CRC agree when using
  the same history month, but normally reference different snapshots.
- Bureau takes latest history on/before D; CRC takes exactly the previous month
  and exposes its last day as snapshot date. CRC never substitutes older history.
- Retention boundaries are inclusive SQLite calendar arithmetic (including its
  month-end overflow behavior). Monthly periods are first-of-month ISO dates.
- Payment amounts are **RON equivalents**. Original currency and granted RON
  equivalent are separate. CRC uses the latter, not outstanding balance.
- Guarantees appear in product views but not debt totals. Co-debtors receive the
  full obligation. Assigned/written-off/insolvency products not closed are still
  obligations under the prototype policy.
- Missing history leaves null product figures but zero/partial summary totals.
  **Zero is not verified debt-free evidence.** Completeness/freshness must be
  assessed separately; no completeness flag was added in this import.
- `report_params` is one global reference date, not a per-request parameter.
  Use separate snapshots/copies for concurrent reports at different dates.
- REAL money is prototype storage. Dates/syntax/enums/finite amounts are checked;
  REAL aggregate overflow on unrealistically huge finite values remains possible.
- Future closure visibility is handled; all past rate/participant/non-closure
  status changes cannot be reconstructed because those attributes are not versioned.
- Shared quality checks are dataset policies, not universal banking constraints:
  one DEBTOR after complete load, monthly lifetime/job overlap, positive overdue
  money for delinquency, selected fixed-rate RON amortizer balance checks, and
  source fiscal-code/CNP metadata consistency. Revolving drawdowns and FX changes
  are not universally invalid balance increases.
- Enable `PRAGMA foreign_keys = ON` for each writable SQLite connection. Use
  bound query parameters and read-only connections for consumers where possible.

## Required adapter work before wiring eligibility

The existing application's Pydantic/Decimal contracts are intentionally stricter
and different. Do not directly pass these SQL row dictionaries into
`VerificationResult`, replace synthetic providers automatically, or treat the
fixture as verified applicant evidence.

1. Map authorized `customer_id` to a synthetic CNP server-side. Keep owner/role,
   notice/consent/legal-basis checks in the application, not this external store.
2. Convert monetary outputs via explicit decimal strings/rounding rules; existing
   Money fields reject Python floats. Never relabel RON payment figures as EUR.
3. Resolve unsupported CHF explicitly: existing debt contracts accept RON/EUR/USD,
   while this fixture includes CHF. Preserve review-required/unsupported outcomes.
4. Supply canonical liability IDs and deduplicate loans across internal/bureau
   evidence. Guarantees and co-debtors need deliberate mapping.
5. Populate `complete`, evidence timestamps/IDs, source versions, verified status,
   recurring-income/period semantics and report availability. Annual average
   income is not automatically current verified recurring salary.
6. Do not invent enforcement, repeated-delay, dispute or official FICO approval
   rules from this fixture. Missing information must not be mapped to `False`.
7. Existing affordability includes new-loan pricing and at least 3% of unused
   revolving limits. `v_dsti_inputs` only divides existing recorded instalments by
   annual average income; it is not the same eligibility measure.
8. A displayed historical HARD inquiry is not authorization to perform a new
   score-affecting inquiry. Existing provider calls remain preliminary synthetic
   stubs. Every new application still requires explicit submission and human review.

## Regression environment / pre-existing dependency drift

The original `main` baseline allowed FastAPI 0.162.0/Pydantic 2.14.1 via broad
requirement ranges. A clean install with these versions failed the existing
OpenAPI parity test before database integration: FastAPI adds `ctx` and `input`
properties to ValidationError. No application schema/contract was regenerated
to hide this. Reference regression versions within the existing declared ranges:
**FastAPI 0.115.12, Pydantic 2.11.10, Uvicorn 0.34.0** (Starlette 0.46.2).

To reproduce backend contract parity in an isolated test environment:

```powershell
Set-Location 'C:\Users\msi\Downloads\mergeconflict-integration'
py -3 -m venv 'C:\Users\msi\Downloads\mergeconflict-integration\.venv'
& 'C:\Users\msi\Downloads\mergeconflict-integration\.venv\Scripts\python.exe' -m pip install -r 'C:\Users\msi\Downloads\mergeconflict-integration\requirements.txt' 'fastapi==0.115.12' 'pydantic==2.11.10' 'uvicorn==0.34.0'
& 'C:\Users\msi\Downloads\mergeconflict-integration\.venv\Scripts\python.exe' -B -m unittest discover -s tests -v
& 'C:\Users\msi\Downloads\mergeconflict-integration\.venv\Scripts\python.exe' -B -m scripts.export_eligibility_contracts --check
& 'C:\Users\msi\Downloads\mergeconflict-integration\.venv\Scripts\python.exe' -B -m scripts.eligibility_smoke
```

Dependency locking/upgrading the existing service is a separate follow-up. This
fixture import changes no requirement ranges, frontend dependency lockfile or
generated eligibility contract. Frontend validation remains `npm run check`,
`npm run build` and `npm run test:e2e`, using the existing lockfile and test stores.

Database benchmarks use 3,000 random people, 6,000 products and 204,000 monthly
rows in memory with a warm cache, reporting median/p95 and full-report timings.
They are not cold-disk/concurrency/production latency guarantees. An optional
`CREDIT_SOURCES_MAX_P95_MS` budget is machine-specific.

## Validated integration snapshot (2026-10-28)

- **183 Python tests pass with benchmark enabled**: 110 existing eligibility tests
  plus 73 database/fixture/setup tests. Normal discovery skips just the benchmark.
- Existing OpenAPI/JSON-schema/tool artifacts match executable definitions with
  the reference backend versions above; seven live loopback HTTP checks pass.
- `npm run check` passes ESLint, TypeScript and **16 Node/domain/API tests**;
  `npm run build` builds both Next.js apps; **7 Playwright journeys** pass.
- Default local database reconstruction and read-only full replay validation pass.
  Schema, sample SQL, metadata, catalogue and original specification are byte-identical
  to the validated standalone sources. Existing backend/frontend/configuration,
  model contracts, dependency files and pre-existing tests have no content changes.
- Publishable files passed a limited common AWS/GitHub/private-key pattern scan;
  source credentials, binary databases, backup files and generated build changes
  are excluded. This is not a comprehensive production security audit.

These results validate this isolated fixture import, not an unimplemented
provider/frontend adapter or all future versions allowed by broad requirements.
The feature is integrated through a PR; use Git/PR state as the source of truth
for the actual main merge revision.