# Luma Chat on the Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Luma customer chat (:3000) talks to the AI orchestrator (:8000, `/chat/sessions/...`) and renders its replies, progress and blocks, while the rest of Luma keeps using the demo API.

**Architecture:** FastAPI gets a settings-driven CORS allow-list. The frontend gets a typed orchestrator client and a pure reducer + React hook in `@banking/demo`, and new chat components in `apps/customer/src/components/orchestrator/` that render `TurnResponse` blocks. `assistant-workspace.tsx` swaps its conversation source; sign-in, snapshot and the context panel stay on the demo API.

**Tech Stack:** Python/FastAPI (`CORSMiddleware`), TypeScript, React 19, Next.js 16 (client components only), Tailwind, `@banking/ui`, `lucide-react`, `tsx --test` (node:test), Playwright.

**Spec:** `docs/superpowers/specs/2026-10-28-luma-orchestrator-chat-design.md`. Wire contract: `contracts/http/README.md` + `contracts/http/chat.openapi.yaml` (authoritative for every field name).

## Global Constraints

- Branch `feat/luma-orchestrator-chat`. Never commit on `main`. Commit format per `GIT_AGENT_PROTOCOL.md` (`agent(frontend): ...` or `agent(orchestrator): ...`, Details/Status/Next lines), ending with exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Stage by explicit path; never commit `.superpowers/`, `.frontend-dev.log`, `.orchestrator.log`, `data/local/`.
- Python: `C:/Users/vladb/Documents/Hackathon/MergeConflict/.venv/Scripts/python.exe`. Node 22, npm workspaces; `npm test` = `tsx --test packages/banking/test/*.test.ts`; `npm run typecheck`; `npm run lint`.
- Next.js in this repo has breaking changes vs. common knowledge: read `node_modules/next/dist/docs/` before Next-specific code (`apps/customer/AGENTS.md`). Only `"use client"` React components are needed here.
- Orchestrator base URL: `process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ?? "http://127.0.0.1:8000"`. Synthetic customers: `["cust-001", "cust-002", "cust-003"]`, one picked uniformly at random per conversation.
- CORS default origins: `http://127.0.0.1:3000`, `http://127.0.0.1:3001`; env `ORCHESTRATOR_CORS_ORIGINS` (comma-separated); methods `GET, POST, OPTIONS`; headers `Content-Type, X-Customer-Id`; no credentials.
- Money and amounts are decimal strings from the API; never `parseFloat` for display.
- Confirm button sends exactly the `summary.summary_version` on screen, and only when `awaiting.kind === "confirmation"` and `awaiting.summary_version` matches. Never resend a confirmation automatically.
- UI copy is English. Footer note: "Synthetic data · simulated, based on public conditions". No UI text may imply approval or a Raiffeisen offer.
- sessionStorage key: `luma-orchestrator-chat-v1-${customerId}` where `customerId = snapshot.customer.id` (the Luma user), value `{ sessionId, customerId: "cust-00X" }`.
- Uploads accept `.pdf,.jpg,.jpeg,.png`.

## Review Focus

