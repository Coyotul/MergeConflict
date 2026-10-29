# Orchestrator eligibility with SQLite-backed ANAF and Biroul de Credit

Date: 2026-10-29. Status: draft for owner review.

## Intent

The orchestrator's `run_eligibility_check` tool is a stub
(`src/agent/tools/stubs.py`, `handle_eligibility`) that checks a few YAML limits
against chat fields. The owner wants eligibility rebuilt as a step of the
orchestrator flow:

1. read the fields the product requires from the session state;
2. fetch additional details from mock external APIs for ANAF (tax-declared
   income, employment) and Biroul de Credit (existing loans, payment history,
   insolvency, fraud, score);
3. decide with deterministic rules, never the LLM, whether the customer is
   eligible for the requested amount and term.

The mock APIs read the existing credit-source SQLite dataset
(`data/synthetic/credit_sources/`, 323 fictional people), so the demo can show
many customers in different situations. Each demo customer can sign in to the
customer app with their own account.

## Goals

- `run_eligibility_check` returns a real deterministic decision built from
  session fields plus ANAF and bureau data.
- Chat customers are people in the credit-source database; their profile comes
  from the `persons` table.
- The customer app offers nine demo sign-ins, each landing in a different
  eligibility outcome.
- Every reason in the result has a code and a plain-language message, including
  the gap between declared and ANAF income.

## Non-goals

- The existing `EligibilityService` stack (`src/services/eligibility/`,
  `src/rules/eligibility/engine.py`, `src/core/eligibility_demo.py`, the
  eligibility HTTP API) is left untouched. It keeps serving its own demo API; the
  orchestrator no longer depends on it in any way.
- No real document processing, pricing, workflow or human-review wiring. Those
  stubs stay (other branches own them).
- No change to the staff/reviewer app.
- No HTTP mock servers; "mock API" means an in-process adapter behind an
  interface.

## Anti-goals

- The LLM must not compute or override any part of the decision.
- A missing or unavailable bureau/ANAF answer must never be read as a clean
  record.
- Customer identity (customer ID to CNP) must never come from the model or a
  request body; it is trusted server configuration.

## Constraints

- The credit-source database is built locally by
  `scripts/credit_sources/setup.py` into ignored `data/local/credit_sources.db`.
  When it is missing, the tools report `tool_unavailable`; they do not fall back
  to fake data.
- The dataset is evaluated as of its `report_params.as_of_date`
  (default 2026-10-28). Time windows such as "last 12 months" are relative to
  that date, not the wall clock.
- SQLite stores money as REAL; convert to `Decimal` at the adapter boundary and
  quantize to 0.01.
- Orchestrator tool handlers are synchronous (`ToolSpec.handler`). The new
  adapters are synchronous; no `asyncio` bridging.
- `feature/orchestrator-eligibility-anaf` also rewrites the eligibility stub.
  This design supersedes that branch's `orchestrator_bridge.py`; expect a merge
  conflict in `stubs.py` and resolve in favour of this work.

## Approaches considered

- **A. Mock APIs over the credit-source SQLite dataset (chosen by the owner).**
  Realistic data and many people; requires building the database locally and
  linking chat customers to CNPs.
- **B. Small YAML mock data keyed by `cust-00x`.** Fastest and fully
  deterministic, but only a handful of hand-made customers. Rejected: the owner
  wants the database's people and more customers.
- **C. Mock HTTP services.** Feels most like real APIs, but adds processes,
  ports and timeouts for no extra demo value. Rejected.

## Design

### Customer identity

- New config `config/orchestrator/customer_bindings.yaml` maps a customer ID to
  a CNP and its `persona_tag`. Only bound customers can use the eligibility
  flow; an unbound customer ID gets `not_found` from both APIs, which the rules
  turn into `more_information_required`.
- Customer IDs are readable slugs, the same string in the TypeScript demo server
  and the orchestrator (for example `cust-alex-morgan`). Exact slugs are the
  builder's call.
- `get_customer_profile` reads name and birth date (age computed as of the
  dataset date) from `persons` through the binding, instead of
  `customers.yaml`.
- `cust-001`, `cust-002` and `cust-003` are retired everywhere: config, the
  frontend's `SYNTHETIC_CUSTOMERS`/`pickCustomer`, the scripted
  `DemoChatModel`, unit/e2e tests and `contracts/http` examples.

### Demo customers

The owner asked that every demo customer has ANAF records, so the demo can be
tested end to end. The existing labelled personas (`NO_HISTORY`, `DELAY_091`,
…) are credit-source test fixtures whose missing ANAF data is asserted on
purpose (`validate_fixture`, `tests/credit_sources/`), so they are **not**
modified. Instead, nine new demo people are added to the dataset, each with a
`DEMO_*` persona tag, a fixed fictional name and complete ANAF records:
an employment row, monthly salary declarations covering at least the 12 months
before the dataset date, and the matching `income_records` rows. Each then gets
the bureau situation its scenario needs.

