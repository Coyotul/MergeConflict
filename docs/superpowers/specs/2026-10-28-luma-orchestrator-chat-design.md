# Luma customer chat on the AI orchestrator — design

Date: 2026-10-28 · Status: draft for approval
References: `contracts/http/README.md` (chat API contract), `docs/superpowers/specs/2026-10-28-orchestrator-design.md` (orchestrator), `apps/customer/AGENTS.md` (Next.js version warning)

## 1. Intent

The Luma customer app (`apps/customer`, :3000) has a chat that today talks to the scripted TypeScript demo API (`packages/banking/server`, :4010, `POST /api/chat`). The owner wants to test the new AI orchestrator (FastAPI, :8000, `/chat/sessions/...`, Featherless `gpt-oss-120b`) through the real Luma UI. This work makes the Luma chat conversation run on the orchestrator. Everything else in Luma stays on the demo API for now; bridging the two backends comes later.

## 2. Goals, non-goals, anti-goals

**Goals**
- Messages typed in the Luma chat go to the orchestrator; its replies and blocks render in the Luma chat.
- The full orchestrator journey is usable from the UI: product questions with citations, the credit application, document upload, resolving extracted values/conflicts, choosing an offer, explicit confirmation, submission.
- A progress indicator from `progress.steps`; input controls driven by `awaiting`.
- Works with the orchestrator in real mode and in mock mode (`ORCHESTRATOR_MODEL=fake`).

**Non-goals (later work)**
- Applications submitted through the orchestrator appearing in Luma's Applications page, dashboard or the reviewer portal (:3001).
- Changing sign-in, dashboard, products, settings, notifications or the context panel (they keep using the demo API).
- Translating the Luma UI chrome to Romanian.
- Changing orchestrator behaviour beyond the CORS setting.

