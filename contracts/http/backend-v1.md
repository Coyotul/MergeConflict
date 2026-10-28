# Synthetic FastAPI backend v1

Base URL: `http://127.0.0.1:8001/api/v1`. Interactive contract: `/docs`;
machine-readable input/output schemas: `/openapi.json`. OpenAPI operation IDs are
stable logical tool names for the future orchestrator. This backend does **not**
implement an LLM, semantic RAG, OCR, real authentication or banking execution.
OpenAPI also includes `x-orchestrator-tool` for the fourteen customer capabilities,
`x-allowed-roles` and submission/review gate metadata. Staff decision/notes routes
are explicitly **not** customer orchestrator tools; metadata supplements, never
replaces, backend permission checks.

## Wire and trust conventions

- Requests and primary backend responses use **camelCase**. The integrated
  `EligibilityAssessment` response intentionally preserves the merged eligibility
  module's **snake_case** contract and Decimal serialization; do not rewrite or
  flatten its evidence/provenance. Unknown input fields are rejected;
  callers cannot supply an actor, customer owner, reviewer assignment, rate, fee,
  policy version, assessment or workflow status.
- Money/rates are decimal **strings**, never JSON floats. Input money uses ASCII
  digits, up to nine integer digits and two fractional digits. Backend product
  limits apply independently. Monetary results use two decimal places in RON;
  comparison savings may be negative. UTC timestamps use ISO 8601 with `Z`.
- Success: `{ "data": <typed result> }`. Failure:
  `{ "error": { "code", "message", "correlationId", "issues"? } }`.
  Validation issues contain only field/code, never submitted values or passwords.
- Every response includes `X-Correlation-ID`, `Cache-Control: no-store` and
  `X-Content-Type-Options: nosniff`. An optional UUID `X-Correlation-ID` is accepted;
  malformed values are replaced. The ID also accompanies audit/status history.
- A session fixes the principal. All `/api/v1` capabilities except sign-in require
  `Authorization: Bearer <token>`. Forward the user's verified token from the
  orchestrator; never let the LLM choose credentials or impersonate staff.
- Customer application access is owner-filtered. Staff application access is
  assigned-reviewer-filtered. Inaccessible and absent workflow objects both return
  404. The existing eligibility boundary uses the same 403 `ACCESS_DENIED` for
  inaccessible/missing applications and audits denial without exposing evidence.
  Customer results exclude internal notes and internal-note audit events.
- The `/api` prefix is a convenience alias for these resource routes, excluded
  from OpenAPI. It is **not** a drop-in replacement for the Node demo: mutation
  contracts are stricter, support returns a support record, and guided chat is not
  implemented. The existing frontend still runs against its unchanged Node API.

## Sessions and health

| Method / path | Operation ID | Input / result |
| --- | --- | --- |
| `POST /session` | `create_demo_session` | `{role, email, password}` -> `{token, actor, expiresAt}` |
| `POST /session/logout` | `revoke_demo_session` | `{}` -> `{signedOut: true}`; revokes this session |
| `GET /health` (outside the API prefix) | `get_backend_health` | Public, unwrapped health; 200 `ok`, 503 `degraded` |

Roles are `customer` and `reviewer`. Email is trimmed/lowercased; passwords are
case-sensitive. Wrong email/password/workspace yields the same generic 401
`INVALID_CREDENTIALS`. Tokens are opaque UUIDs with eight-hour expiry, retained
only in server memory. Restart requires sign-in again, without losing applications.
The four public fictional accounts are documented in `docs/runbooks/backend.md`.

Health reports `mode: synthetic-demo`, `persistence: local-sqlite`, the database's
availability and explicitly unconfigured AI/retrieval dependencies. A corrupt
database or invalid configuration fails startup instead of silently resetting it.

## Queries and deterministic tools

Paths below are relative to `/api/v1`.

