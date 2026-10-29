# Documents first, one review form: short design

Date: 2026-10-29.

**Intent.** The customer uploads all required documents without being asked
anything else, then reviews everything extracted from them in one form: OK, or
fix what is wrong and OK. Only values that do not influence eligibility or
pricing are editable. Replaces per-field confirmation in chat.

**Goals.**
- The chat asks only for values no document supplies (purpose, amount, term,
  product), then requests the documents. Fields with `verified_by` are never
  asked as `missing_field`; documents fill them.
- While documents are pending, the model sees only document needs; it does not
  ask about other values.
- When every required document is accepted, the response carries one review form.
  OK (with optional edits) confirms all extracted values; eligibility and offers
  follow.

**Non-goals.** No change to document validation, review workflow or submission.

**Anti-goals.** The model, or a form edit, changing a value that feeds eligibility
or pricing; skipping the form.

**Approaches.** (A) Code-handled form event (chosen: deterministic, the model
cannot skip, edit or confirm on the customer's behalf). (B) Form text sent as a
chat message for the model to parse (rejected: unreliable edits).

**Decided.**
- Editable: `full_name`, `employer_name`. Read-only: `monthly_net_income`,
  `existing_monthly_obligations`, `employment_type`, `employment_months`, `age`
  (wrong values are fixed by re-uploading the document). Encoded as
  `editable: true` on those two field specs in `config/orchestrator/requirements.yaml`.
- Needs order: discovery/product → missing fields *without* `verified_by` →
  documents → `review_extracted` (one need, replaces `confirm_extracted` and
  `resolve_conflict`) → eligibility → offers → confirm submission.
- New wire block `extracted_fields_form`: `fields: [{field, label, value, source,
  document_type, confidence, editable}]`; `awaiting.kind = "review_form"`.
- New endpoint `POST /chat/sessions/{id}/extracted-fields` body
  `{edits: {field: value}}` → event `ExtractedFieldsReviewed`, handled by code:
  reject (422) edits to non-editable or unknown fields, parse edits with the
  field spec, store edited values as `source=customer, confirmed=True`, confirm
  all other document values, then let the model continue (eligibility).
- Prompt: drop per-field confirmation rules and example; say the form handles
  review and that during the document stage the model only talks about documents.
- Customer app: form component with read-only rows and inputs for editable rows,
  one OK button; replaces the per-field confirm buttons in
  `extracted-fields-block.tsx`.

**Left to the builder.** Form layout and copy; regenerated contract examples;
which existing confirm/conflict tests are rewritten vs removed.
