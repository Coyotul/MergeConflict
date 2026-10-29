# Chat API contract (for the frontend)

This folder is the contract between the credit-assistant backend and the chat UI.

- `chat.openapi.yaml` is the OpenAPI document of the running API (generated, do not edit by hand).
- `examples/chat/NN-<stage>.json` holds one real `TurnResponse` per progress stage, recorded from the
  mock-mode happy path (`00-start` is the greeting, before any application exists).
- `examples/chat/error-503.json` and `error-422.json` are real error bodies.

Regenerate everything with `python scripts/export_chat_contract.py`. A test fails if the committed
files drift from the app. Ids and timestamps in the examples are placeholders
(`example-session-1`, `example-turn-NN`, `APP-00000001`, `2026-10-28T09:00:00Z`).

## Run the backend in mock mode

Mock mode runs the real API with a scripted, deterministic assistant and synthetic data. You don't need
a Featherless API key, a database or Docker.

```bash
pip install -r requirements.txt
ORCHESTRATOR_MODEL=fake uvicorn src.api.app:create_app --factory --port 8000
```

Sessions are saved under `data/local/sessions/` and survive a restart. Set
`ORCHESTRATOR_SESSION_STORE=memory` if you want a clean slate on every start.

**CORS:** The orchestrator allows cross-origin requests from origins listed in the `ORCHESTRATOR_CORS_ORIGINS` environment variable (default: `http://127.0.0.1:3000,http://127.0.0.1:3001,http://localhost:3000,http://localhost:3001`). Use a comma-separated list to override it. Unhandled `500 internal_error` responses also carry CORS headers for allowed origins.

Everything the backend returns in mock mode is synthetic. Responses carry `simulated: true`, and
eligibility results and offers are "simulated, based on public conditions". They are not offers or
decisions from any bank. Never show them as approvals.

## Identity: the `X-Customer-Id` header

Until the gateway exists, every request needs an `X-Customer-Id` header (missing header: `401`).
A session can only be used with the id that created it (otherwise `403`).

Use the synthetic customers:

| Id | What happens |
|---|---|
| `cust-alex-morgan` | Happy path: eligible (ANAF income 8500, no loans); the payslip income (8500) differs from a stated 7000, so you see a conflict to confirm |
| `cust-elena-popa` | Eligible (ANAF income 4500, no loans) |
| `cust-radu-mihai` | Eligible on two ANAF salaries (5000 total) with two small loans; a stated 6500 adds an `income_gap` reason |
| `cust-dan-ionescu` | Debt-to-income above 40% (large existing loan): `not_eligible` |
| `cust-andrei-stan` | ANAF income 2300, below the 2500 minimum: `not_eligible` |
| `cust-ioana-marin` | A loan currently 91 days past due: `not_eligible` |
| `cust-victor-dobre` | Open insolvency procedure: `not_eligible` |
| `cust-maria-stoica` | Loan restructured in the last 12 months: `manual_review` |
| `cust-mihai-ilie` | Self-employed (PFA): answer `self_employed` for the employment type to reach `manual_review`; the payslip income has low extraction confidence |

Eligibility is decided by deterministic rules over the session fields plus the mock ANAF and credit-bureau
SQLite dataset (`data/local/credit_sources.db`, built by `python scripts/credit_sources/setup.py`). If the
database is missing, the eligibility and profile tools fail with `tool_unavailable`.
Other ids can chat, but their profile lookup and document processing fail.

## Endpoints

| Method and path | Body | Returns |
|---|---|---|
| `POST /chat/sessions` | `{}` | `201` `TurnResponse` with the greeting |
| `POST /chat/sessions/{id}/messages` | `{"text": "..."}` (1-4000 chars after trimming) | `TurnResponse` |
| `POST /chat/sessions/{id}/documents` | multipart: `doc_type`, `file` (PDF/JPG/PNG, at most 10 MB) | `TurnResponse` |
| `POST /chat/sessions/{id}/offer-selection` | `{"offer_id": "..."}` | `TurnResponse` |
| `POST /chat/sessions/{id}/confirmation` | `{"summary_version": "...", "decision": "confirm" \| "decline"}` | `TurnResponse` |
| `GET /chat/sessions/{id}` | – | `SessionView`: all chat messages plus `latest` (a `TurnResponse` with empty `messages`) |
| `GET /health` | – | `{"status": "ok", "model": ..., "session_store": ...}` |

