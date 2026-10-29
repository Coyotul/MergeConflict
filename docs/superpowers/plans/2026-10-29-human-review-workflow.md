# Human Review Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chat submissions become real applications that a human reviewer approves, rejects or requests a document for; the customer follows status and uploads requested documents on the Applications page.

**Architecture:** One new Python package `src/services/human_review/` (SQLite store, workflow service, requested-upload + recalculation) behind two new FastAPI routers on the existing app. The customer Applications page and the staff app are rebuilt on those routers through one small TS client. Tasks are ordered so the loop works end to end after Task 5; Tasks 6-8 can be dropped under time pressure.

**Tech Stack:** Python 3 / FastAPI / sqlite3 / pydantic, pytest; Next.js 16 + React 19 (apps/customer :3000, apps/staff :3001), packages/banking shared TS.

**Spec:** `docs/superpowers/specs/2026-10-29-human-review-workflow-design.md`

## Global Constraints

- Statuses exactly: `PENDING_HUMAN_REVIEW`, `MORE_INFORMATION_REQUIRED`, `APPROVED`, `REJECTED`. Customer labels: "Waiting for review", "More information needed", "Accepted", "Rejected".
- Transitions: `PENDING_HUMAN_REVIEW → APPROVED | REJECTED | MORE_INFORMATION_REQUIRED`; `MORE_INFORMATION_REQUIRED → PENDING_HUMAN_REVIEW` only via accepted upload. Others → 409.
- Database file: `data/local/applications.sqlite3` (path configurable; tests use tmp_path).
- Customer identity: `X-Customer-Id` header (same as chat). Reviewer identity: `X-Reviewer-Id` must equal `reviewer-demo`, else 403.
- Requestable doc types: `id_card`, `payslip`, `bank_statement`, and only types in the snapshot's requirements. One open request at a time.
- Every reviewer action requires a non-empty reason (customer-visible). No internal notes.
- No invented ids on storage failure: raise `ToolUnavailable`.
- Run Python tests with `.venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp=.pytest_tmp` (system temp is blocked); delete `.pytest_tmp` after.

## Review Focus

- Customer A requests customer B's application or uploads to B's request → 404, no data leak. (Task 4 test)
- Reviewer acts on a stale `version` or a final application → 409, nothing written. (Task 1 test)
- Upload of a different document type (ID card for a payslip request) → rejected with reason, status unchanged. (Task 3 test)
- Same chat submission confirmed twice (double click / retry) → one application. (Task 2 test)
- Upload when no request is open (already fulfilled) → 409. (Task 3 test)

---

### Task 1: Review store and state machine

**Files:**
- Create: `src/services/human_review/store.py`, `src/services/human_review/models.py`
- Modify: `src/services/human_review/__init__.py` (exports)
- Test: `tests/unit/human_review/test_store.py`

**Interfaces:**
- Produces (`models.py`): `ReviewStatus(StrEnum)` with the 4 statuses; `InvalidTransition(Exception)`, `StaleVersion(Exception)`, `NotFound(Exception)`; pydantic `HistoryEntry(from_status: str|None, to_status: str, actor: str, reason: str, at: datetime)`, `InfoRequest(id, doc_type, reason, status: Literal["open","fulfilled"], created_at, fulfilled_at, fulfilled_document_id)`, `ReviewDocument(document_id, doc_type, origin: Literal["chat","information_request"], status, extracted_fields: dict, validation: dict|None, sha256: str|None, uploaded_at, superseded_by: str|None)`, `ReviewApplication(id, reference, customer_id, session_id, product_code, status, version: int, snapshot: dict, current: dict, documents, history, requests, created_at, updated_at)`.
- Produces (`store.py`): `class ReviewStore(db_path: Path)` with
  - `create(*, idempotency_key, customer_id, session_id, product_code, snapshot: dict, documents: list[ReviewDocument], now) -> ReviewApplication` (returns existing on repeated key; writes history `None → PENDING_HUMAN_REVIEW`, actor `customer`, reason "Submitted from the assistant")
  - `get(app_id) -> ReviewApplication` (raises `NotFound`), `list(*, customer_id=None, status=None) -> list[ReviewApplication]`
  - `transition(app_id, *, to: ReviewStatus, actor, reason, expected_version: int|None, now, request_doc_type: str|None=None) -> ReviewApplication` (validates transition, bumps version, creates `InfoRequest` when `to == MORE_INFORMATION_REQUIRED`)
  - `fulfil_request(app_id, request_id, *, document: ReviewDocument, current: dict, now) -> ReviewApplication` (one transaction: supersede previous doc of type, add doc, mark request fulfilled, set `current`, transition to `PENDING_HUMAN_REVIEW` actor `system`)
