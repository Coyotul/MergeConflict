# Documents First, One Review Form Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Documents fill every document-verified field; the customer reviews all extracted values in one form (only name/employer editable) instead of confirming field by field in chat.

**Architecture:** `next_needs` stops asking for `verified_by` fields, puts documents before eligibility, and replaces per-field confirm/conflict needs with one `review_extracted` need. A code-handled `ExtractedFieldsReviewed` event (new endpoint) applies allowed edits and confirms everything. The existing `extracted_fields` block gains `editable` per field and the awaiting kind `review_form`.

**Tech Stack:** Python/FastAPI/pydantic, pytest; Next.js customer app, packages/banking TS.

**Spec:** `docs/superpowers/specs/2026-10-29-document-review-form-design.md`

## Global Constraints

- Editable fields: exactly `full_name`, `employer_name` (`editable: true` in `config/orchestrator/requirements.yaml`, all products). Every other field is read-only in the form.
- Needs order: discovery/product → missing fields without `verified_by` → documents → `review_extracted` → eligibility → offers → submission.
- Edits to read-only/unknown fields → 422, nothing written.
- Python tests: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp=.pytest_tmp`.

## Review Focus

- Edit to `monthly_net_income` via the endpoint → 422, value unchanged. (Task 1 test)
- Form submitted before all documents are accepted → rejected, nothing confirmed. (Task 1 test)
- Edited editable value fails parsing (empty name) → 422. (Task 1 test)
- A document re-uploaded after the form was confirmed → form shown again. (Task 1 test)
- Model turn while documents pending → context has only document needs. (Task 1 test)

---

### Task 1: Backend — needs order, review event, endpoint

**Files:**
- Modify: `src/models/credit.py:38` (`FieldSpec.editable: bool = False`), `config/orchestrator/requirements.yaml`
- Modify: `src/agent/orchestration/progress.py` (`NeedKind.review_extracted`; remove `confirm_extracted`/`resolve_conflict` emission; group 4 skips specs with `verified_by`; documents before eligibility; `review_extracted` when any document-sourced field is unconfirmed; `Stage` mapping: `review_extracted` → documents stage)
- Modify: `src/models/chat.py` (`ExtractedFieldView.editable: bool`, `document_type: str | None`; `AwaitingKind.review_form`; `ExtractedFieldsReviewRequest {edits: dict[str, str]}`)
- Modify: `src/agent/orchestration/blocks.py` (`_extracted_fields` sets `editable`, `document_type`; awaiting `review_form` when first need is `review_extracted`)
- Modify: `src/agent/orchestration/events.py` (`ExtractedFieldsReviewed(edits: dict[str, str])`, `_handle_fields_reviewed`), `orchestrator.py` dispatch, `turn_trace.py` event summary, `src/api/application/chat.py` route `POST /chat/sessions/{id}/extracted-fields`
- Modify: `src/agent/prompts/orchestrator_system.md` (remove per-field confirm rules + example 3; add: during documents only talk about documents; the form handles review)
- Test: `tests/unit/orchestrator/test_review_form.py`

**Interfaces:** `ExtractedFieldsReviewed(edits)`; handler: if first need != `review_extracted` → fixed reply `event_text("review_not_ready")`, nothing changed; unknown/read-only field in edits → raise `InvalidFieldEdit` (422 via app handler); else apply edits (`parse_field_value`, `source=customer, confirmed=True`), confirm remaining document fields, clear conflicts, add event message `FIELDS_REVIEWED`, then `_explain` (model continues → eligibility).

- [ ] **Step 1: Failing tests:** `test_documents_requested_without_asking_document_fields`; `test_pending_documents_are_the_only_needs`; `test_form_offered_after_all_documents_accepted` (awaiting `review_form`, editable flags exactly name/employer); `test_review_confirms_values_and_applies_allowed_edit`; `test_edit_to_read_only_field_is_refused`; `test_review_before_documents_is_rejected`; `test_reupload_after_review_reopens_form`.
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `agent(orchestrator): documents fill fields; one review form replaces per-field confirmation`

### Task 2: Demo model, contract, existing tests

- Modify: `src/agent/orchestration/demo_model.py` (no `confirm_extracted` handling; `review_extracted` reply text points to the form), `scripts/export_chat_contract.py` (happy path: discovery answers only, three uploads, `("review", None)` posting `{edits: {}}`, select offer, agree), regenerate contracts.
- Modify tests that assumed field questions before documents or per-field confirmation (`test_events.py`, `test_progress.py`, `test_orchestrator.py`, `test_prompting.py`, integration orchestrator tests, `tests/fixtures`).
- [ ] **Step 1:** full Python suite → all pass (credit-source DB present); contract test passes.
- [ ] **Step 2: Commit** `agent(orchestrator): demo model, contract and tests for the review form`

### Task 3: Customer app form

- Modify: `packages/banking/src/orchestrator.ts` (`editable`, `document_type`, `review_form`, client `reviewExtractedFields(sessionId, edits)`), `orchestrator-state.ts`/`orchestrator-react.tsx` (`{kind: "review"; edits}` action + `reviewFields`), `apps/customer/src/components/orchestrator/extracted-fields-block.tsx` (form: read-only rows, inputs for editable rows, single OK; shown as form only when awaiting `review_form`), wire through `blocks.tsx` / `conversation.tsx` / `assistant-workspace.tsx`.
- [ ] **Step 1:** `npm run typecheck -w @banking/customer -w @banking/demo` clean; `npx tsx --test packages/banking/test/*.test.ts` pass
- [ ] **Step 2: Drive it:** restart servers, run the chat as Alex through uploads to the form via API, `curl` the form endpoint.
- [ ] **Step 3: Commit** `agent(customer): one review form for extracted document values`
