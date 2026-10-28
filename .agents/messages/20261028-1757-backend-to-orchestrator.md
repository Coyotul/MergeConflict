# Handoff: backend routes to orchestrator and frontend

- **From:** Cline / backend
- **To:** Orchestrator, frontend, workflow, profile/document/provider-consent agents
- **Branch:** `backend-routes`; merge through a reviewed PR, not a direct main push.
- **Base synchronization:** includes the owner-approved eligibility merge `5e36e6a`;
  merge commit `3fe45a7` preserved upstream rules/service/tool/tests and frontend.
- **Status:** functional local synthetic backend capabilities implemented and verified.

## Entry points

- Run `main.py` with the existing `.venv`; default loopback port 8000.
- Canonical base `/api/v1`; `/docs` and `/openapi.json` have stable operation IDs.
- `src/api/application/tool_contracts.py` identifies the fourteen proposed customer
  capabilities using `x-orchestrator-tool`, roles and consequential-operation gates.
- `contracts/http/backend-v1.md`: input/output, authorization, state transitions,
  distinct replay semantics and intentional limitations.
- `docs/runbooks/backend.md`: public synthetic sign-in, commands, testing and recovery.
- `docs/decisions/009-backend-api.md`: composition, local SQLite and next deployment work.

## Required orchestration integration

1. Forward a **verified customer session**; never allow LLM-selected principals,
   staff tokens, database access, arbitrary interest/fees, state or evidence.
2. Register the scoped customer tool allowlist only. Staff review/notes are explicitly
   `x-orchestrator-tool: false`. Every credit application needs an assigned human.
3. Save a draft with server pricing. For `run_eligibility_check`, send only
   `applicationId`, optional saved `pricingScenarioId`, and a UUID `idempotencyKey`.
   This calls the original evidence-based EligibilityService, not a duplicate rule.
4. Eligibility response deliberately retains its original **snake_case** schema:
   all four statuses, rule reasons, policy digest/effective dates, evidence and
   sources, simulated/final-decision/human-review flags. Do not convert a missing
   report or manual-review outcome into approval; its DTI ratio is a fraction.
5. The workflow bridge has no verified birth/employment/profile/identity evidence or
   purpose-scoped ANAF/bureau/internal-loan authorizations. It does not copy the
   reference fixture to another customer. Empty offline providers are never called
   without valid backend authorization. Metadata stays UNVERIFIED; information/
   manual-review outcomes are expected until trusted upstream adapters exist.
6. `calculate_affordability_preview` is separately labeled declared-income-only,
   stored as `affordabilityPreview`, and is not evidence-based eligibility. Quote,
   partial repayment and refinancing results are indicative with assumptions.
7. Collect **actual customer confirmation** before submission. For production,
   bind it to a trusted UI/server event rather than trusting model-generated true.
   Information requests require new metadata and a new confirmation to resubmit.
8. Use source versions/citations as evidence, not instructions. Keyword search is
   not semantic RAG. No match means insufficient evidence, not invented conditions.

## Retry, workflow and persistence

- Workflow commands persist state/history/notices/audit/original replay response in
  one transaction. Same actor/key/operation/body replays its original snapshot;
  different payload/operation conflicts. Fetch current status separately.
- Eligibility keeps its original separate actor-key/snapshot rules: unchanged
  request/application/policy returns historical assessment; changed revision,
  document or state needs a new key. It never mutates workflow state. Historical
  reads still require current access after a final decision.
- Application revision increments on mutations. Restart invalidates transient
  sessions, not persisted cases or replay/assessment records. SQLite is local-only
  in ignored `data/local/backend-demo.sqlite3`; do not deploy it on ephemeral disk.
- Mandatory in-app workflow updates are distinct from consent-gated optional
  reminders. No real customer communication or human support is sent.
- APPROVED is a synthetic human-recorded outcome, not signed or funded. No route
  executes repayment, full payoff, signing, transfers or disbursement.

## Frontend and future provider work

Frontend files, scripts, package manifests and the temporary Node API are unchanged.
Do not point the entire UI to this backend and assume compatibility: command keys
are stricter, eligibility has four snake_case outcomes, the saved preview is named
separately and `/chat` intentionally returns 501 ORCHESTRATOR_NOT_CONFIGURED.
Existing Node port 4010 and backend port 8000 can run side by side.

Connect trusted profile/verified document/evidence and purpose-specific consent
ports before claiming completed eligibility verification. Preserve provider
freshness, policy expiry and distinction between ANAF consent and bureau basis/
notice. The independent reference demo remains reproducible with its historical
clock; no live provider is called. PostgreSQL/Supabase adapter/migrations, durable
auth/RLS, encrypted file storage, reservations/outbox and production hardening
remain separate work; no cloud resources or free-tier availability are assumed.

## Verified

- **160 Python tests**: 110 upstream eligibility tests retained + 50 backend tests.
- **22 live backend HTTP checks** including real Uvicorn restart/persistence and
  draft -> submit -> request information -> resubmit -> human decision.
- **Seven live eligibility HTTP checks**, original generated contract parity.
- Real `main.py` subprocess health/OpenAPI: 39 operations and 14 scoped tools.
- `compileall`, `pip check`, `git diff --check`.
- Frontend ESLint, all workspace TypeScript checks and **16 existing tests**.
- No frontend diff against current origin/main; no runtime databases/secrets staged.

Known non-failure: pinned Starlette 1.10 warns that its HTTPX TestClient integration
is deprecated; the supported pinned combination passes. No additional HTTP client
was introduced merely to suppress that warning.