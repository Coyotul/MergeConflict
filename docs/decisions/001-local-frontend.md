# ADR 001: Local desktop frontend prototype

Date: 2026-10-28. Status: accepted for the synthetic frontend increment.

## Scope and responsibilities

The owner selected English UI text, local-only operation and a desktop-first design inspired by the supplied conversational reference. The original indigo/white palette and button-only role selector are superseded by ADR 003: Raiffeisen-inspired yellow/black colors and credential-based synthetic customer/bank-agent sign-in. `SPECIFICATION.md` remains the product source of truth; this ADR narrows the present frontend increment, not the eventual product.

- `apps/customer`: Next.js App Router, React, TypeScript, Tailwind 4; dashboard, assistant, products/calculator, existing loans and persistent applications.
- `apps/staff`: separate Next.js reviewer workspace; queue, independent evidence inspection, justified decisions, information requests and history.
- `packages/ui`: shared shadcn-style Radix controls and visual primitives, local Inter font, original SVG illustrations, neutral fictional Luma branding. The current shadcn generator hit an npm workspace resolver error; Button/Dialog/Switch are adapted from verified MIT-licensed shadcn registry sources using unified `radix-ui`, while remaining controls wrap the same accessible primitives. No bank affiliation.
- `packages/banking/src`: typed wire models, decimal-safe indicative calculations, workflow gates, API client and React state provider.
- `packages/banking/server`: deliberately temporary Node HTTP **demo adapter**, not the Python backend. Loopback port 4010, synthetic fixtures only, validated inputs, role/ownership/assignment checks, atomic JSON persistence in ignored `data/local/frontend-demo.json`.
- Python packages in `src/` are untouched. FastAPI will replace the demo adapter through the same typed API boundary.

Using a separate local adapter lets customer (3000) and staff (3001) observe the same state. Browser localStorage is not the workflow database. Customer/staff poll the adapter and refresh after commands. Session tokens are transient, opaque and role-bound. As of ADR 003, login validates public synthetic email/password accounts, tokens expire after eight hours and logout revokes them. This is still **not production authentication**. CORS is restricted to the two loopback app origins. Bind all processes to 127.0.0.1.

## Persistence and conceptual entity relationships

The demo JSON aggregates, rather than pretending to be PostgreSQL tables:

- Customer profile -> owned loan accounts, applications, consent settings, conversation and notifications.
- Product + policy version -> application -> computed offer, document metadata, status history and assigned reviewer.
- Application -> human reviews/notes and audit events; audit references actor, action, object, time and outcome.
- Idempotency record -> actor, operation, payload fingerprint and returned object ID.

A real database must normalize these into specification section 14 entities, add foreign keys/migrations/RLS and durable authentication. The demo store is not encrypted, multi-process safe or tamper-proof. Never use real customer data. Invalid/corrupt store files fail startup rather than silently losing data.

## Workflow and trust boundaries

Origination: DRAFT -> AWAITING_DOCUMENTS -> READY_FOR_SUBMISSION -> PENDING_HUMAN_REVIEW -> MORE_INFORMATION_REQUIRED -> READY_FOR_SUBMISSION -> PENDING_HUMAN_REVIEW -> APPROVED or REJECTED. All transitions are server-checked and appended to history. Customer submission requires an explicit confirmation, complete required demo documents and an idempotency key. Approval/rejection/information requests require the assigned reviewer, independently reviewed evidence and a written reason. APPROVED does not mean signed or funded.

Uploads validate filename, MIME type and size, but store **metadata only**; files are never transmitted or OCR-processed. Users must confirm synthetic content. Format acceptance is not authenticity, income or identity verification. Previewed values are clearly labeled synthetic fixtures, not extraction results.

The conversational adapter classifies supported intents and invokes shared demo tools; it is explicitly rule-based and **does not implement an LLM or RAG**. Unsupported or incomplete requests ask for clarification instead of manufacturing outcomes. Sources are versioned synthetic policy fixtures. This can be replaced by the Python orchestrator without changing UI workflows.

Calculations use decimal.js (40-digit precision, ROUND_HALF_UP, RON cents). Monthly schedules round interest/payment to cents and adjust the final payment. Rates, fees and income are configurable synthetic fixtures, not bank quotations. Full settlement and real repayment execution are unavailable. Refinancing compares monthly cost **and** total cost; longer terms are not automatically better.

## Dependencies and tests

Versions verified from current official docs/npm on 2026-10-28: Next 16.4.3, React 19.3.1, Tailwind 4.3.3, decimal.js 10.6.0, Zod 4.6.7, Playwright 1.64.1. Install uses npm workspaces and a lockfile. Font/assets are bundled locally. Runtime requires no cloud service, credentials or network. shadcn CLI is used only to generate shared controls; no cloud/free-tier assumptions apply.

Initial tests: known-result amortization and zero interest; invalid financial inputs; early repayment/refinancing trade-offs; workflow/confirmation gates; customer isolation/reviewer assignment; duplicate/colliding idempotency keys; invalid uploads; persistence/restart; and browser-level customer -> request information -> resubmit -> human decision. Validate ESLint, all workspace TypeScript projects, unit/API tests and both production builds. Browser tests cover desktop navigation, keyboard dialogs and rich response flows.

Deferred: real identity/auth, banking APIs, LLM/RAG/OCR, PostgreSQL migrations, administrator UI, signing/disbursement, production observability and security hardening. These must not be advertised as implemented.
