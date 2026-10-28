# Frontend demo API v1 (temporary adapter contract)

Base URL: `http://127.0.0.1:4010/api`. Money is a decimal **string** in RON; timestamps are ISO 8601 UTC. All results concern synthetic data. Types live in `packages/banking/src/types.ts`; HTTP input schemas in `packages/banking/src/schemas.ts`. Replace the adapter with authenticated FastAPI endpoints, not direct UI database access.

## Authentication and responses

`POST /session` `{ "role": "customer" | "reviewer", "email": string, "password": string }` -> `{ token, actor, expiresAt }`. Email is trimmed and lowercased; password is required and case-sensitive. Inputs are strict: role selection without credentials returns 400. Public synthetic accounts are defined in `packages/banking/src/demo-accounts.ts` and shown on the UI. Incorrect credentials or using a customer account in the bank-agent workspace (or vice versa) returns 401 / INVALID_CREDENTIALS with the same generic message. An account fixes the server-issued actor and role; workspace selection never grants permissions by itself. This is not production authentication or real identity verification.

Tokens are opaque, role-bound, held in server memory and expire after eight hours; `expiresAt` is ISO 8601 UTC. The browser stores the validated session in per-tab sessionStorage, not the password. Server restart invalidates sessions but preserves application data. All remaining `/api` routes require `Authorization: Bearer <token>`. Invalid/expired/revoked sessions return 401; wrong role/owner/assignment returns 403 or 404.

`POST /session/logout` `{}` -> `{ "signedOut": true }`. Revokes the authenticated token. Subsequent calls with that token return 401; the UI clears session storage and returns to the login screen. No password or token is written to the persisted demo JSON.

Success: `{ "data": <typed value> }`. Failure: `{ "error": { "code": string, "message": string, "correlationId": string } }`. Responses never report a failed command as successful. Supported errors: VALIDATION_ERROR (400), INVALID_CREDENTIALS / UNAUTHORIZED (401), FORBIDDEN (403), NOT_FOUND (404), INVALID_TRANSITION / IDEMPOTENCY_CONFLICT (409), INTERNAL_ERROR (500).

## Queries

- `GET /health` (public, outside `/api`) -> `{ status: "ok", mode: "synthetic-demo", persistence: "local-json" }`.
- `GET /snapshot` -> `Snapshot`: actor, customer profile, products, loans, visible applications, notifications, permitted audit events, consent and messages. Customer results are owner-filtered; reviewer results are assignment-filtered.

## Customer commands

- `POST /chat` `{ text: string (1..2000) }` -> assistant message. Stored user/assistant messages are independent of applications. Structured `kind` values invoke loan, repayment, refinance, document or application cards. Unknown intents return a clarification; no real LLM is called.
- `POST /chat/reset` `{}` -> cleared conversation; applications remain unchanged.
- `POST /applications` `{ amount: decimalString, months: integer, productId: "personal" | "mortgage" | "car", idempotencyKey: UUID }` -> application. Pricing is recomputed on the server from the versioned demo product; client-supplied interest rates are not accepted.
- `POST /applications/:id/documents` `{ kind: "identity" | "income" | "statement", name, mimeType, size, syntheticConfirmed: true }` -> application. Allowed PDF/JPEG/PNG, >0..10 MiB. **Metadata only**, no bytes/OCR/authenticity verification. Relevant missing/requested checklist item is updated, followed by a valid state transition when complete.
- `POST /applications/:id/submit` `{ confirmed: true, idempotencyKey: UUID }` -> application. READY_FOR_SUBMISSION only. Repeating the same actor/key/payload returns the original result, not a duplicate transition. Reusing a key with different inputs returns 409.
- `PATCH /consent` `{ financialInsights: boolean, notifications: boolean }` -> consent. Financial-insight estimates require the corresponding consent.
- `POST /notifications/read` `{}` -> updated notifications.
- `POST /support` `{ message: string }` -> notification. Simulated handoff only; no real bank employee is contacted.

## Assigned reviewer commands

- `POST /applications/:id/review` `{ action: "approve" | "reject" | "request-information", reason: string (10..2000), evidenceReviewed: true, requestedDocument?: "identity" | "income" | "statement", idempotencyKey: UUID }` -> application. Assigned reviewer + PENDING_HUMAN_REVIEW required. Information requests require a document kind; other decisions require complete evidence. Writes status history, review note, audit event and customer notification atomically.
- `POST /applications/:id/notes` `{ text: string (3..2000) }` -> application; assigned reviewer only. Internal notes never appear in customer snapshots.

## States and consequential operations

Documents: MISSING -> FORMAT_ACCEPTED, explicitly not VERIFIED. Preliminary affordability uses synthetic declared income and configured debt ratio, not a credit decision. Origination states: DRAFT, AWAITING_DOCUMENTS, READY_FOR_SUBMISSION, PENDING_HUMAN_REVIEW, MORE_INFORMATION_REQUIRED, APPROVED, REJECTED, CANCELLED. Extra specification states remain reserved for future capabilities.

APPROVED is a synthetic human decision only. The demo does not expose signing, settlement, transfers, full payoff quotation or real repayment execution. Indicative calculators are reusable deterministic client/domain functions; production authoritative results must come from FastAPI financial services.