- Schema created on open (`CREATE TABLE IF NOT EXISTS`): `applications`, `application_documents`, `application_history`, `information_requests` per spec; `snapshot`/`current`/`extracted_fields`/`validation` as JSON text. `id = "APP-" + secrets.token_hex(4).upper()`, `reference = "LN-" + yyyymmdd + 4 hex`.

- [ ] **Step 1: Write failing tests**

```python
def test_create_is_idempotent_and_starts_pending(store): a = make(store); b = make(store); assert a.id == b.id and a.status == "PENDING_HUMAN_REVIEW" and len(a.history) == 1
def test_request_information_opens_one_request(store): app = store.transition(make(store).id, to=ReviewStatus.MORE_INFORMATION_REQUIRED, actor="reviewer", reason="Newer payslip", expected_version=1, now=NOW, request_doc_type="payslip"); assert app.requests[0].status == "open" and app.version == 2
def test_final_status_rejects_further_transitions(store): approve then transition to REJECTED -> raises InvalidTransition
def test_stale_version_is_rejected(store): transition with expected_version=99 -> raises StaleVersion, app unchanged
def test_pending_cannot_be_set_by_reviewer_from_more_info(store): MORE_INFO -> transition(to=PENDING, actor="reviewer") raises InvalidTransition
def test_fulfil_request_supersedes_old_document_and_returns_to_pending(store): ... assert app.status == "PENDING_HUMAN_REVIEW", old.superseded_by == new.document_id, app.requests[0].status == "fulfilled", app.current == new_current
def test_list_filters_by_customer(store): two customers -> list(customer_id="customer-alex") returns only theirs
```

- [ ] **Step 2: Run** `... -m pytest tests/unit/human_review/test_store.py` → FAIL (module missing)
- [ ] **Step 3: Implement** `models.py` and `store.py` (sqlite3, `with conn:` transactions, row_factory Row). `MORE_INFORMATION_REQUIRED → PENDING_HUMAN_REVIEW` allowed only inside `fulfil_request`.
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `agent(human-review): sqlite review store and status machine`

### Task 2: Real chat submission

**Files:**
- Modify: `src/agent/tools/stubs.py:542-689` (replace `handle_submit_application`, `handle_get_status`), `build_stub_registry` signature
- Modify: `src/core/composition.py:117-123`, `src/core/settings.py` (add `review_db_path: Path = Path("data/local/applications.sqlite3")`)
- Test: `tests/unit/human_review/test_submission.py`

**Interfaces:**
- Consumes: `ReviewStore.create`, `ReviewStore.get`.
- Produces: `build_stub_registry(data, policy_search, *, document_service=None, review_store: ReviewStore | None = None)`. When `review_store` is None, submission raises `ToolUnavailable("Application storage is not configured.")`. Snapshot = `{"customer_id", "profile": data.customers[cid]["profile"], "application": state.application.model_dump(mode="json")}`; `current` initialised by the store to `{"application": snapshot["application"]}`. Documents = accepted `app.documents` as `ReviewDocument(origin="chat")`.
- `SubmitApplicationOutput(application_id=app.id, status=app.status, simulated=False)`. `get_application_status` maps `app.history` to `StatusEntry(status=to_status, at=...)`, `simulated=False`. Remove `submission_cache` and the fake-id fallback; sqlite errors → `ToolUnavailable`.

