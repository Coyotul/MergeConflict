# Handoff: Eligibility Check to orchestrator, workflow and frontend

- **From:** Cline / eligibility
- **To:** Orchestrator, document processing, pricing, workflow and frontend agents
- **Branch:** `feature/eligibility-check` (merge through reviewed PR, not direct master push)
- **Implementation commit:** `0ffe058`; concurrent frontend base preserved by `4bc9b39`.
- **Status:** synthetic preliminary eligibility branch implemented and independently validated.

## Capabilities and entry points

- `src/services/eligibility/service.py`: `EligibilityService.assess(request, actor)`;
  consumes trusted application snapshots, policies, verification ports and storage.
- `src/agent/tools/eligibility.py`: `run_eligibility_check` + `tool_definition()`.
  Only application/scenario IDs and an idempotency key are LLM/tool inputs.
  Inject the authenticated backend actor; no model-provided permissions/consent.
- `src/api/application/eligibility.py`: `eligibility_router(service, actor_dependency)`.
  The gateway dependency must resolve actual identity/permissions/assignment.
- `src/api/gateway/eligibility_demo.py`: loopback **synthetic** demo gateway only.
  Public demo keys are not production authentication or frontend session tokens.
- `contracts/http/eligibility.md`, generated OpenAPI and JSON schemas: actual wire
  contracts, statuses, retry semantics, evidence and policy provenance.
- `docs/runbooks/eligibility-demo.md`: commands, fixtures, recovery and limitations.
- `docs/research/eligibility-raiffeisen-ro.md`: verified sources vs demo assumptions.

## Required downstream work

1. Document processing must return **verified** evidence with IDs, source version,
   timestamp and identity expiry. OCR/extraction or FORMAT_ACCEPTED metadata alone
   is not verification. No applicant data should be supplied by the orchestrator.
2. Application/customer repositories must enforce ownership and supply immutable
   revisions, profile evidence and purpose-scoped notices/authorization. ANAF
   consent and bureau legal basis/notice are distinct backend records.
3. Pricing provides a server-owned indicative scenario: customer/application IDs,
   term, financed-principal breakdown, nominal annual interest and recurring costs.
   Financed fees/insurance are already in principal; do not double-add them.
4. Workflow owns states and explicit submission/human review. Eligibility returns
   a snapshot and never submits, approves, rejects, signs or disburses. Every
   submitted prototype application still requires an authorized human decision.
5. Frontend `Assessment` currently handles only two outcomes; add all four backend
   statuses, rule-level reasons, source URLs, assumptions and simulation flags.
   Replace the temporary Node assessment only through an authenticated backend
   integration. This branch does **not** wire or modify frontend code.
6. Production persistence needs PostgreSQL/cloud migrations and appropriate RLS,
   encryption, retention and access controls. The local SQLite adapter is solely
   a synthetic demonstration of atomic audit/snapshot/retry storage.
7. Real providers require reviewed contracts and a durable multi-worker inquiry
   reservation/outbox. SQLite uniqueness prevents duplicate saved outcomes, not
   exactly-once inquiries across workers. This branch only calls offline stubs.

## Verified checks

`python -m unittest discover -s tests` passes **110** unit/integration/contract/
demo-journey tests. `python -m scripts.eligibility_smoke` passes **seven** live
Uvicorn loopback checks. `python -m scripts.export_eligibility_contracts --check`
verifies artifacts against executable definitions. Money is Decimal/string-safe.

The demo distinguishes clean/absent/partial/unavailable bureau reports, has no
invented FICO cutoff, counts canonical duplicated loans once and includes at
least 3% of unused revolving limits. Policy conflicts, stale/mismatched evidence,
provider failures and unsupported products cannot silently pass. Configuration's
2,700 RON minimum net income is an explicit synthetic assumption, not bank policy.

The fixed reference clock is 2026-10-28. Normal API calls enforce current time;
demo policy expiry on 2026-11-26 and evidence staleness are intentional. A replay
key returns its original timestamp/outcome, not newly verified eligibility.