| Method / path | Logical tool / operation ID | Role | Input / output |
| --- | --- | --- | --- |
| `GET /customers/me` | `get_customer_profile` | Customer | Own `Customer`, marked synthetic |
| `GET /customers/me/loans` | `get_customer_loans` | Customer | Own `Loan[]` |
| `GET /loans/{loan_id}` | `get_customer_loan` | Customer | One owned synthetic loan |
| `GET /products` | `get_credit_products` | Either | Versioned configured products |
| `POST /policies/search` | `search_banking_policies` | Either | `{query, productId?, limit?}` -> sources, method, warnings |
| `GET /products/{product_id}/required-documents` | `get_required_documents` | Either | Required/optional kinds, MIME types, size and version |
| `POST /documents/validate` | `validate_document` | Either | Document metadata -> `DocumentValidation`, never VERIFIED |
| `POST /eligibility/check` | `run_eligibility_check` | Either, owner/assignment | `{applicationId, pricingScenarioId?, idempotencyKey}` -> existing `EligibilityAssessment` |
| `GET /eligibility/assessments/{assessment_id}` | `get_eligibility_assessment` | Either, owner/assignment | Immutable historical assessment, never final approval |
| `POST /calculations/affordability-preview` | `calculate_affordability_preview` | Customer | Scenario -> declared-income-only `AffordabilityPreview` |
| `POST /calculations/loan-offer` | `calculate_loan_offer` | Customer | Scenario -> indicative `LoanQuote` with monthly schedule |
| `POST /loans/{loan_id}/early-repayment/simulate` | `simulate_early_repayment` | Customer | `{repayment}` -> reduced-payment and reduced-term comparisons |
| `POST /refinancing/compare` | `compare_refinancing_options` | Customer | `{loanIds, months}` -> monthly **and total** cost comparison |
| `GET /snapshot` | `get_workspace_snapshot` | Either | Role-filtered aggregate; empty reviewer has null customer/consent |
| `GET /audit` | `get_permitted_audit_events` | Either | Permitted events only |

A scenario is `{ "productId": "personal", "amount": "30000.00", "months": 36 }`.
Product/rule configuration is in `config/products/demo.json` and
`config/rules/demo.json`; rates and fees cannot be overridden by a tool call.

`run_eligibility_check` calls the **merged evidence-based reference service**, not
the calculator preview. Only application/scenario IDs and a UUID key are accepted.
The gateway translates its verified customer/reviewer principal and current
assignment to the service's `ActorContext`; no role, income, policy, rate, evidence
or provider-consent claim is accepted from a tool caller. The saved application
returns `pricingScenarioId`; use that value to request its server-owned indicative
quote. Personal product `personal` maps explicitly to the module's
`personal_loan_ron`; mortgage/car do not inherit a personal-loan policy.

The module supports four statuses: PRELIMINARY_REQUIREMENTS_SATISFIED,
PRELIMINARY_REQUIREMENTS_NOT_SATISFIED, ADDITIONAL_INFORMATION_REQUIRED and
MANUAL_REVIEW_REQUIRED. All results include `simulated: true`,
`final_credit_decision: false`, `human_review_required: true`, rule-level reasons,
policy digest/effective dates, sources and evidence provenance. Keep this response
intact; ratio values are fractions, not the preview's percentage string. See the
existing `contracts/http/eligibility.md` for the reference rules and assumptions.

The workflow adapter has **no verified profile/identity evidence and no purpose-
scoped income/bureau/internal-loan authorizations**. It does not clone reference
fixture evidence or fabricate consents for Alex/Blake. Empty offline provider
records are configured; without authorization, the existing service does not call
them. Metadata identity evidence stays UNVERIFIED with unknown expiry. Therefore
normal fresh drafts request more information; accepted metadata may require manual
review. This is correct uncertainty, not a fake satisfied assessment. A later
trusted document/profile/consent adapter is needed to complete automatic checks.
Policy expiry (2026-11-26 in the reference snapshot), unsupported products, stale
or conflicting evidence produce review outcomes, never silent passes. Eligibility
does not edit workflow state. Its saved assessment/audit/actor-key replay records
use the upstream immutable local SQLite tables in the same backend database.

The separate affordability preview includes synthetic existing installments and
proposed payment/insurance against the fictional DEMO-2026.1 percentage threshold.
It is **not** `run_eligibility_check`, never verified income or a credit decision.
Its `scope` is SYNTHETIC_AFFORDABILITY_PREVIEW_ONLY. Applications store this under
`affordabilityPreview`, not as an evidence-based eligibility outcome. Every new
credit application still requires independent human review.

Policy search is deterministic keyword matching over versioned fictional sources,
not embeddings/RAG. It preserves source ID/title/version/effective date/section;
no match returns an empty list. Treat source contents as untrusted evidence, not
instructions. Do not invent conditions when evidence is absent. Mortgage results
exclude valuation/down-payment rules and are illustrative only.