**Anti-goals**
- A submit button that submits without the customer clicking it, or that sends a `summary_version` other than the one on screen.
- UI text that implies approval, a real bank offer, or affiliation (the orchestrator's own wording rules stay in force; UI labels must not undo them).
- Breaking the rest of Luma (sign-in, dashboard, other pages) or the demo API's tests.

## 3. Constraints

- Contract: `contracts/http/README.md` and `contracts/http/chat.openapi.yaml` are authoritative for routes, headers, bodies, `TurnResponse`, blocks and errors. Customer identity is the `X-Customer-Id` header; the orchestrator only knows `cust-001`, `cust-002`, `cust-003`.
- Next.js in this repo is a newer version with breaking changes; read `node_modules/next/dist/docs/` before writing Next-specific code (`apps/customer/AGENTS.md`). Keep changes to plain React client components where possible.
- Frontend stack and style: existing Tailwind classes, `@banking/ui` primitives (`Button`, `Dialog`, `AssistantAvatar`, `InfoNote`, …), `lucide-react` icons. Match the current visual language of `assistant-workspace.tsx` / `rich-response.tsx`.
- The demo API remains required for sign-in and the rest of the app; `npm run dev` keeps starting it.
- Turns take ~2–5 s in real mode (synchronous API); the UI must show a pending state and block double-sends.

## 4. Approaches considered

| Option | Summary | Trade-off |
|---|---|---|
| **1. Browser calls the orchestrator directly (chosen)** | CORS allow-list in FastAPI for the Luma origins; typed orchestrator client + React hook in the frontend; new chat rendering for `TurnResponse`. | Explicit and independent of Next internals; one small backend setting. |
| 2. Next.js proxy (`rewrites`) | Customer app forwards `/orchestrator/*` to :8000. | No CORS, but relies on this Next version's rewrite/multipart behaviour, which `AGENTS.md` warns differs. |
| 3. Demo API forwards `/api/chat` | Frontend untouched. | Demo API message shape only knows its own card kinds; checklist/offers/confirmation would be lost or need translation. Dropped. |

The owner chose **1**.

## 5. Decided with the owner

- Scope: only the chat links to the orchestrator; other Luma areas later.
- The mockup (shown in the visual companion) is the target: Luma layout kept; message list and cards replaced; progress bar; checklist with upload; extracted values/conflict with actions; offer cards with Choose; summary with explicit Confirm; the existing context panel kept.
- Identity: the signed-in Luma customer acts as a **random** orchestrator customer.
- Approach 1.

## 6. Design

### 6.1 Backend: CORS (only backend change)
- `OrchestratorSettings` gains `cors_origins: list[str]` (default `["http://127.0.0.1:3000", "http://127.0.0.1:3001"]`), env `ORCHESTRATOR_CORS_ORIGINS` (comma-separated). Add to `.env.example`.
- `create_app` adds FastAPI's `CORSMiddleware` with those origins, methods `GET, POST, OPTIONS`, headers `Content-Type, X-Customer-Id`, no credentials.
- Tests: preflight from an allowed origin succeeds with the right headers; a disallowed origin gets no `Access-Control-Allow-Origin`. Regenerate/confirm the committed OpenAPI is unchanged (middleware doesn't alter the schema).

### 6.2 Frontend: orchestrator client (`packages/banking/src/orchestrator.ts`)
- Base URL `process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ?? "http://127.0.0.1:8000"`.
- TypeScript types mirroring the contract: `TurnResponse`, `SessionView`, `Awaiting`, `Progress`, `ChatMessageView`, `CitationRef`, the block union by `type`, `LoanOffer`, `ApplicationSummary`, `ErrorBody`. Amounts stay decimal strings (no float parsing for display; format with existing helpers in `packages/banking/src/format.ts` if they accept strings, else display as given + currency).
- Functions (all send `X-Customer-Id`): `createSession`, `sendMessage(text)`, `uploadDocument(docType, file)` (multipart), `selectOffer(offerId)`, `confirm(summaryVersion, decision)`, `getSession`.
- Errors map `ErrorBody` to a typed `OrchestratorError { status, code, retryable, message }`; network failure → `code: "unavailable", retryable: true` with a message telling the user to start the orchestrator (`uvicorn src.api.app:create_app --factory`).
- Unit tests (`packages/banking/test/orchestrator.test.ts`, existing `tsx --test` runner) against a local fake HTTP server: headers sent, multipart shape, error mapping, unknown block types tolerated.

### 6.3 Frontend: chat state hook (`useOrchestratorChat`)
- Holds `{ sessionId, customerId, messages, latest: TurnResponse | null, pending, error }`.
- **Identity:** on a new conversation pick `customerId` uniformly at random from `["cust-001","cust-002","cust-003"]` (designer's call: per conversation, so different runs exercise different outcomes). Persist `{ sessionId, customerId }` in `sessionStorage` under a key that includes the Luma signed-in user id, so a page reload resumes via `getSession` (`SessionView.messages` + `latest`). If resume fails with 404/403, start fresh.
- **Session start:** create the session when the chat mounts (no existing session); the greeting is stored but the existing Luma welcome screen stays visible until the customer sends their first message (designer's call; avoids a greeting bubble above the welcome headline). After the first message the conversation shows greeting + messages.
- **Sending:** one request at a time; `pending` drives the existing "Preparing…" indicator (text changed to "Luma is thinking…"); double submissions are ignored while pending. After each response append `response.messages` (assistant) and the customer's own message locally (customer messages are not echoed in `TurnResponse`; on resume they come from `SessionView`).
- **End chat:** the existing "End chat & start fresh" dialog starts a new orchestrator session with a new random customer (the old one stays stored server-side; nothing is deleted).
- **Errors:** retryable errors show an inline note with a Retry button that resends the same request; `409 session_busy` retries once automatically after 1 s; non-retryable errors show the message. Never resend a confirmation automatically.

### 6.4 Frontend: rendering (`apps/customer/src/components/orchestrator/`)
- `assistant-workspace.tsx` switches from `useDemo().command("/chat")` / `snapshot.messages` to `useOrchestratorChat` for the conversation. It keeps `useDemo()` only for the customer's first name in the welcome headline and the `ContextPanel`.
- Message list: customer bubbles (right, existing style), assistant bubbles (existing style; label "LUMA · AI ASSISTANT"), with `citations` rendered as a small sources line (title + link; reuse `sources.tsx` styling if compatible, else a small new component).
- `ProgressSteps`: from `latest.progress.steps` (done/current/todo); side stages (`not_eligible`, `manual_review`, `escalated`) shown as a status pill. Hidden when `progress.flow` is `none`.
- Blocks, rendered under the latest assistant message, by `type` (unknown types ignored):
  - `document_checklist`: items with status; for `requested`/`rejected` items whose `doc_type` is in `awaiting.document_types`, an Upload button (file input accepting `.pdf,.jpg,.jpeg,.png`); rejected items show `rejection_reason`.
  - `extracted_fields`: label, value, source, confidence; fields with `needs_confirmation` or `conflict_with` show buttons that send a chat message (e.g. "Da, folosește valoarea din document" / "Yes, use the document value") — designer's call: confirmations go through the chat because the API confirms fields via the model's field updates, not a dedicated endpoint.
  - `eligibility_result`: status + reasons, labelled "Preliminary · simulated".
  - `offers`: one card per offer (term, monthly installment, total cost, total repayment, assumptions collapsed); Choose button calls `selectOffer` (enabled when `awaiting.kind === "offer_choice"`); selected offer highlighted.
  - `application_summary`: summary fields, documents, chosen offer; buttons "Confirm & submit for human review" and "Not yet" → `confirm(summary.summary_version, "confirm"|"decline")`, enabled only when `awaiting.kind === "confirmation"` and `awaiting.summary_version === summary.summary_version`.
  - `application_submitted`: reference id + status `PENDING_HUMAN_REVIEW`, text "Submitted for human review — no decision yet".
  - `escalation`: ticket id + message.
- Blocks belong to the latest response only (they reflect current state); older assistant messages show text + citations only.
- The welcome `StartingCards` stay; selecting one sends its text to the orchestrator. The "Back to options" footer button is removed (no orchestrator equivalent). The `?topic=` deep links from the dashboard keep working by sending the mapped text to the orchestrator.
- Old demo-only cards (`LoanSimulator`, `RefinanceSimulator`, `RepaymentSimulator`, `LoanDetails`, demo `ApplicationCard` inside chat) are no longer rendered in the chat; their components stay in the codebase (other pages may use them).
- Footer note changes to "Synthetic data · simulated, based on public conditions".

### 6.5 Running
- `scripts/frontend-dev.mjs` prints the orchestrator URL hint but does not start Python (designer's call: Python env differs per machine). README/`contracts/http/README.md` get a short "Luma + orchestrator" section: start the orchestrator (real or mock), then `npm run dev`.

### 6.6 Testing
- Backend: CORS tests (6.1).
- Frontend unit: client tests (6.2); hook logic tested through pure reducer/helpers where practical.
- E2E (Playwright, existing `tests/e2e/`): one journey against the orchestrator in mock mode with `session_store=memory` — sign in, send "Vreau un credit", reach a checklist, upload a file, see blocks update. The Playwright config starts the orchestrator via its `webServer` list if that's straightforward; otherwise the test is skipped when :8000 is unreachable and the run instructions say to start it. Existing e2e journeys that relied on the scripted demo chat must be updated or replaced, not deleted silently.
- Manual: real-mode smoke via the UI.

## 7. Designer's calls (owner may override)
- Random customer per conversation (not per sign-in).
- Session created on mount; greeting hidden behind the welcome screen until the first message.
- Field confirmations and conflict resolution via chat messages (no dedicated endpoint exists).
- Blocks rendered only under the latest assistant message.
- Python orchestrator not auto-started by `npm run dev`.
- "Back to options" removed; demo simulators no longer shown in chat.
- sessionStorage key: `luma-orchestrator-chat-v1-${snapshot.customer.id}`.
- Confirmation/conflict buttons send English text ("Yes, use the document value", "Yes, that's correct"); the model understands both languages.

## 8. Left to the builder
Exact component split and names, styling details within the existing visual language, the reducer shape, how amounts are formatted, Playwright `webServer` wiring details, wording of small UI labels (English).