- [ ] **Step 1: Failing tests:** `test_submit_writes_real_application` (registry with tmp store, verified app from `tests/unit/orchestrator/factories.make_verified_app` + selected offer → output.simulated is False, store.get(id).snapshot["application"]["selected_offer_id"] set); `test_repeated_idempotency_key_returns_same_application`; `test_missing_store_raises_tool_unavailable`; `test_status_tool_reads_review_store` (after a transition, tool returns `MORE_INFORMATION_REQUIRED`).
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement**; wire `ReviewStore(settings.review_db_path)` in `build_orchestrator`; pass the same instance to `create_app` via `app.state.review_store` (build it once in `create_app` and pass into `build_orchestrator(settings, documents=..., review_store=...)`).
- [ ] **Step 4: Run** new tests + `tests/unit/orchestrator tests/integration/orchestrator` → only the 4 known pre-existing failures (see Task 7)
- [ ] **Step 5: Commit** `agent(human-review): chat submission creates a real review application`

### Task 3: Requested-upload validation and recalculation

**Files:**
- Modify: `src/agent/tools/documents.py` (extract acceptance)
- Create: `src/services/human_review/service.py`
- Test: `tests/unit/human_review/test_service.py`

**Interfaces:**
- Produces (`documents.py`): `assess_processed_document(doc_type: str, result: ProcessedDocumentResponse, *, profile: dict, required_fields: list[FieldSpec], today: date) -> ProcessDocumentOutput` — the body of `DocumentTools._output` with `ctx` replaced by these args; `_output` calls it. Existing `tests/unit/orchestrator/test_documents.py` must stay green.
- Produces (`service.py`): `class ReviewService(store: ReviewStore, documents: DocumentProcessingService, stub_data: StubData, clock)` with
  - `request_document(app_id, *, doc_type, reason, version) -> ReviewApplication` — validates doc_type ∈ {id_card,payslip,bank_statement} ∩ snapshot requirement doc types, non-empty reason, no open request; else `ValueError` (→ 422).
  - `decide(app_id, *, action: Literal["approve","reject"], reason, version) -> ReviewApplication`
  - `upload_requested(app_id, request_id, *, customer_id, filename, content: bytes, mime_type) -> tuple[ReviewApplication, UploadOutcome]`; `UploadOutcome(accepted: bool, reasons: list[str])`.
- Upload algorithm: ownership (`app.customer_id == customer_id` else `NotFound`); request must be open (else `InvalidTransition`); `validate_document_bytes`; `storage.store_document(customer_id=…, application_id=app_id, doc_kind=doc_type, …)`; `process_stored_document(..., allow_synthetic_cnp=False)`; `assess_processed_document` with requirements from `snapshot.application.requirements`; then `cross_validate_application` against current accepted docs of other types. **Rejected if** status != "accepted" **or** `human_review_required` **or** cross-check inconsistent/`human_review_required` (user decision: no reviewer escalation). Rejected message prefix for type mismatch: `"This doesn't look like the requested {label}."` when the extractor produced no required fields.
- Recalculation on accept: `state = SessionState(session_id=app.session_id, customer_id=app.customer_id, created_at=now, updated_at=now, active_flow=Flow.credit_application, application=ApplicationState.model_validate(current["application"]))`; for each extracted field set `FieldValue(source=document, confirmed=True, document_id=…)`; `ctx = ToolContext(state, now)`; `eligibility = assess_session_eligibility(ctx, stub_data)`; offers = `calculate_offers(CalculateOffersInput(term_options_months=None), ctx)`; pick offer with same `term_months` as the original selected offer (else first). New `current = {"application": state.application.model_dump(mode="json"), "eligibility": eligibility.model_dump(mode="json") if eligibility else None, "offer": offer.model_dump(mode="json") if offer else None, "pricing_errors": [...]}`. Store via `fulfil_request`.

