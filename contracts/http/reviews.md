# Review API

Served by the Python API (`src/api/application/reviews.py`), same host as `/chat`.

## Customer (`X-Customer-Id` header, same id as the chat)

- `GET /applications` → `{applications: [CustomerApplicationView]}`
- `GET /applications/{id}` → `CustomerApplicationView` (404 if not yours)
- `POST /applications/{id}/requests/{request_id}/document` (multipart `file`)
  → `{application: CustomerApplicationView, accepted: bool, reasons: string[]}`;
  409 if the request is not open.

`CustomerApplicationView`: `id, reference, product_code, status, status_label,
amount, term_months, monthly_installment, total_cost, offer_updated,
history: [{to_status, status_label, reason, at}], open_request: {id, doc_type, reason} | null,
created_at, updated_at`.

Status labels: `PENDING_HUMAN_REVIEW` "Waiting for review",
`MORE_INFORMATION_REQUIRED` "More information needed", `APPROVED` "Accepted",
`REJECTED` "Rejected".

## Reviewer (`X-Reviewer-Id: reviewer-demo`, else 403)

- `GET /review/applications?status=` → `{applications: [{id, reference, customer_name, product_code, amount, status, status_label, updated_at}]}`
- `GET /review/applications/{id}` → full record: `snapshot`, `current`
  (`application`, `eligibility`, `offer`, `pricing_errors` after a requested upload),
  `documents`, `history`, `requests`, `version`, `changed_fields: [{field, before, after}]`,
  `customer` (the customer view).
- `POST /review/applications/{id}/decision` body
  `{action: "approve" | "reject" | "request_document", reason, version, doc_type?}`;
  422 for an empty reason or a type that cannot be requested, 409 for a stale
  `version` or a disallowed transition.
- `GET /review/applications/{id}/documents/{document_id}` → file bytes.
