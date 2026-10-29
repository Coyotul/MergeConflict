# Human review workflow: design

Date: 2026-10-29
Status: draft for approval

## Intent

A credit application submitted through the AI chat must not stop at "submitted".
A human reviewer decides every submitted application. The customer follows it on
the **Applications page** of the customer portal, which shows whether it is
waiting for review, accepted, rejected, or needs more information. When a reviewer
asks for a document, the customer uploads it on the Applications page, and the
server checks that it really is the requested document before the reviewer sees
it again.

Why: the spec (`SPECIFICATION.md:121-124`, `:825-831`) requires that a human
approves, rejects or requests information, and that the customer is told the
outcome. Today none of this is connected (see "Current state").

## Current state (what gets replaced)

- The chat's `submit_application` (`src/agent/tools/stubs.py:542`) writes a row to
  `credit_applications` in `data/local/eligibility-demo.sqlite3`
  (`src/storage/application_db/repository.py`), copies a partly hard-coded entry
  into the Node demo store `data/local/frontend-demo.json`, and returns
  `simulated=True`. If the write fails it invents an `APP-<hex>` id.
- The staff app (`apps/staff`) and the customer Applications page read and write
  the separate Node demo server (`packages/banking/server`, port 4010). That
  server loads its JSON file once at startup, so chat submissions do not appear
  until restart and can be overwritten.
- Reviewer decisions only change the Node JSON. Nothing reaches SQLite or the chat.
- Stops before submission (manual-review eligibility, documents needing a human,
  `request_human_review`) leave the chat stuck on a fake `HR-<hex>` ticket.
- Customer identity already lines up: in the portal the chat uses the logged-in
  Node customer (`customer-alex`, Alex Morgan) via
  `useOrchestratorChat(snapshot?.customer.id)`; `cust-001/002/003` are only the
  chat's fallback when there is no portal login. All of them are profiles in
  `config/orchestrator/customers.yaml`. Only Alex Morgan has generated demo
  documents (`data/synthetic/documents/alex_morgan_demo_customer/`).

The user's instruction: discard the existing review/application implementation
and rebuild it.

## Goals

1. Submitting in the chat creates a real application record, in one place, that
   the reviewer queue and the customer Applications page both read.
2. A reviewer can approve, reject, or request one specific document, each with a
   written reason the customer sees.
3. The customer sees the current status and history on the Applications page,
   and is told what to do when information is needed.
4. A customer can upload a requested document on the Applications page. The
   server runs the existing OCR/extraction/validation pipeline and accepts it
   only if it is the requested document and passes the rules; otherwise the
   customer is told why immediately and can retry.
5. Once a requested document is accepted, eligibility and the offer are
   recalculated with the new values, and the application returns to the
   reviewer queue showing the new document, the changed values, and both the
   original and the recalculated eligibility and offer.
6. Chat stops before submission end with a clear "please contact a bank
   representative" message; no ticket, no review case.
7. Applications belong to the same customer the chat uses: whatever id the chat
   sends in `X-Customer-Id` (in the portal, the logged-in `customer-alex`). No
   change to the portal login or Node customer data.

## Non-goals

- Signing, contract generation, disbursement, or the AWAITING_SIGNATURE /
  COMPLETED states from the spec.
- Review cases for escalated/stopped chats (explicitly decided: only fully
  submitted applications reach a reviewer).
- Email/SMS/push notifications. "Notified" means the Applications page (and its
  sidebar badge) shows the status.
- Real authentication, multiple reviewers, assignment or workload balancing.
- Migrating the other Node-backed customer pages (loans, products, settings,
  consents, messages). They keep running on the Node server, untouched except
  where they show applications (see Frontend).
- Customer cancellation of a submitted application.

## Anti-goals (would be failure even if it "works")

- The AI or any automated rule makes or implies the credit decision. Only a
  reviewer action changes status to approved/rejected.
- An upload that is not the requested document type, belongs to someone else,
  or fails validation is ever shown to the reviewer as fulfilling the request.
- A submission silently "succeeds" with an invented id when storage fails.
- Customer sees another customer's applications. (There are no reviewer-only
  notes; every reviewer reason is customer-visible by design.)
- Two sources of truth for application status again.

## Approaches considered

**A. One Python backend (chosen).** Add a review service and its own SQLite
tables to the existing FastAPI app. The chat writes the real application there;
new customer and reviewer endpoints serve the Applications page and a rebuilt
staff app. Requested uploads go through the same Python document pipeline the
chat uses. Chosen because the documents, OCR, validation and orchestrator state
are already in Python, and a single store removes the sync problem that breaks
the current setup. Trade-off: the Node demo server still runs for unrelated
customer pages.

**B. Keep the Node server as the portal backend.** Python would push submissions
to Node, and Node would call Python to validate uploads. Rejected: it keeps two
stores and two servers that must stay in sync, which is the current failure.

## Design

### Statuses and transitions