1. **Orchestrator not running** (customer opens Luma with :8000 down): the chat shows a clear inline message with a Retry button telling them to start the orchestrator; no crash, no blank screen. Test: `client maps network failure to unavailable` (Task 2) + manual check (Task 6).
2. **Reload mid-application** (customer refreshes on the documents step): the conversation and current blocks come back from `GET /chat/sessions/{id}`; a stale/foreign session (404/403) silently starts fresh. Test: `reducer resumes from SessionView` and `resume falls back on 404` (Task 3).
3. **Double click on Send / Confirm / Choose**: only one request goes out while one is pending. Test: `hook ignores sends while pending` (Task 3, via reducer/guard helper).
4. **Stale confirmation** (summary changed after it was shown): the Confirm button is disabled unless `awaiting.summary_version === summary.summary_version`. Test: `canConfirm` helper test (Task 3).
5. **Unknown block types or new fields** from a newer backend: ignored, no crash. Test: `client tolerates unknown block types` (Task 2).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/core/settings.py`, `src/api/app.py`, `.env.example` (modify) | CORS setting + middleware |
| `tests/integration/orchestrator/test_cors.py` | CORS tests |
| `packages/banking/src/orchestrator.ts` | wire types + HTTP client |
| `packages/banking/src/orchestrator-state.ts` | pure reducer and helpers (no React) |
| `packages/banking/src/orchestrator-react.tsx` | `useOrchestratorChat` hook |
| `packages/banking/package.json` (modify) | export `./orchestrator-react` |
| `packages/banking/test/orchestrator.test.ts`, `orchestrator-state.test.ts` | unit tests |
| `apps/customer/src/components/orchestrator/*.tsx` | message list, progress, block components |
| `apps/customer/src/components/assistant-workspace.tsx` (modify) | use the hook + new components |
| `playwright.config.ts`, `tests/e2e/frontend.spec.ts` (modify) | orchestrator mock web server; updated journeys |
| `README.md`, `contracts/http/README.md`, `scripts/frontend-dev.mjs` (modify) | run instructions |

---

### Task 1: Backend CORS allow-list

**Files:** Modify `src/core/settings.py`, `src/api/app.py`, `.env.example`; Test `tests/integration/orchestrator/test_cors.py`

**Interfaces — Produces:** `OrchestratorSettings.cors_origins: list[str]` (defaults per Global Constraints); `load_orchestrator_settings` reads `ORCHESTRATOR_CORS_ORIGINS` (split on `,`, strip, drop empty).

- [ ] **Step 1: Write failing tests**

```python
def test_preflight_allowed_origin():
    r = client.options("/chat/sessions", headers={"Origin": "http://127.0.0.1:3000",
        "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-customer-id,content-type"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert "x-customer-id" in r.headers["access-control-allow-headers"].lower()

def test_disallowed_origin_gets_no_cors_header():
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers

def test_cors_origins_env_parsing():
    s = load_orchestrator_settings({"ORCHESTRATOR_CORS_ORIGINS": "http://a:1, http://b:2,"})
    assert s.cors_origins == ["http://a:1", "http://b:2"]

def test_cors_default_origins():
    assert load_orchestrator_settings({}).cors_origins == ["http://127.0.0.1:3000", "http://127.0.0.1:3001"]
```
(`client` = `TestClient(create_app(OrchestratorSettings(model="fake", session_store="memory", ...)))` with uploads under the gitignored `.test_tmp` pattern used in `test_chat_api.py`.)

- [ ] **Step 2:** `"$PY" -m pytest tests/integration/orchestrator/test_cors.py -v` → FAIL.
- [ ] **Step 3: Implement** the setting, env parsing and `app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET","POST","OPTIONS"], allow_headers=["Content-Type","X-Customer-Id"], allow_credentials=False)` in `create_app`. Add `ORCHESTRATOR_CORS_ORIGINS=http://127.0.0.1:3000,http://127.0.0.1:3001` to `.env.example`.
- [ ] **Step 4:** Run the test file, then `"$PY" -m pytest tests -q` → all pass except main's known eligibility OpenAPI drift test (FastAPI version; pre-existing). The chat contract drift tests must pass (middleware doesn't change the schema).
- [ ] **Step 5: Commit** (`agent(orchestrator): allow Luma origins via CORS`).

---

### Task 2: Typed orchestrator client

**Files:** Create `packages/banking/src/orchestrator.ts`; Test `packages/banking/test/orchestrator.test.ts`

**Interfaces — Produces:**
- Types mirroring `contracts/http/chat.openapi.yaml` exactly (field names snake_case as on the wire): `CitationRef`, `ChatMessageView`, `AwaitingKind`, `Awaiting`, `ProgressStep`, `Progress`, `Money { amount: string; currency: string }`, `LoanOffer`, `EligibilityResult`, `DocumentChecklistItem`, `ExtractedFieldView`, `SummaryField`, `ApplicationSummary`, block interfaces `DocumentChecklistBlock | ExtractedFieldsBlock | EligibilityResultBlock | OffersBlock | ApplicationSummaryBlock | ApplicationSubmittedBlock | EscalationBlock` as `KnownBlock`, plus `UnknownBlock { type: string }`; `Block = KnownBlock | UnknownBlock`; `TurnResponse`, `SessionView`, `ErrorBody`.
- `class OrchestratorError extends Error { status: number; code: string; retryable: boolean }`.
- `createOrchestratorClient(customerId: string, baseUrl = ORCHESTRATOR_URL, fetchImpl: typeof fetch = fetch)` returning `{ createSession(): Promise<TurnResponse>; sendMessage(sessionId, text): Promise<TurnResponse>; uploadDocument(sessionId, docType, file: Blob, filename: string): Promise<TurnResponse>; selectOffer(sessionId, offerId): Promise<TurnResponse>; confirm(sessionId, summaryVersion, decision: "confirm" | "decline"): Promise<TurnResponse>; getSession(sessionId): Promise<SessionView> }`.
- Every request sends `X-Customer-Id`; JSON bodies send `Content-Type: application/json`; upload sends `FormData` with `doc_type` and `file` (no manual Content-Type). Timeout 60 s via `AbortSignal.timeout(60000)` (model turns can take several seconds).
- Error mapping: non-2xx with `ErrorBody` → `OrchestratorError(status, code, retryable, message)`; non-JSON error → `code "request_failed"`, `retryable` = status ≥ 500; network failure/timeout → `status 0, code "unavailable", retryable true`, message `"The AI assistant service is not reachable. Start it with: uvicorn src.api.app:create_app --factory"`.
- `isKnownBlock(block): block is KnownBlock` type guard over the 7 type strings.

- [ ] **Step 1: Write failing tests** using `node:test` + a local `http.createServer` fake on an ephemeral port (follow `packages/banking/test/api.test.ts` style):

```ts
test("sends X-Customer-Id and JSON body", ...)        // server records headers/body for sendMessage
test("upload sends multipart doc_type and file", ...)  // parse content-type boundary; fields present
test("maps ErrorBody to OrchestratorError", ...)       // 503 {code:"service_unavailable",retryable:true}
test("client maps network failure to unavailable", ...) // closed port → status 0, code "unavailable"
test("client tolerates unknown block types", ...)      // response with {type:"future_block"} parses; isKnownBlock false
test("confirm sends summary_version and decision", ...)
```

- [ ] **Step 2:** `npm test` → new tests FAIL.
- [ ] **Step 3: Implement** `orchestrator.ts`.
- [ ] **Step 4:** `npm test` and `npm run typecheck` → pass.
- [ ] **Step 5: Commit** (`agent(frontend): add typed orchestrator chat client`).

---

### Task 3: Chat state reducer and React hook

**Files:** Create `packages/banking/src/orchestrator-state.ts`, `packages/banking/src/orchestrator-react.tsx`; Modify `packages/banking/package.json` (add `"./orchestrator-react": "./src/orchestrator-react.tsx"` to `exports`); Test `packages/banking/test/orchestrator-state.test.ts`

**Interfaces — Consumes:** Task 2 client and types. **Produces:**
- `SYNTHETIC_CUSTOMERS = ["cust-001", "cust-002", "cust-003"] as const`; `pickCustomer(random = Math.random): string`.
- `interface ChatEntry { id: string; role: "customer" | "assistant"; text: string; citations: CitationRef[] }`.
- `interface ChatState { sessionId: string | null; customerId: string | null; entries: ChatEntry[]; latest: TurnResponse | null; pending: boolean; error: OrchestratorError | null; lastAction: PendingAction | null }` where `PendingAction` = `{ kind: "message"; text } | { kind: "upload"; docType; file; filename } | { kind: "offer"; offerId } | { kind: "confirm"; summaryVersion; decision } | { kind: "start" }`.
- `initialChatState`; `chatReducer(state, event)` with events: `started(customerId, response)`, `resumed(customerId, sessionId, view: SessionView)`, `requested(action, localEntry?: ChatEntry)`, `succeeded(response)`, `failed(error)`, `reset()`. `requested` with a message action appends the customer's own entry immediately; `succeeded` appends `response.messages` as assistant entries and replaces `latest`.
- Helpers: `canSend(state)` (not pending and sessionId set); `canConfirm(state, summary: ApplicationSummary)` per Global Constraints; `hasCustomerMessages(state)` (drives the welcome screen); `storageKey(lumaCustomerId)`.
- `useOrchestratorChat(lumaCustomerId: string | undefined)` returning `{ state, send(text): Promise<boolean>, upload(docType, file: File): Promise<boolean>, chooseOffer(offerId), confirm(summaryVersion, decision), retry(), restart() }`:
  - On mount with `lumaCustomerId`: read sessionStorage; if present, `getSession` → `resumed`; on 404/403 or parse failure, clear and start fresh. Otherwise `pickCustomer()`, `createSession` → `started`, persist.
  - All actions no-op (return false) when `!canSend(state)`; a `useRef` lock guards against same-tick double calls.
  - `409 session_busy`: retry once after 1000 ms automatically (not for confirm). Other errors → `failed`.
  - `retry()` re-runs `lastAction` except a confirm (confirm must be clicked again).
  - `restart()` clears storage and starts a new session with a new random customer.

- [ ] **Step 1: Write failing reducer/helper tests:**

```ts
test("pickCustomer covers all three", ...)          // random=()=>0 → cust-001, 0.5 → cust-002, 0.99 → cust-003
test("requested message appends customer entry and sets pending", ...)
test("succeeded appends assistant messages and replaces latest", ...)
test("reducer resumes from SessionView", ...)       // entries from view.messages, latest = view.latest
test("hook ignores sends while pending", ...)       // canSend false while pending
test("canConfirm requires matching summary_version and confirmation awaiting", ...)
test("hasCustomerMessages false when only the greeting exists", ...)
test("resume falls back on 404", ...)               // pure helper deciding fresh-start on OrchestratorError 404/403
```

- [ ] **Step 2:** `npm test` → FAIL.
- [ ] **Step 3: Implement** state module, hook and package export.
- [ ] **Step 4:** `npm test`, `npm run typecheck` → pass.
- [ ] **Step 5: Commit** (`agent(frontend): add orchestrator chat state and hook`).

---

### Task 4: Chat rendering components

**Files:** Create in `apps/customer/src/components/orchestrator/`: `conversation.tsx` (message list + citations), `progress-steps.tsx`, `blocks.tsx` (dispatch by `type`), `document-checklist-block.tsx`, `extracted-fields-block.tsx`, `offers-block.tsx`, `summary-block.tsx`, `status-blocks.tsx` (eligibility, submitted, escalation). Split differently if cleaner; keep each file focused.

**Interfaces — Consumes:** Task 2 types, Task 3 `ChatState` + hook actions. **Produces:**
- `<OrchestratorConversation state onUpload onChooseOffer onConfirm onSend disabled />`: renders `state.entries` (customer right bubble in the existing `bg-ink` style; assistant bubble in the existing `bg-slate-50` style with label "LUMA · AI ASSISTANT"); citations as small chips (title, opens `url` in a new tab; publisher shown); blocks of `state.latest` rendered under the last assistant entry only.
- `<ProgressSteps progress />`: hidden when `progress.flow === "none"`; steps done/current/todo with human labels (Discovery, Your details, Eligibility, Documents, Offers, Confirm, Submitted); side stages `not_eligible`/`manual_review`/`escalated` as a status pill ("Not eligible (preliminary)", "Manual review", "With a human").
- Block behaviour exactly as spec §6.4: upload buttons only for doc types in `awaiting.document_types` (hidden `<input type="file" accept=".pdf,.jpg,.jpeg,.png">`); extracted fields show source + confidence and, when `needs_confirmation` or `conflict_with`, buttons that call `onSend("Yes, that's correct")` / `onSend("Yes, use the document value")`; offers cards with Choose enabled only when `awaiting.kind === "offer_choice"`; summary Confirm/Not yet using `canConfirm`; submitted block text "Submitted for human review — no decision yet"; eligibility labelled "Preliminary · simulated, based on public conditions"; unknown blocks ignored via `isKnownBlock`.
- Accessible names (used by e2e): buttons "Upload {label}", "Choose {term_months}-month offer", "Confirm & submit for human review", "Not yet"; progress region `aria-label="Application progress"`.
- Reuse `@banking/ui` `Button`, `InfoNote`, `AssistantAvatar` and Tailwind tokens already used in `assistant-workspace.tsx` / `rich-response.tsx`.

- [ ] **Step 1:** No React unit-test infra exists; verification is typecheck + lint here and Playwright in Task 5. Write the components.
- [ ] **Step 2:** `npm run typecheck` and `npm run lint` → pass with no new warnings.
- [ ] **Step 3: Commit** (`agent(frontend): render orchestrator turns and blocks in Luma`).

---

### Task 5: Wire the workspace and update e2e

**Files:** Modify `apps/customer/src/components/assistant-workspace.tsx`, `playwright.config.ts`, `tests/e2e/frontend.spec.ts`

**Interfaces — Consumes:** Tasks 3–4.
- `AssistantWorkspace`: conversation from `useOrchestratorChat(snapshot?.customer.id)`; keeps `useDemo()` only for `snapshot.customer.name` (welcome headline) and `ContextPanel`. Welcome screen shown while `!hasCustomerMessages(state)`; `StartingCards` send their text via the hook; `?topic=` deep links send their mapped text via the hook (once the session exists). Remove the "Back to options" button. "End chat & start fresh" calls `restart()`. Pending indicator text "Luma is thinking…". Error: inline `InfoNote` with the error message and a "Retry" button (`retry()`) when `retryable`. Footer note per Global Constraints. `RichResponse` is no longer used by the workspace (leave the file; other pages may import pieces).
- `playwright.config.ts`: add a webServer entry for the orchestrator in mock mode: command `${process.env.ORCHESTRATOR_PYTHON ?? "python"} -m uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port 8000`, url `http://127.0.0.1:8000/health`, env `ORCHESTRATOR_MODEL=fake`, `ORCHESTRATOR_SESSION_STORE=memory`, `ORCHESTRATOR_UPLOADS_DIR=data/local/e2e-uploads-${Date.now()}`, `reuseExistingServer: false`, timeout 60000.
- e2e changes:
  - Replace the journey "desktop guided assistant, free text, loan changes and existing information" with "assistant runs on the orchestrator": sign in → welcome visible → send "Vreau un credit de 30000 lei pe 60 de luni pentru renovare" → an assistant bubble appears and `Application progress` is visible → continue answering (mock demo model flows; drive with the messages the contract README/e2e scenario use) until "Upload …" buttons appear → upload a small generated PDF buffer for one requested type → checklist shows it accepted → "End chat" dialog → welcome visible again → no page errors. Because the customer is random, assert only on steps every customer reaches (welcome, assistant reply, progress, the first upload) — or set the customer deterministically in the test via `sessionStorage` before load (`luma-orchestrator-chat-v1-<luma id>` with a pre-created session for `cust-001`), whichever is simpler; document the choice in the test.
  - The journey "customer submission, reviewer information request, …" starts its demo application from the Products page (`/products`, existing `LoanSimulator` → "Choose scenario & prepare application") instead of through the chat; everything after stays the same.
  - Other journeys unchanged; fix only what the chat change breaks.

- [ ] **Step 1:** Update e2e first so the new journey fails against the old chat; run `ORCHESTRATOR_PYTHON=<venv python> npx playwright test` → the new journey FAILS. (Stop any dev servers on 3000/3001/4010/8000 first; the config starts its own.)
- [ ] **Step 2:** Implement the workspace changes.
- [ ] **Step 3:** `npm run typecheck`, `npm run lint`, `npm test`, then the Playwright suite → all pass. Record pass counts.
- [ ] **Step 4: Commit** (`agent(frontend): run the Luma chat on the orchestrator`).

---

### Task 6: Docs and manual check

**Files:** Modify `README.md` (Luma + orchestrator section), `contracts/http/README.md` (CORS note), `scripts/frontend-dev.mjs` (print `AI orchestrator: http://127.0.0.1:8000/docs (start separately: uvicorn src.api.app:create_app --factory)`).

- [ ] **Step 1:** Write the docs: start the orchestrator (real or `ORCHESTRATOR_MODEL=fake`), then `npm run dev`; `NEXT_PUBLIC_ORCHESTRATOR_URL`; `ORCHESTRATOR_CORS_ORIGINS`; that each chat picks a random synthetic customer.
- [ ] **Step 2: Manual check:** with the orchestrator in real mode and `npm run dev`, sign in at :3000, send a product question and a credit request; confirm replies render, progress appears, and stopping the orchestrator shows the unavailable message with Retry. Record what you saw.
- [ ] **Step 3: Commit** (`agent(frontend): document running Luma with the orchestrator`), Status COMPLETED.
