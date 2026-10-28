# Loan pricing simulator -> orchestrator integration

## Provenance and scope

- Engine implementation: **13b4cf25fe7ea4c606730184e5f799efdca2dc72**,
  `agent(pricing): implement deterministic loan pricing and simulation engine`.
- Additional scenario tests/runner: **b7ee96d**.
- Engine already merged into main by **53c95c2**; no cherry-pick needed.
- This integration starts at **c7cea73f00e2c8a7d031eb29224b278c13ae6fab** on local
  **feature/orchestrator-pricing**, task ORCH-PRICING-02. No push/merge is part of
  this task unless separately authorized.

The existing registered `calculate_loan_offer` tool now calls the deterministic
service instead of the zero-fee, one-rate annuity stub. Both mock and Featherless
orchestrators use the same registration/composition. The engine mathematics,
product JSON, IRCC rules, separate eligibility implementation, document pipeline,
database fixtures, frontend source and HTTP wire schema are unchanged.

Current checkout paths (adjust to your checkout; runtime code resolves paths):

- `C:\Users\msi\Downloads\mergeconflict-integration\src\agent\tools\pricing.py`:
  session-to-service and service-to-offer adapter.
- `C:\Users\msi\Downloads\mergeconflict-integration\src\agent\tools\stubs.py`:
  existing registry factory now registers deterministic pricing and exposes
  pricing-service catalog limits/rates; other synthetic tools remain stubs.
- `C:\Users\msi\Downloads\mergeconflict-integration\src\services\pricing\service.py`:
  authoritative existing calculation implementation (unchanged).
- `C:\Users\msi\Downloads\mergeconflict-integration\tests\unit\orchestrator\test_pricing_adapter.py`
  and `C:\Users\msi\Downloads\mergeconflict-integration\tests\integration\orchestrator\test_pricing_integration.py`:
  engine parity, trust boundaries, typed errors, session state and HTTP workflow tests.

## Product and input mapping

| Orchestrator product code | Pricing product ID |
| --- | --- |
| personal_loan | personal_loan_fixed |
| refinancing_unsecured | refinancing_fixed |
| mortgage_casa_ta | mortgage_fixed_then_ircc |

The model can supply only `term_options_months`: at most three strict integers
between 6 and 360. Unknown arguments are rejected, including attempts to inject
amount, income, customer/product ID, base rate, salary discount, insurance or date.
All other inputs come from the owned session. `ToolContext.now`, converted to UTC,
provides an explicit simulation date, not the LLM or the module's wall clock.

The registry keeps current/satisfied eligibility and verified-input prerequisites,
also checks document verification/conflicts, and blocks submitted/escalated cases.
The existing chat API enforces session ownership; this does not turn its demo
X-Customer-Id header into production authentication.

Defaults are explicit: annuity, no salary-account discount, no optional insurance,
no first-home uplift, engine minimum base rate if no risk-based rate is available.
Income does not prove a salary account; insurance is never elected by inference.
Property value is supplied only for the mortgage. Missing positive income or
obligations means the simulation affordability check is omitted, not a false pass.

The customer's primary amount/term is never clamped. Pricing returns its actual
limit error if that request is invalid. Optional terms are deduplicated in order,
up to three scenarios including the primary one; invalid alternatives are reported
and disclosed alongside any valid offers. Product discovery now uses the engine's
limits, avoiding the old personal-loan catalog's 6-84 month range when the engine
supports 18-60. Mortgage's default fixed period must be shorter than its total term.

## Output mapping and customer disclosures

The existing API `LoanOffer` shape is preserved, so Luma's offer blocks and
confirmation summary continue to work without a frontend protocol change.

| Orchestrator field | Service value |
| --- | --- |
| amount | Total credit requested, including financed costs; **not** net payout |
| annual_interest_rate_percent | First nominal rate period |
| monthly_installment | First scheduled total payment, including recurring charges |
| total_repayment | totals.total_payable (including separate upfront fees) |
| total_cost | totals.total_cost_of_credit (relative to net payout) |
| fees | Sum of upfront fees/premiums and recurring charges over the term |

No instalment, DAE, interest or repayment total is recomputed by the orchestrator.
Money remains Decimal and serializes as decimal strings. Fee aggregation is a
projection of engine line items; those costs are already in the totals and must
not be added again.

The already-rendered `assumptions` list carries the **exact** engine assumptions,
warnings/disclaimer, DAE/APR, net payout, financed/separate fee details, total
recurring charges, product version/date and post-fixed-period mortgage payment.
`DAE_INCOMPLETE` is retained, never marketed as a full bank-comparable mortgage APR.
The simulation's first-payment affordability result is explicitly not an
eligibility decision or future-rate stress test. Disclosures persist in session
JSON, model context, offer blocks and the selected offer's confirmation summary.
Mock replies also include deduplicated disclosures; the model prompt requires
their presentation and forbids inventing figures or accepting injected rates.

With D=2026-10-28, personal loan 30,000 RON/60 months, no inferred discounts or
optional insurance:

- base nominal rate 8.55%; monthly payment **621.22 RON**;
- net payout **29,800.00 RON**; DAE **9.58%**;
- total repayment **37,273.16 RON**; total cost **7,473.16 RON**;
- fees/charges **500.00 RON** (200 financed analysis fee + 300 recurring charges).

Mortgage 350,900 RON/300 months initially returns **2,155.79 RON**, later
**2,713.05 RON** under the explicit unchanged-IRCC assumption. No claim of official
bank approval or binding pricing is made.

