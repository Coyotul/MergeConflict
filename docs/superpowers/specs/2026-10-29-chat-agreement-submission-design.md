# Submission by chat agreement: short design

Date: 2026-10-29. Builds on `2026-10-29-human-review-workflow-design.md`.

**Intent.** The AI orchestrator submits the application itself, through the
`submit_application` tool, once the application is complete and the customer has
explicitly agreed in the chat. Agreeing in the chat is the only way to submit;
the summary card and its confirm/decline buttons are removed (also from `main`
when this branch merges).

**Goals.** The model presents the final terms in text (amount, term, monthly
installment, DAE, total cost) and asks whether to submit; on a clear yes it calls
`submit_application`. The server refuses the call unless it is safe.

**Non-goals.** No other submission path. No change to the review workflow.

**Anti-goals.** The model submitting on its own initiative, after an upload or a
tool result, or for terms that changed since they were shown.

**Approaches.** (1) Model-callable tool with server guards (chosen: the only way
that makes chat the sole path while keeping a deterministic safety net).
(2) Unguarded model tool (rejected: one misread message submits a credit
application). (3) Keep a hidden confirm event (rejected: contradicts "agreement
in chat is the only way").

**Decided.**
- `submit_application` becomes `model_callable=True`. Model input:
  `{customer_agreement: str}` (the customer's agreeing words, quoted). Server
  fills `application_id`/`idempotency_key` (`session_id:summary_version`); the
  model never supplies them.
- Precondition (server): next need is `confirm_submission` (all verified, offer
  selected, current summary); the turn was started by a `CustomerMessage`;
  `customer_agreement` is non-empty and appears in that customer message
  (case/whitespace-insensitive substring). Otherwise the tool fails with
  `precondition_failed` and nothing is written.
- `customer_agreement` and the summary terms are stored in the review snapshot,
  shown to the reviewer.
- After a successful call the orchestrator saves the session and replies with the
  existing fixed "submitted" text (no paraphrase), same as today.
- Prompt: remove "never callable" for `submit_application`; add when to call it
  and that asking/answering must be explicit.
- Removed: `ApplicationSummaryBlock` rendering in the customer app
  (`summary-block.tsx`, its use in `blocks.tsx`), the confirm/decline action in
  `orchestrator-react.tsx`/`orchestrator-state.ts`, `POST .../confirmation`
  route, `ConfirmationDecision` event and handler. The summary still exists in
  session state (it supplies `summary_version` and the model's context); the
  wire block is no longer sent, `awaiting.kind` at this stage becomes `text`.
- Declining is ordinary chat; the model can change term/offer as today.

**Left to the builder.** Exact prompt wording; contract examples regenerated;
which existing tests are rewritten vs removed.
