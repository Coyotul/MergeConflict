# Eligibility Check API/tool contract v1

Independent **synthetic local demo**; not a Raiffeisen integration or credit
decision system. Generated OpenAPI is in `eligibility.openapi.json`. Shared
serialized schemas are in `../schemas/eligibility-*.json`.

## Authentication and trust boundary

`Authorization: Bearer <demo-key>` resolves a backend actor. The bundled public
keys `demo-customer-key` and `demo-reviewer-key` are for loopback demonstration
only, **not production authentication**. A real gateway must inject verified
identity, permissions and assignment into `eligibility_router`.

The customer may access only their applications. Reviewers/services need explicit
assignment and `eligibility:assess` or `eligibility:read`. Unknown and unauthorized
application checks use the same 403 response. All reads are permission-checked.
The frontend demo's opaque session tokens are NOT these Python demo keys; do not
pass client-chosen roles or trust frontend session storage as backend identity.

## Routes

- `GET /health`: public dependency check. 200 when local storage is available,
  otherwise 503; includes `mode: synthetic-demo`, `persistence: local-sqlite`.
- `POST /api/eligibility/assessments`: check a trusted server-owned application.
- `GET /api/eligibility/assessments/{assessment_id}`: fetch an immutable historical
  assessment after current owner/assignment/permission checks. May be read after
  the application has reached a final state; it remains historical, not approval.

POST input (unknown fields rejected):

```json
{
  "application_id": "demo-app-eligible",
  "pricing_scenario_id": "demo-quote-eligible",
  "idempotency_key": "eligibility-request-0001"
}
```

Only `application_id` and `idempotency_key` are required. Without a pricing
scenario, basic checks run but complete affordability remains information-required.
Do not send income, interest rates, roles, consent claims, profiles or provider
reports through this endpoint. Evidence comes from trusted backend repositories,
consent records and validated adapters. No CNP or real applicant data is needed.

The ANAF SQLite adapter resolves a fictional CNP from trusted backend bindings,
not a request field. It reads the supplied credit-source fixture in read-only
mode and does not update its global reporting date. Provider provenance is
synthetic. Monthly salary periods and completed-year averages are distinguished
internally by `IncomeVerificationData`; serialized provider contract:
`../schemas/anaf-income-verification.schema.json`. Historical annual averages
cannot automatically establish current recurring salary or pass affordability.
The public request/result/tool schemas are unchanged by this adapter wiring.

Success: `{ "data": <EligibilityAssessment> }`. All amounts and ratios are
decimal **strings**, timestamps are timezone-aware UTC, and evidence IDs resolve
to the returned evidence references. Public sources retain ID, classification,
URL, section and retrieval date. Demo assumptions are returned separately.

Possible assessment statuses:

- `PRELIMINARY_REQUIREMENTS_SATISFIED`
- `PRELIMINARY_REQUIREMENTS_NOT_SATISFIED`
- `ADDITIONAL_INFORMATION_REQUIRED`
- `MANUAL_REVIEW_REQUIRED`

Every result has `simulated: true`, `final_credit_decision: false` and
`human_review_required: true`. Individual checks are `PASS`, `FAIL`,
`INFORMATION_REQUIRED`, `REVIEW_REQUIRED` or `NOT_APPLICABLE`. Aggregation gives
review/integrity concerns precedence over failures, failures over missing data;
all individual reasons remain visible. An empty check set cannot pass.

## Authorization, states and failures

Permitted POST states: `DRAFT`, `AWAITING_DOCUMENTS`, `PRELIMINARY_ASSESSMENT`,
`READY_FOR_SUBMISSION`, `PENDING_HUMAN_REVIEW`, `MORE_INFORMATION_REQUIRED`.
Eligibility never changes these states, submits, approves, rejects, signs or
disburses. Final-state applications cannot receive a new screening through this
endpoint. Workflow/human review own those consequential operations.

Error envelope:

```json
{
  "error": {
    "code": "ACCESS_DENIED",
    "message": "This assessment is not permitted.",
    "correlationId": "server-generated-correlation-id"
  }
}
```

Codes/statuses include: `UNAUTHORIZED` (401), `ACCESS_DENIED` (403),
`PRICING_SCENARIO_NOT_FOUND`/`ASSESSMENT_NOT_FOUND` (404),
`INVALID_WORKFLOW_STATE`/`APPLICATION_CHANGED`/`IDEMPOTENCY_CONFLICT` (409),
`VALIDATION_ERROR` (422), `STORAGE_UNAVAILABLE` (503), `INTERNAL_ERROR` (500).
Untrusted input/provider exception contents are not echoed. Provider failures
typically produce an auditable preliminary review/information result, not a 500
and never an implicit pass. Missing/expired policies also require review with no
provider inquiry.

## Retry and persistence semantics

Keys are scoped to the authenticated actor and hashed at rest. Identical inputs
and application/policy snapshot replay the original assessment, **including the
original `assessed_at`**. A replay is explicitly historical; it is not proof of
fresh evidence. Different parameters or changed backend snapshots require a new
key and return 409 if an old key is reused. A failed storage operation does not
commit the key; retry is safe. Denied accesses are audited without applicant data.

Local SQLite commits the assessment, idempotency record and audit event atomically.
The service serializes checks within one process; uniqueness/transactions prevent
duplicate stored outcomes across processes. **Exactly-once provider inquiry across
multiple processes is not guaranteed** and needs a durable reservation/outbox
before live providers or multiple workers are introduced.

## Agent tool

`run_eligibility_check` uses the same identifier schema and service. The backend
injects `actor`; it is not a tool argument. `tool_definition()` exports its schema.
The tool returns the same data/error envelopes. The orchestrator may explain rule
results and request missing evidence; it must not reinterpret them as a final
decision or substitute its own calculations.

## Frontend integration handoff

The separate frontend prototype's `Assessment` type currently has only satisfied
and manual-review outcomes. Integration must support all four backend outcomes,
retain rule-level reasons/source links, display the indicative/synthetic flags,
and use `financial_assessment.debt_to_income_ratio`/policy version rather than
recalculating in the browser. Metadata-only document acceptance is not verified
evidence. Replace the temporary frontend service with an authenticated backend
adapter; this branch deliberately does not change the frontend files.