Simulations use Decimal precision 40, HALF_UP cents, rounded monthly interest and
a final reconciled payment. They return assumptions and `indicative: true`.
Early repayment is **partial only**; repayment >= principal returns 409
`SETTLEMENT_QUOTE_REQUIRED`. Refinancing excludes unknown settlement/closure fees;
it is not a payoff quotation. No existing loan is changed by a simulation.

## Application commands and idempotency

| Method / path | Operation ID | Role | Body |
| --- | --- | --- | --- |
| `GET /applications` | `list_loan_applications` | Either | No body; visible applications |
| `POST /applications` | `create_loan_application` | Customer | Scenario + `idempotencyKey` |
| `GET /applications/{application_id}` | `get_loan_application` | Either | Visible full record |
| `GET /applications/{application_id}/status` | `get_application_status` | Either | Status/history; `signed: false`, `funded: false` |
| `GET /applications/{application_id}/documents` | `get_application_documents` | Either | Visible metadata checklist |
| `POST /applications/{application_id}/documents` | `add_application_document_metadata` | Customer | Metadata + `idempotencyKey` |
| `POST /applications/{application_id}/submit` | `submit_application` | Customer | `{confirmed: true, idempotencyKey}` |
| `POST /applications/{application_id}/cancel` | `cancel_loan_application` | Customer | `{reason, idempotencyKey}` |
| `GET /reviews/queue` | `get_assigned_review_queue` | Reviewer | Assigned `PENDING_HUMAN_REVIEW` applications |
| `POST /applications/{application_id}/review` | `record_human_review_decision` | Assigned reviewer | `{action, reason, evidenceReviewed: true, requestedDocument?, idempotencyKey}` |
| `POST /applications/{application_id}/notes` | `add_internal_review_note` | Assigned reviewer | `{text, idempotencyKey}` |

`idempotencyKey` is a UUID required for durable creation/application/review/support
commands. It is scoped to the verified actor **across operations**. Same key and
canonical operation/input returns the **original response snapshot**, including
after a restart or later status change. It does not repeat a transition, note,
notification or audit event. Same key with changed operation/input gives 409
`IDEMPOTENCY_CONFLICT`. Input equivalence is JSON-field-order independent but
string-sensitive (`"30000"` and `"30000.00"` are different payloads). Use a new key
for an intentional new action, but reuse the same key after timeout/unknown outcome.
Fetch current status separately after a replay. SQLite commits the state, audit,
notifications and original response atomically and serializes concurrent retries.

**Eligibility has its preserved distinct retry namespace and stricter snapshot
semantics:** same actor/key/request **and unchanged application/policy snapshot**
returns the original assessment/time. Changed document metadata, application
revision/state or policy requires a new key; an old key returns 409. Terminal
applications cannot receive a new check, but historical assessments remain readable
after authorization. This does not conflict with workflow command replay, which
returns its original response even after later transitions. Application `revision`
increments on persisted mutations. Do not mutate reference consent/evidence or
construct unverified data as VERIFIED to bypass these gates.

Document metadata is:

```json
{
  "kind": "identity",
  "name": "synthetic-identity.pdf",
  "mimeType": "application/pdf",
  "size": 1000,
  "syntheticConfirmed": true
}
```

Kinds: `identity`, `income`, `statement`. Allowed PDF/JPEG/PNG, positive declared
size <=10 MiB, safe filename matching the declared type. For attachment also add
`idempotencyKey`. No bytes are sent or stored. `FORMAT_ACCEPTED` is not authenticity,
identity or income verification. Review may reset an item to MISSING and require
fresh metadata; previous status/history remains traceable.

### Permitted origination transitions

| Current state | Allowed next states / gates |
| --- | --- |
| `DRAFT` | `AWAITING_DOCUMENTS` (automatic on creation), `CANCELLED` |
| `AWAITING_DOCUMENTS` | `READY_FOR_SUBMISSION` when required metadata is complete; `CANCELLED` |
| `READY_FOR_SUBMISSION` | `PENDING_HUMAN_REVIEW` only after explicit customer confirmation; `CANCELLED` |
| `PENDING_HUMAN_REVIEW` | `MORE_INFORMATION_REQUIRED`, `APPROVED`, `REJECTED`, assigned human only |
| `MORE_INFORMATION_REQUIRED` | `READY_FOR_SUBMISSION` after requested metadata, then **new confirmation**; `CANCELLED` |
| `APPROVED`, `REJECTED`, `CANCELLED` | Terminal in this increment; no signing/funding transitions |