Use `GET /chat/sessions/{id}` to rebuild the screen after a reload: render `messages`, then
`latest.awaiting`, `latest.progress` and `latest.blocks`.

## Rendering a `TurnResponse`

- **`messages[]`**: the assistant's new messages for this turn. Append them to the chat. Each
  message can carry `citations[]` (`id`, `publisher`, `title`, `url`, `section`, `effective_date`):
  show them as sources under the message.
- **`awaiting`** decides the input control:
  - `text`: the normal text box.
  - `document`: an upload control for the types in `awaiting.document_types` (send one of those as
    `doc_type`). Keep the text box available too.
  - `offer_choice`: let the customer pick one offer from the `offers` block, then call
    `offer-selection` with its `offer_id`.
  - `confirmation`: show the `application_summary` block with Confirm and Decline buttons. They call
    `confirmation`.
  - `none`: the application is submitted. Nothing more to send for it.
- **`progress`**: `flow`, the current `stage` and `steps[]` (`done` / `current` / `todo`) for a stepper.
  Main stages in order: `discovery`, `collecting_information`, `eligibility`, `documents`,
  `offer_selection`, `awaiting_confirmation`, `submitted`. The side stages `not_eligible`,
  `manual_review` and `escalated` take the slot of the stage they branched from. `stage` is `null`
  until the customer starts an application.
- **`blocks[]`** are built from state by the backend. Render each block by its `type`, and ignore types
  you don't know:
  - `document_checklist`: `items[]` with `doc_type`, `label`, `status` (`requested`, `processing`,
    `accepted`, `rejected`) and `rejection_reason`.
  - `extracted_fields`: values read from documents, with `confidence`, `needs_confirmation` and
    `conflict_with` (the value the customer stated, when it differs).
  - `eligibility_result`: `result.status`, `result.reasons[]`. Label it "simulated, based on public conditions".
  - `offers`: `offers[]` (amounts are decimal strings plus currency) and `selected_offer_id`.
  - `application_summary`: `summary` including `summary_version`.
  - `application_submitted`: `application_id`, `status` (`PENDING_HUMAN_REVIEW`). It is not an approval.
  - `escalation`: `ticket_id`, `message`.
- **`simulated`**: `true` whenever synthetic data contributed. Show a visible "simulated" badge.

## Confirmation must send the `summary_version` you showed

When `awaiting.kind` is `confirmation`, `awaiting.summary_version` equals the
`application_summary.summary.summary_version` on screen. Send exactly that value. If the summary
changed in the meantime, nothing is submitted and the response shows the current summary instead.
Ask the customer to review it again.

## Test hooks

- Upload a file whose name starts with `reject_` (for example `reject_id.pdf`) to get a rejected document
  with a `rejection_reason`. The checklist shows `rejected` and the customer is asked to upload it again.
- An empty file is rejected too.
- Scripted conversation (Romanian or English) that walks the happy path with `cust-alex-morgan`:
  `Vreau un credit` → `pentru renovare` → `30000 lei` → `60 luni` → `employed` → `48` → `7000` →
  `FICTIV Employer's Studio 1` → `0` → upload `id_card`, `payslip`, `bank_statement` → `da` → pick an offer → confirm.
- A message ending in `?` (for example `Ce documente îmi trebuie?`) is answered from the synthetic policy
  passages, with citations (publisher `Synthetic stub`). This works mid-application too.

## Errors

Every error has the body `{"code": "...", "message": "...", "retryable": true | false}`.

| Status | `code` | Meaning |
|---|---|---|
| `401` | `missing_customer_id` | No `X-Customer-Id` header |
| `403` | `forbidden` | The session belongs to another customer |
| `404` | `session_not_found` | Unknown session id |
| `409` | `session_busy` / `version_conflict` | Another request for this session is running (`retryable: true`) |
| `413` | `upload_too_large` | File over 10 MB |
| `415` | `unsupported_media_type` | Not PDF, JPG or PNG |
| `422` | `invalid_request`, `document_not_requested` | Invalid body, or a `doc_type` the application doesn't ask for |
| `503` | `service_unavailable` | The model or a tool provider is down; nothing was saved (`retryable: true`) |
| `500` | `internal_error` | Unexpected failure |

When `retryable` is `true`, keep the customer's input and offer a retry (or retry once
automatically after a short delay). When it is `false`, show the `message` and don't resend the same
request unchanged.