- [ ] **Step 1: Failing tests** (real PDFs from `tests/fixtures/documents.py`, whose name "ANA POPESCU" matches customer `cust-001`):
  - `test_valid_payslip_fulfils_request_and_returns_to_pending` (status PENDING, request fulfilled, `current["application"]["fields"]["monthly_net_income"]["value"] == "7500.00"` for `income_text(net="7.500,00")`)
  - `test_accepted_upload_recalculates_eligibility_and_offer` (`current["eligibility"]` is not None; `current["offer"]["term_months"]` equals the snapshot's selected offer term; with `income_text(net="1.000,00")` `current["eligibility"]["status"] != "satisfied"` while the snapshot's stays satisfied)
  - `test_id_card_uploaded_for_payslip_request_is_rejected` (outcome.accepted False, reasons[0] startswith "This doesn't look like the requested", app status still MORE_INFORMATION_REQUIRED)
  - `test_fixed_term_payslip_needing_human_review_is_rejected_to_customer`
  - `test_upload_without_open_request_conflicts`
  - `test_other_customer_cannot_upload` (raises NotFound)
  - `test_request_type_not_in_requirements_is_refused`
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** extraction + service.
- [ ] **Step 4: Run** new tests + `tests/unit/orchestrator/test_documents.py` → PASS
- [ ] **Step 5: Commit** `agent(human-review): requested uploads validated and reassessed`

### Task 4: Customer and reviewer HTTP API

**Files:**
- Create: `src/api/application/reviews.py`
- Modify: `src/api/app.py` (build `ReviewStore`, `ReviewService`; include router; CORS `allow_headers += ["X-Reviewer-Id"]`; exception handlers `NotFound→404`, `InvalidTransition/StaleVersion→409`, `ValueError→422` scoped to the router)
- Test: `tests/integration/human_review/test_review_api.py`

**Interfaces (paths fixed here):**
- Customer: `GET /applications` → `{applications: [CustomerApplicationView]}`; `GET /applications/{id}`; `POST /applications/{id}/requests/{request_id}/document` (multipart `file`) → `{application, accepted, reasons}`.
  `CustomerApplicationView = {id, reference, product_code, status, status_label, amount, term_months, monthly_installment, dae, offer_updated: bool, history: [{to_status, status_label, reason, at}], open_request: {id, doc_type, reason}|null}` (amount/term/installment from `current.offer` falling back to snapshot offer).
- Reviewer: `GET /review/applications?status=` → summaries `{id, reference, customer_name, product_code, amount, status, updated_at}`; `GET /review/applications/{id}` → full `ReviewApplication` plus `changed_fields: [{field, before, after}]`; `POST /review/applications/{id}/decision` body `{action: "approve"|"reject"|"request_document", reason, version, doc_type?}`; `GET /review/applications/{id}/documents/{document_id}` → file bytes with stored mime type.
- Record the shapes in `contracts/http/reviews.md`.

- [ ] **Step 1: Failing tests** with `TestClient(create_app(settings))` and a store seeded through `ReviewStore.create`: list scoped by `X-Customer-Id`; other customer → 404 on GET and upload; reviewer header missing/wrong → 403; decision with stale version → 409; request_document then customer sees `open_request` and `status_label == "More information needed"`; approve → `status_label == "Accepted"`.
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** `agent(human-review): customer and reviewer review API`

### Task 5: Customer Applications page

**Files:**
- Create: `packages/banking/src/review-api.ts` (client: `listMyApplications(customerId)`, `uploadRequested(customerId, appId, requestId, file)`, `listQueue(status?)`, `getReview(id)`, `decide(id, body)`, `documentUrl(id, docId)`; base `NEXT_PUBLIC_ORCHESTRATOR_URL ?? "http://127.0.0.1:8000"`; reviewer header `reviewer-demo`), export path in `packages/banking/package.json` like the other `@banking/demo/*` entries.
- Modify: `apps/customer/src/app/applications/page.tsx` (rewrite), `apps/customer/src/components/customer-sidebar.tsx:21` (badge from new API), dashboard Applications panel (`apps/customer/src/app/dashboard/page.tsx`) and `context-panel.tsx:14`.
- Delete/replace: `apps/customer/src/components/application-card.tsx`, `document-checklist.tsx` → new `apps/customer/src/components/review-application-card.tsx` (status pill, offer terms + "Updated after review" when `offer_updated`, timeline with reasons, open-request box with reason + file input + inline accepted/rejected reasons).