## Error and stale-result behavior

The internal tool output adds `status`/typed `errors`; chat HTTP response schemas
are unchanged. Invalid primary scenarios create **no selectable offers**. A failed
or unavailable recalculation clears pre-submission offers, selection and summary;
no empty offer list or old quote remains ready for confirmation. Already-submitted
records are not altered.

Offer IDs include session-input fingerprint and actual pricing result/date/product
version, rather than only a short field hash. Recalculation under changed pricing
requires a new selection and summary confirmation. Repeating identical inputs,
configuration and date is deterministic. Stored quotes are historical snapshots;
this change does not introduce automatic quote expiry/repricing at submission.

Missing IRCC returns `INDEX_UNAVAILABLE`, never a guessed variable rate. Missing
configuration becomes `tool_unavailable`, with no illustrative fallback. The
model must ask for corrected inputs or human help, not approve or silently choose
a different term. Explicit UI submission and `PENDING_HUMAN_REVIEW` remain unchanged.

## Deliberately not exposed yet

`simulate_early_repayment` and `compare_refinancing_options` exist in the pricing
service but are **not registered for this new-application flow**. The orchestrator
does not collect an authorized existing loan, repayment month, outstanding balance,
settlement fees or comparison portfolio. Do not fabricate those from application
amount/income. A separate servicing/refinancing flow with those contracts is needed.
The refinancing product mapping here prices a new refinancing loan; it does not
claim to consolidate or repay any existing debts.

The legacy `run_eligibility_check` remains its synthetic preliminary stub and the
independent EligibilityService is not replaced. The pricing affordability result
does not authorize underwriting, signing or settlement. New customer elections
(insurance, salary account, repayment method) need explicit collection/confirmation
and offer invalidation before being exposed as tool options.

## Reproducible tests / generated contract examples

Use the repository's existing dependencies; no new package was added to requirements.
In PowerShell, with the integration environment:

```powershell
Set-Location 'C:\Users\msi\Downloads\mergeconflict-integration'
& 'C:\Users\msi\Downloads\mergeconflict-integration\.venv\Scripts\python.exe' -B -m pytest tests/unit/orchestrator tests/unit/services/pricing tests/unit/services/financial_calculations tests/unit/rules/pricing tests/integration/orchestrator/test_chat_api.py tests/integration/orchestrator/test_cors.py tests/integration/orchestrator/test_pricing_integration.py tests/e2e/test_chat_scenarios.py tests/contract/test_chat_contract.py -q
npm run check
```

The contract exporter now freezes the **execution clock before calculating**,
not just timestamps after calculation. Three quote/confirmation/submission example
JSON files are refreshed; the HTTP OpenAPI content remains unchanged. No real LLM
calls, banking requests or non-test database resets are needed for validation.

Environment note: current main's chat OpenAPI includes newer FastAPI ValidationError
fields. FastAPI 0.115.12 from the previous integration environment fails the two
existing chat-contract tests before this change; FastAPI 0.162.0 (within existing
requirements), Pydantic 2.11.10 and Uvicorn 0.34.0 reproduce the current chat contract.
No HTTP schema or dependency file was modified to conceal version drift. External
Featherless/PostgreSQL/RAG integration tests need their own services and are separate
from the offline pricing connection.

## Validation result (2026-10-29)

- **435 focused Python tests passed** covering pricing math/rules, adapter,
  registry/orchestrator, HTTP ownership, selection/confirmation, chat journeys,
  disclosures, fixed-date contract reproduction and existing orchestrator tests.
  This adds 42 parameterized/test cases over the corresponding main baseline.
- **63 frontend Node/API tests**, TypeScript/ESLint and both production Next.js
  builds passed. Existing ESLint unused-import warnings remain outside this change.
- **9 Playwright journeys passed**, including a new full pricing integration test:
  real mock-mode API -> engine offer -> rendered DAE/net payout/fees/disclaimer ->
  explicit selection -> separate submission confirmation -> human review only.
- Original pricing scenario runner passed all known examples. HTTP OpenAPI,
  pricing engine/config, database fixtures and frontend implementation are unchanged;
  only three generated chat example JSON files change with the real pricing values.
- Broader offline pytest run with the existing database benchmark enabled:
  **670 passed, 2 failed, 420 subtests passed**. Both failures reproduce unchanged
  on detached main `c7cea73` using the same environment and local fixture DB:
  - `tests/unit/test_document_generation.py::DocumentGenerationTests::test_load_profile_from_db_dsti_39`
    expects `Dan` but the existing local database contains `Mihai`.
  - `tests/unit/test_document_processing_pipeline.py::DocumentProcessingPipelineTests::test_e2e_full_dossier_processing_and_cross_validation`
    rejects the bank-statement validation in this Windows OCR environment.
- Installing the already-declared Windows `winocr` dependency resolved four other
  environment-only document failures. No document code, synthetic source data,
  unrelated tests or local database rows were altered to mask remaining failures.
- The current ignored local credit database predates main's latest fixture names;
  read-only `--replay` detects differing person rows. This is independent of pricing.
  Use a new temporary reconstruction for source-export validation; never reset a
  user's existing database to force parity.
- External PostgreSQL/RAG integration and live Featherless tests were not run.
  No external model API key or real financial service was used.

Changes are local on `feature/orchestrator-pricing`, with a local commit for review.
No branch publication, PR, merge or push was requested or performed for this task.