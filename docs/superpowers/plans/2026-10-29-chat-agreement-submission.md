# Submission by Chat Agreement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The orchestrator model submits via a guarded `submit_application` tool after explicit agreement in chat; the summary card and confirmation endpoint are removed.

**Architecture:** The model calls `submit_application({customer_agreement})`; the orchestrator intercepts that call, checks the guards, runs the existing code submission path (save before any model call, fixed reply), and ends the turn. The confirmation event, route and wire summary block go away.

**Tech Stack:** Python/FastAPI/pydantic, pytest; Next.js customer app.

**Spec:** `docs/superpowers/specs/2026-10-29-chat-agreement-submission-design.md`

## Global Constraints

- Guards (all server-side): next need is `confirm_submission` with a current summary; the turn was started by a `CustomerMessage`; `customer_agreement` non-empty and contained in that message (case- and whitespace-insensitive). Failure → tool result `precondition_failed`, nothing written.
- Idempotency key stays `session_id:summary_version`; ids are server-filled.
- Successful submission reply is the existing fixed `event_text("submitted", ...)`.
- Python tests: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp=.pytest_tmp`.

## Review Focus

- Model calls the tool on an upload/offer-selection turn → refused. (Task 1 test)
- Customer says "no" / asks a question, model still calls with invented words → refused. (Task 1 test)
- Terms changed after being shown (stale summary) → refused. (Task 1 test)
- Tool called twice in one turn → one application. (Task 1 test)
- Model call while already submitted → fixed "submitted" text, no second application. (Task 1 test)

---

### Task 1: Guarded model-callable submission

**Files:**
- Modify: `src/agent/tools/contracts.py:181` (`SubmitApplicationInput`: `customer_agreement: str`, `application_id: str | None = None`, `idempotency_key: str | None = None`), `src/agent/tools/stubs.py` (`model_callable=True`; snapshot gains `"customer_agreement"`; missing key → `ToolUnavailable`)
- Modify: `src/agent/orchestration/orchestrator.py` (`_Turn.customer_text: str | None`, set in `_handle_customer_message`; `_execute_model_tool` routes `submit_application` to new `_submit_from_model(turn, arguments) -> ToolCallOutcome`; `_run_model_steps` stops and returns True when `turn.submitted` is set)
- Modify: `src/agent/prompts/orchestrator_system.md:65,136` (submission rules)
- Test: `tests/unit/orchestrator/test_submission_by_agreement.py`

- [ ] **Step 1: Failing tests** (scripted FakeChatModel via `orchestrator_factory`, session seeded at `confirm_submission` with `seed_application` + verified app + selected offer):
  `test_explicit_agreement_submits_with_fixed_reply` (customer "Da, trimite cererea", model calls tool with `customer_agreement="Da, trimite cererea"` → `application_id` set, reply == fixed submitted text, review store snapshot `customer_agreement` saved);
  `test_agreement_not_in_customer_message_is_refused`; `test_tool_refused_on_upload_turn`; `test_tool_refused_when_not_at_confirmation`; `test_second_call_in_same_turn_does_not_duplicate`.
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `agent(orchestrator): model submits only after explicit agreement in chat`

### Task 2: Remove the summary card and confirmation path

**Files:**
- Delete: `ConfirmationDecision` (events.py + orchestrator dispatch), `_handle_confirmation`, `POST /chat/sessions/{id}/confirmation` and `ConfirmationRequest` (`src/api/application/chat.py`, `src/models/chat.py`), `ApplicationSummaryBlock` emission (`src/agent/orchestration/blocks.py`); awaiting kind at `awaiting_confirmation` → `text`.
- Delete: `apps/customer/src/components/orchestrator/summary-block.tsx` and its use in `blocks.tsx`; confirm action in `packages/banking/src/orchestrator-react.tsx`, `orchestrator-state.ts`, `orchestrator.ts` client method and block type.
- Modify: `src/agent/orchestration/demo_model.py` — at `confirm_submission`, on a yes-word customer message call `submit_application` with the customer text; `confirm_submission` prompt text asks to reply "yes" to submit.
- Modify: `scripts/export_chat_contract.py` happy path: final step `("say", "Da, trimite cererea")`; regenerate contracts.
- Modify tests that used `ConfirmationDecision`/confirmation route (`test_events.py`, `test_chat_api.py`, `test_document_tools_api.py`, `test_pricing_integration.py`, `test_trace_orchestrator.py`, `test_wire_models.py`, `test_orchestrator.py`, `test_progress.py`) to agree by message.

- [ ] **Step 1:** `grep -rn "ConfirmationDecision\|/confirmation\|application_summary" src apps packages/banking/src scripts` → only intended hits remain after edits
- [ ] **Step 2:** full Python suite → only the 3 known ANAF failures; contract test passes; `npm run typecheck -w @banking/customer -w @banking/demo` clean
- [ ] **Step 3: Commit** `agent(orchestrator): remove the summary card and confirmation endpoint`