**Interfaces:** customer id = `useDemo().snapshot.customer.id`. Poll `listMyApplications` every 5 s; refetch right after upload.

- [ ] **Step 1:** `npm run typecheck -w @banking/customer` passes after the rewrite (no unit test harness for components; e2e in Task 8).
- [ ] **Step 2: Manual check:** run API + customer app, submit in chat as Alex Morgan, see "Waiting for review" on /applications.
- [ ] **Step 3: Commit** `agent(human-review): applications page on the review API`

### Task 6: Staff review app

**Files:**
- Modify: `apps/staff/src/app/page.tsx` (queue on `listQueue`: counts per status, status filter, search), `apps/staff/src/app/applications/[id]/page.tsx`, `apps/staff/src/components/review-detail.tsx`, `review-detail-sections.tsx`, `evidence-panel.tsx`, `review-actions.tsx` (rewrite on `getReview` / `decide`; sections: applicant, fields with source+confidence and `changed_fields` highlighted, documents with validation + link to `documentUrl`, eligibility original vs current, offer original vs current, history; actions: approve / reject / request document (select of allowed types), required reason, sends `version`, shows 409 message "This application changed; reload.").
- Delete: `apps/staff/src/app/audit/`, its nav entry in `staff-shell.tsx`.

- [ ] **Step 1:** `npm run typecheck -w @banking/staff` passes.
- [ ] **Step 2: Manual check:** request payslip → customer page shows request → upload `data/synthetic/documents/alex_morgan_demo_customer/adeverinta_venit_alex_morgan_demo_customer.pdf` → back in queue with current offer → approve → customer sees "Accepted".
- [ ] **Step 3: Commit** `agent(human-review): staff app on the review API`

### Task 7: Chat stops tell the customer to contact a representative

**Files:**
- Modify: `src/agent/tools/stubs.py:692-707` (no ticket; record reason only), `src/agent/orchestration/state.py:118` (`EscalationRecord.ticket_id` removed), `src/models/chat.py:138` (`EscalationBlock.ticket_id` removed), `src/agent/orchestration/blocks.py`, `events.py` fixed texts for `manual_review` / `escalated`; `packages/banking/src/orchestrator.ts` + `apps/customer/src/components/orchestrator/status-blocks.tsx` (drop ticket).
- Copy (exact): "This application needs a bank representative. Please contact your branch or call the bank, and they will help you continue."
- Test: extend `tests/unit/orchestrator/test_orchestrator.py` — manual_review and escalated responses contain that text and no `ticket_id`.

- [ ] **Step 1:** failing test → **Step 2:** run FAIL → **Step 3:** implement → **Step 4:** run orchestrator tests PASS; regenerate contract `python scripts/export_chat_contract.py` and confirm `tests/contract` passes → **Step 5:** commit `agent(orchestrator): stops point the customer to a bank representative`

### Task 8: Remove the old implementation

**Files:**
- Delete: application tables + `save_application` + JSON sync in `src/storage/application_db/repository.py` (keep any eligibility code still imported; check with grep), `tests/unit/storage/test_application_persistence.py`.
- Delete: `packages/banking/server/applications.ts`, `reviews.ts`, their routes in `server/index.ts`/`queries.ts`, review transitions in `packages/banking/src/workflow.ts`, seeded applications in `seed.ts`.
- Modify: `tests/e2e/frontend.spec.ts` — replace Node application/review scenarios with one: request document → upload → approve → "Accepted".

- [ ] **Step 1:** `grep -rn "save_application\|frontend-demo.json\|reviewApplication" src packages apps` → no hits
- [ ] **Step 2:** full Python suite: only the 3 pre-existing `test_orchestrator_eligibility_anaf.py` failures remain; `npm run typecheck` in all workspaces passes
- [ ] **Step 3:** commit `agent(human-review): remove the old application and review code`