| Sign-in | Persona tag | ANAF net monthly | Bureau situation | Expected outcome |
|---|---|---|---|---|
| Alex Morgan | `DEMO_ALEX_MORGAN` | 8,500 | none | `satisfied` |
| Elena Popa | `DEMO_ELENA_POPA` | 4,500 | none | `satisfied` |
| Radu Mihai | `DEMO_RADU_MIHAI` | 5,000 (two employers) | two current loans, 300/month | `satisfied`, loans counted |
| Dan Ionescu | `DEMO_DAN_IONESCU` | 5,996.25 | current loan 2,340/month | `not_satisfied`: debt over 40% |
| Andrei Stan | `DEMO_ANDREI_STAN` | 2,300 | none | `not_satisfied`: income below 2,500 |
| Ioana Marin | `DEMO_LATE_91` | 6,000 | loan currently 91 days past due | `not_satisfied` |
| Victor Dobre | `DEMO_INSOLVENCY` | 5,500 | open insolvency | `not_satisfied` |
| Maria Stoica | `DEMO_RESTRUCTURED` | 6,500 | restructuring event 2 months ago, current | `manual_review` |
| Mihai Ilie | `DEMO_SELF_EMPLOYED` | 7,000 from PFA activity (no salary) | none | `manual_review` |