| Status | Customer label | Set by |
|---|---|---|
| `PENDING_HUMAN_REVIEW` | Waiting for review | chat submission; accepted requested document |
| `MORE_INFORMATION_REQUIRED` | More information needed | reviewer "request document" |
| `APPROVED` | Accepted | reviewer |
| `REJECTED` | Rejected | reviewer |

Allowed transitions:
`PENDING_HUMAN_REVIEW → APPROVED | REJECTED | MORE_INFORMATION_REQUIRED`,
`MORE_INFORMATION_REQUIRED → PENDING_HUMAN_REVIEW` (only via an accepted upload).
`APPROVED` and `REJECTED` are final. Any other transition is rejected with 409.
A reviewer may request information any number of times, one open request at a
time (builder's call made by us: one open request keeps the customer UI simple).

Every transition writes a history entry: from, to, actor (`customer`, `reviewer`,
`system`), the customer-visible reason, timestamp.

### Data (new SQLite tables, new database file)

Builder's call made by us: a new file `data/local/applications.sqlite3`, created
by a migration in the existing `src/storage/application_db/migrations/` style, so
it does not mix with the immutable eligibility demo tables.

- `applications`: id (`APP-` + random), human reference, customer_id,
  chat session_id, product_code, status, idempotency_key (unique), submitted
  snapshot (JSON), created_at, updated_at, version (for optimistic concurrency
  on reviewer actions).
- `application_documents`: application_id, document_id (in the existing
  `SecureDocumentStore`), doc_type, origin (`chat` or `information_request`),
  status, extracted fields, validation summary, sha256, uploaded_at,
  superseded_by.
- `application_history`: as described above.
- `information_requests`: id, application_id, doc_type, reason, status
  (`open`, `fulfilled`), created_at, fulfilled_at, fulfilled_document_id.

The **submitted snapshot** is frozen at submission and contains: applicant name
and profile fields, the product requirements (fields and documents), every
application field with value / source (customer or document) / confirmed flag,
the eligibility result, the selected offer (amount, term, installment, DAE,
total cost), and the document records. The snapshot itself never changes.

Next to it, `applications` holds a **current assessment** (JSON): the current
field values, eligibility result and offer. At submission it equals the
snapshot; each accepted requested document replaces it (see Recalculation).
`application_history` entries for recalculations record what changed.

### Chat submission

Submission always has real stored documents: the production orchestrator uses
the real document tools (`build_orchestrator` always passes a
`DocumentProcessingService`). The stub `process_document` remains for unit tests
only; tests that exercise submission use real stored documents.

`submit_application` becomes real: it writes the application, its documents and
the first history entry in one transaction, keyed by the existing idempotency
key (`session_id:summary_version`), and returns `simulated=False` with the real
id and status. A repeated key returns the existing application. On storage
failure the tool fails (`ToolUnavailable`) and the chat tells the customer the
submission did not go through and to try again; no invented id. The in-memory
idempotency cache goes away.

`get_application_status` reads the new tables, so if the customer asks in the
chat, the answer matches the Applications page. The chat itself does not push
or poll status updates; the Applications page is where the customer is notified.

### Stops before submission

`manual_review` (eligibility or documents) and `escalated` stages end the chat
with a fixed message telling the customer to contact a bank representative.
`request_human_review` stays model-callable so the model can stop the flow, but
it records only the reason in the session; no ticket id is generated. The
`EscalationBlock` drops `ticket_id`. The chat contract examples are regenerated.

### Requested-document upload and validation

Endpoint (customer): upload a file against an open information request.
Processing:

1. Same upload checks as chat uploads: size, MIME/content signature, filename
   sanitising (`src/storage/secure_documents/validation.py`). Stored in the
   existing `SecureDocumentStore`, owned by the customer and bound to the
   application.
2. Run `DocumentProcessingService.process_stored_document` with the requested
   type, then the same acceptance rules the chat uses in
   `DocumentTools._output` (`src/agent/tools/documents.py`): validation must
   pass, ID name must match the profile, payslip must have a complete employee
   name and valid CNP, statement must be RON with an explicit debt total,
   extraction confidence ≥ 0.85, and every field the requested type verifies
   must parse. That logic is extracted into a shared function both callers use,
   rather than copied.
3. "Is it the requested document": the request names one type (`id_card`,
   `payslip`, `bank_statement`); the file is only processed as that type, and
   it is accepted only if that type's extractor finds its required fields and
   validation passes. A different document (an ID card uploaded for a payslip
   request) fails this and the customer sees "This doesn't look like the
   requested payslip" plus the specific reasons. Builder may add a cheap
   keyword check on the OCR text for a clearer message.
4. Cross-check against the application's other accepted documents (existing
   `cross_validate`). An inconsistency rejects the upload with the reason.
5. Outcomes that the chat treats as "needs human review" (ID name mismatch,
   foreign-currency statement, no explicit debt total, confidence below 0.85,
   cross-document inconsistency) are plain rejections here: the customer sees
   the reason and must upload something else. Decided by the user.
