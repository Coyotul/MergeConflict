# ADR 006: Authenticated synthetic backend capabilities for orchestration

Date: 2026-10-28. Status: accepted for local backend development on `backend-routes`.

## Context

The Python tree was scaffolding; the Next.js prototype used a deliberately temporary
Node adapter (ADR 001). The owner requested backend routes that a future orchestrator
can call. `SPECIFICATION.md` sections 6–13 require narrow validated tools, independent
authorization, deterministic calculations, durable state, explicit submission and
human-controlled credit outcomes. No cloud credentials or banking connection exist.

## Decision

- Use the selected FastAPI/Pydantic v2 modular monolith. HTTP handlers live in
  `src/api/application/`, gateway/auth/error middleware in `src/api/gateway/`, shared
  models in `src/models/`, and composition in `src/core/`.
- Build functional synthetic services, not success-shaped placeholder endpoints.
  OpenAPI operation IDs map to the fourteen proposed tools in specification section
  7. Staff review remains a separate, assigned-human capability. The `/chat` boundary
  returns explicit 501 until an orchestrator is connected.
- Keep financial logic in a pure Decimal engine and configured affordability rule.
  Products/rates/thresholds/policy versions come from validated synthetic JSON, not
  request bodies or prompts. Quote assumptions and preliminary evidence/reason
  codes are part of the wire contract.
- Mirror resource naming and camelCase/decimal-string conventions of the frontend
  contract. Add idempotency to all durable creation/application/review commands.
  Preserve the original replay response; separate GET requests return current state.
  The optional `/api` alias is not a full Node guided-chat compatibility layer.
- Use **SQLite from Python's standard library for local development only**. No new
  hosted service, unconfirmed database driver or cloud free tier is needed. A SQL
  migration creates owner/assignment indexes, foreign keys and typed JSON aggregates.
  Workflow changes, notices, audit and idempotency results commit in one transaction;
  BEGIN IMMEDIATE serializes concurrent writes. Corruption fails startup.
- Store a new backend database under ignored `data/local/backend-demo.sqlite3`.
  Do not overwrite or import `frontend-demo.json`, and do not alter frontend scripts.
  Application records survive restart; transient demo bearer sessions do not.
- Use the existing public Alex/Jamie credentials, plus a second customer and reviewer
  to exercise owner/assignment isolation. Credentials and tokens are never persisted.
  This is not production identity verification. Bind the default server to loopback.
- Keep document handling metadata-only and policy search keyword-only, with explicit
  limitations. No OCR/identity/income/authenticity result, semantic RAG, ANAF/bureau
  query, signing, settlement, payment or disbursement is claimed.

## Storage relationships and future deployment

Actors -> customers -> owned loans/applications/consents/messages/notifications.
Applications -> assigned reviewer + document metadata + status history + review
notes + saved quote/assessment/version. Audit references actors, objects and
correlation IDs. Support references an owned application and conversation message
IDs. Idempotency stores actor/key/fingerprint and original typed response.

PostgreSQL/Supabase remains the intended deployment architecture. The local SQLite
adapter is a deliberate bounded exception, **not** ephemeral deployed persistence
and not a production banking database. Before deploying, introduce a managed
PostgreSQL adapter/migrations, RLS/tenant boundaries, durable identity sessions,
trusted confirmation events, encrypted document storage, operational retention,
distributed abuse controls and monitoring. The current aggregate schema and audit
are not tamper-proof. No free-tier/provider availability is assumed or provisioned.

## Verification and dependencies

Tests use standard-library unittest and FastAPI TestClient/HTTPX. Coverage includes
known annuity results, cents/fees/insurance, principal conservation, partial
repayment, refinancing trade-offs, strict validation, role spoofing, owner/assignment
isolation, private notes, workflow/confirmation gates, retry conflicts, concurrent
retries, transaction rollback, restart/resumption, corrupt stores and OpenAPI.

Versions verified via official FastAPI/Pydantic documentation and pip on 2026-10-28:
FastAPI 0.162.0, Pydantic 2.14.1, Starlette 1.10.0, Uvicorn 0.54.0, HTTPX 0.28.1.
Starlette 1.10 emits a TestClient deprecation warning for HTTPX while still supporting
it; no new HTTP client library is introduced just to silence that warning. Core
versions are pinned; remaining pre-existing document/data dependencies are retained.

## Consequences / next integration

- The orchestrator can consume `/openapi.json` and invoke `/api/v1` with the verified
  customer session; it does not need direct database access.
- Register a customer tool allowlist, never the staff review/notes operations.
  Collect explicit trusted confirmation before submit; interpret all financial
  responses as indicative and use cited sources as evidence, not instructions.
- Backend and existing frontend can run side by side at ports 8000 and 4010. A
  later frontend/orchestration integration must handle changed command schemas and
  a real assistant boundary before replacing the Node adapter.
- Full product scope (administrator actions, semantic ingestion/retrieval, OCR,
  verified banking data, insights, restructuring/recovery and signing/settlement)
  remains future work; no stub advertises these as completed.