Names for the last four are fictional placeholders (designer's call). Expected
outcomes assume the test request pinned per customer (for example 30,000 RON
over 60 months; for Dan, a request that takes his debt over 40%).

Generator changes (`scripts/credit_sources/generate_credit_sources.py`):

- a `demo_cases()` step that runs **after** `random_cases()`, so existing
  CNPs and the seeded random people do not shift;
- `person()` accepts explicit first/last name (and birth date) for demo people;
  CNPs are generated the usual way (deliberately invalid checksum), so Alex's
  document-index CNP `1920515410012` is replaced;
- demo people are listed in the manifest and `SAMPLE_DATA.md` like curated
  cases; generated SQL and manifest are regenerated; credit-source tests are
  updated for the new row counts (existing persona assertions unchanged);
- `scripts/generate_documents.py --cnp` regenerates the ID, income certificate
  and bank statement PDFs for all nine from the database, replacing the five
  existing folders in `data/synthetic/documents/` and updating `INDEX.md`.

`scripts/credit_sources/setup.py` builds `data/local/credit_sources.db` with
these people; the runbook notes it must be run before the demo and the
integration tests.

### Mock external APIs

Two interfaces, owned by the orchestrator tools layer, with SQLite
implementations under `src/integrations/`:

- `AnafClient.lookup(customer_id) -> AnafReport`: status
  (`found` / `not_found` / `unavailable`), verified net monthly income (recurring
  monthly salary when available, otherwise the latest-year annual average, with
  its basis), income kinds (salary, PFA/independent activity, pension, rental),
  current employment start date and contract type.
- `CreditBureauClient.lookup(customer_id) -> BureauReport`: status, active
  products where the person is debtor or co-debtor (guarantees excluded) with
  monthly instalment, current worst days past due, worst days past due in the
  last 12 months, written-off or assigned debts, open insolvency, credit events
  (restructuring, payment suspension, …) in the last 12 months, card-fraud
  records, latest score or `NO_SCORE`.

Reports are Pydantic models with `Decimal` money and `simulated=True`.
Implementations read the database read-only (`mode=ro`, as
`src/integrations/anaf/sqlite.py` does) and prefer the existing views
(`v_anaf_income`, `v_bureau_products`, `v_bureau_events`,
`v_bureau_latest_score`, `v_bureau_insolvency`, `v_dsti_inputs`). The builder may
reuse query logic from `SqliteAnafProvider`, but the orchestrator must not
depend on `src/models/eligibility.py` types.

A SQLite error or missing file raises `ToolUnavailable`. `not_found` means
the bound CNP is not in `persons`. A known person with no bureau rows is
`found` with an empty report ("no credit history"), and a `NO_SCORE` score is
reported as such; both are neutral for the rules.

### Eligibility rules

A pure function in a new module
(`evaluate(fields, product, rule, anaf, bureau) -> EligibilityResult`) with no
I/O. Limits come from `config/orchestrator/eligibility.yaml`; new bureau
thresholds are added there per product. `rule_version` is bumped.

Inputs from the session: `amount`, `term_months`, `age`, `employment_type`,
`employment_months`, `monthly_net_income`, `existing_monthly_obligations`.

Income and employment use ANAF figures when ANAF has them; declared values are
used only to explain the gap.

**`not_satisfied`:**
- amount or term outside the product's limits;
- age under 18, or over 70 at loan maturity;
- ANAF net monthly income below 2,500 RON;
- employment shorter than 3 months (ANAF employment start if present, else the
  declared months);
- debt-to-income above 40%: (new instalment + existing instalments) / ANAF
  income. Existing instalments = max(declared obligations, bureau total). The
  new instalment uses the product's indicative rate and the existing
  `annuity_installment`;
- bureau: currently 90 or more days past due, a written-off or assigned debt, or
  an open insolvency.

**`manual_review`:**
- self-employed (declared, or ANAF shows independent activity as the main
  income);
- bureau: 31–89 days past due at any point in the last 12 months, a
  restructuring or payment-suspension event in the last 12 months, a card-fraud
  record, or a score below 500;
- bureau: 90 or more days past due at any point in the last 12 months but
  current now;
- ANAF has no income record for the customer. The minimum-income and
  debt-to-income rules are then skipped (declared income never drives a
  decision); all other rules still run. Message: the income could not be
  verified with ANAF and an advisor will check the documents.

**`more_information_required`:**
- a required session field is missing (listed in `missing_fields`). This is the
  only trigger, so the existing loop in `progress.py` always has a field to ask
  for.

**Neutral (informational reason only):** no credit history, `NO_SCORE`.

**Precedence:** `not_satisfied` > `manual_review` >
`more_information_required` > `satisfied`. All triggered reasons are returned,
not just the winning one.

Always-on informational reasons: declared vs ANAF income gap (when declared
income differs by more than 10%), computed debt-to-income, bureau obligations
counted.

ANAF or bureau unavailable: the tool fails with `tool_unavailable`; no partial
decision.

### Orchestrator wiring

- `build_stub_registry` keeps its other stubs; `run_eligibility_check` gets the
  real handler. Simplest shape: a new `build_registry` in `src/core/composition.py`
  that registers the stub tools and then overrides eligibility and profile with
  real handlers built from the clients. Builder's call.
- `OrchestratorSettings` gains `credit_sources_db` (default
  `data/local/credit_sources.db`) and the bindings path.
- The progress and gating logic in `src/agent/orchestration/progress.py` already
  handles all four statuses and stays unchanged.
- The eligibility tool output carries `simulated=True` and keeps
  `ctx.state.used_stubs` semantics (true, since the data is synthetic).
- The agent trace records the tool call as today; no new trace events.

### Documents stub

`process_document` still reads per-customer document values from
`config/orchestrator/customers.yaml`. That file is rewritten keyed by the nine
new customer IDs, with values matching the regenerated PDFs. At least one
customer (designer's call: Radu Mihai) declares in chat an income noticeably
higher than ANAF to show the gap message. The real
document-processing wiring is on `feature/orchestrator-document-tools` and will
replace this later.

### Customer app sign-in

- `DEMO_ACCOUNTS` becomes one reviewer plus a list of customer accounts (name,
  email, password, scenario label, customer ID).
- `SessionGate` shows the list; choosing one fills the form, like the current
  "Use demo account" button.
- `DemoSessions.create` matches the email among customer accounts and returns
  that customer's actor.
- The TypeScript seed creates each customer with basic dashboard data (name,
  initials, income from ANAF, fictional employer). Seeded loans, the seeded
  application and notifications stay Alex-only.
- `useOrchestratorChat` uses the signed-in customer's ID instead of
  `pickCustomer()`; `SYNTHETIC_CUSTOMERS` and `pickCustomer` are removed.

## Testing

- Unit tests for the rules function: every rule, its boundary (exactly 40%,
  exactly 90 days, 2,500 RON), precedence, and the income-gap message.
- Adapter tests against a small SQLite fixture built from the schema, plus one
  integration test per demo customer against the generated database asserting
  the expected outcome.
- Existing orchestrator unit/e2e tests migrated off `cust-00x`.
- Frontend tests for multi-account sign-in and that the chat uses the signed-in
  customer ID; Playwright e2e signs in as at least two customers.
- Credit-source tests updated for the added person.

## Decided by the owner

- Rebuild eligibility in the orchestrator; do not wire the old
  `EligibilityService`.
- ANAF figures win over declared values; the result explains the gap.
- The rule set above.
- Mock APIs read the credit-source SQLite dataset; chat customers are database
  people; `cust-00x` is retired.
- One sign-in per demo customer, with nine scenarios.
- Every demo customer has ANAF records in the database.

## Proposed by the designer, pending owner confirmation

- Known person with no bureau history, and `NO_SCORE`, are neutral.
- No ANAF income → `manual_review`, with income and debt-to-income rules
  skipped; `more_information_required` only for missing session fields.
- Cured 90+ days past due within 12 months → `manual_review`.
- New `DEMO_*` people instead of editing the labelled test personas.

## Left to the builder (marked as the designer's calls)

- Exact customer-ID slugs, module and file names.
- Whether ANAF reading reuses `SqliteAnafProvider` code or is written fresh.
- Exact SQL; which views to use.
- Per-customer test requests that pin each expected outcome, and swapping a
  persona if one doesn't produce its outcome.
- Branch: start a new branch from `feat/agent-trace` for this work.