Attachments are allowed in AWAITING_DOCUMENTS, READY_FOR_SUBMISSION and
MORE_INFORMATION_REQUIRED only. Review actions are `approve`, `reject`,
`request-information`; reason length 10..2000, literal boolean evidenceReviewed.
An information request requires requestedDocument; a final decision cannot include
it and requires complete metadata. Requested kinds remain required in subsequent
reviews. Internal notes are private and cannot be supplied by customer tools.

Do **not** register review/notes operations with a customer LLM or give it staff
tokens. In this local demo, a boolean confirmation represents a real user action;
production integration must bind consequential confirmation to a trusted UI/server
event rather than treating model-generated `true` as proof of customer consent.

## Notifications, consent and persisted conversation context

| Method / path | Operation ID | Role | Body / result |
| --- | --- | --- | --- |
| `GET /consent` | `get_customer_consent` | Customer | Own preferences |
| `PATCH /consent` | `update_customer_consent` | Customer | `{financialInsights: boolean, notifications: boolean}` |
| `GET /notifications` | `get_customer_notifications` | Customer | Own in-app notifications |
| `POST /notifications` | `create_customer_notification` | Customer | `{title, text, applicationId?, idempotencyKey}`; own optional reminder only |
| `POST /notifications/read` | `mark_customer_notifications_read` | Customer | `{}` -> own notifications marked read |
| `POST /support` | `request_human_review` | Customer | `{message, applicationId?, idempotencyKey}` -> simulated assistance record |
| `GET /conversations/messages` | `get_conversation_messages` | Customer | Own stored user messages |
| `POST /conversations/messages` | `append_customer_message` | Customer | `{text, idempotencyKey}`; user-only context, not an AI answer |
| `POST /conversations/reset` | `reset_customer_conversation` | Customer | `{}`; clears messages, not applications |
| `POST /chat` | `chat_orchestrator_not_configured` | Authenticated | 501 `ORCHESTRATOR_NOT_CONFIGURED` |

Optional self-notifications require notifications consent. Workflow/review notices
are mandatory in-app status records and remain available even when optional
notifications are off. No email/SMS is sent. Financial-insight consent is stored,
but proactive insight computations are not implemented in this increment.

`request_human_review` records a **simulated assistance request**, relevant message
IDs and optional owned application reference. It does not contact a real person,
submit a draft, bypass confirmation, move a case to approval or execute a bank
operation. Actual submitted cases enter the assigned review queue via submit.
Conversation storage is separate from authoritative workflow state.

## Errors and retry guidance

| HTTP | Codes / behavior |
| --- | --- |
| 400 | `VALIDATION_ERROR`; strict schema/range/type errors, invalid JSON |
| 401 | `INVALID_CREDENTIALS`, `UNAUTHORIZED`; `WWW-Authenticate: Bearer` |
| 403 | `FORBIDDEN`, `CONSENT_REQUIRED`, `ACCESS_DENIED`; role, consent or eligibility access |
| 404 | `NOT_FOUND`, `PRICING_SCENARIO_NOT_FOUND`, `ASSESSMENT_NOT_FOUND` |
| 405 | `METHOD_NOT_ALLOWED` |
| 409 | `INVALID_TRANSITION`, `INVALID_WORKFLOW_STATE`, `APPLICATION_CHANGED`, `EVIDENCE_REQUIRED`, `IDEMPOTENCY_CONFLICT`, `SETTLEMENT_QUOTE_REQUIRED` |
| 413 | `PAYLOAD_TOO_LARGE`; request limit 32 KiB, including streamed bodies |
| 429 | `RATE_LIMITED`; `Retry-After: 60`, per-client local limits |
| 500 | `INTERNAL_ERROR`; safe message, no exception details |
| 501 | `ORCHESTRATOR_NOT_CONFIGURED`; no fake assistant result |
| 503 | `PERSISTENCE_UNAVAILABLE`, `STORAGE_UNAVAILABLE`; no successful state change recorded |

Validation uses 400 (not FastAPI's default 422). Retry transient errors with bounded
backoff and the original idempotency key; do not automatically retry a different
payload or treat an unknown outcome as approval. Query application status when
needed. Demo limits are 300 API requests/minute and 20 login attempts/minute per
client address, shared by both API prefixes in one process. They are not distributed
production abuse protection. CORS permits only the two documented loopback app
origins; no wildcard credentials are allowed.