6. Accepted: request becomes `fulfilled`, document recorded with origin
   `information_request` and the previous document of that type marked
   superseded, then recalculation runs (below), then status returns to
   `PENDING_HUMAN_REVIEW` and history entries are written, all in one
   transaction. Rejected: nothing changes on the application; the response
   carries the reasons; the customer can retry. Rejected attempts are not shown
   to the reviewer (our call; the reviewer only sees accepted evidence).

Requestable types: only `id_card`, `payslip`, `bank_statement` (the three with
automatic extractors, `DOCUMENT_KINDS` in `src/agent/tools/documents.py`), and
only types the product's requirements in the snapshot list. The fields an
upload must provide are the snapshot requirements' fields with
`verified_by` equal to the requested type; the shared acceptance function
takes those requirements as input instead of reading a live chat session.

### Recalculation (decided by the user: automatic)

After a requested document is accepted:

1. Build the current field values: the previous current assessment, with every
   field that the new document verifies replaced by the document's value.
2. Rerun eligibility through the same service the chat uses
   (`src/services/eligibility/orchestrator_bridge.py`) and pricing through the
   same service the chat's `calculate_loan_offer` uses
   (`src/services/pricing/service.py`), for the same product, amount and term as
   the selected offer. These run outside a chat session, from the stored
   values; the builder adapts the inputs (for example by building an
   `ApplicationState` from the stored values) without changing the rules.
3. Store the result as the new current assessment. If eligibility is no longer
   satisfied, or pricing fails for the selected amount/term, the result says so;
   status still returns to `PENDING_HUMAN_REVIEW` and the reviewer decides.
4. The reviewer sees original vs current: changed field values, eligibility
   status and reasons, and offer terms (installment, DAE, total cost).

Our call: approval approves the **current** offer. The customer does not have
to re-accept a changed offer (nothing is signed in this demo); the Applications
page shows the current offer terms and marks them as updated after review.

### API

All on the existing FastAPI app, new routers.

Customer (identity from the existing `X-Customer-Id` header, same as the chat):
- list my applications (summary, status, customer-visible history, open request)
- get one of my applications
- upload a document for an open information request

Reviewer (identity from an `X-Reviewer-Id` header that must equal one configured
demo reviewer id; anything else is 403):
- list the queue, filterable by status
- get an application: snapshot, documents (current and superseded), extracted
  fields with sources and confidence, eligibility, selected offer, history,
  information requests
- approve / reject / request document: each requires a non-empty reason;
  request requires a doc type; each carries the application `version` and
  fails with 409 if stale or if the transition is not allowed
- download a document's file for viewing

CORS: allow the new header and the staff app origin.

### Frontend

Customer app (`apps/customer`):
- Applications page rebuilt on the new customer API, polling every few seconds
  (builder picks the interval). Shows each application's status label, amount,
  term, installment, history with reasons, and, when more information is
  needed, the reviewer's reason and an upload control with immediate
  accept/reject feedback.
- Customer identity: the same id the chat uses, i.e. the logged-in Node
  customer (`snapshot.customer.id`, `customer-alex` in the demo), sent as
  `X-Customer-Id`. The chat's `cust-00x` fallback is unchanged.
- The sidebar "needs attention" badge, the dashboard "Applications" panel and
  the assistant context panel's application link switch to the new API.
- Old components that only served the Node application model
  (`application-card.tsx`, `document-checklist.tsx`, application parts of
  `notifications.tsx`) are rewritten or removed.

Staff app (`apps/staff`), rebuilt on the reviewer API:
- Queue: status filter, counts per status, search by reference or name.
- Application detail: applicant, extracted fields with source and confidence
  (document values that changed via a requested upload are highlighted against
  the old value), documents with validation results and a file viewer, the
  eligibility result, the selected offer, history.
- Actions: approve, reject, request document, each with a required reason
  shown to the customer.
- The existing audit page is removed (history on each application replaces it).

### Removed

- `credit_applications` / `credit_application_history` tables, `save_application`
  and the JSON sync in `src/storage/application_db/repository.py`, and its tests.
- Submission/status/review stubs in `src/agent/tools/stubs.py` (replaced).
- Node application/review code: `packages/banking/server/applications.ts`,
  `reviews.ts`, application parts of `queries.ts`, the workflow transitions in
  `packages/banking/src/workflow.ts`, and seeded applications in `seed.ts`.
  Node routes still needed by other pages stay.

## Constraints

- Windows-only OCR for scanned images applies here too; PDFs with embedded text
  work everywhere.
- Must keep the existing chat contract tests passing, with examples regenerated
  for the deliberate contract changes.
- Synthetic data only; the UI keeps saying no real credit decision is made.

## Left to the builder

- Table column details, indexes, reference format.
- Polling interval, exact UI layout and copy (within the labels above).
- Endpoint paths and response shapes, recorded in `contracts/http/`.
- Whether to add a keyword check for clearer "wrong document" messages.
- How to keep e2e tests (`tests/e2e/frontend.spec.ts`) meaningful after the
  Node application flows are removed.
