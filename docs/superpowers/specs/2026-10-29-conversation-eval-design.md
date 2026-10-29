# Conversation evaluation: simulated customers, trace checks and an LLM judge

Date: 2026-10-29. Status: draft for owner review.
Branch: `integrate/eligibility-local-rag` (RAG, real documents, pricing, SQLite eligibility, agent trace).

## Intent

The owner wants proof that the agent behaves well in real conversations: it asks
the right questions, clarifies what the customer actually wants, and calls the
right tools at the right moments. The end state (submission, human review) is
explicitly **not** the measure. Several scenarios must be exercised:

1. a customer who knows they want a loan;
2. a customer who does not know which loan type fits;
3. a customer who changes their mind mid-conversation and wants a loan for
   something else;
4. a customer asking general questions the RAG should answer.

Each scenario runs against the real agent (Featherless model, real tools). A
simulated customer (another model) plays the customer from a brief. The session
trace is checked deterministically for tool calls, order, intents and field
changes, and a judge model grades the wording of the agent's replies.

## Goals

- One command runs every scenario N times and writes a readable report: the
  conversation, each check's result with the evidence, the judge's grades with
  reasons, and the pass rate per check across runs.
- Scenarios are data (YAML), so new ones need no code.
- Trace checks are deterministic and unit-tested against recorded traces.
- The judge's and the simulator's outputs are validated JSON; malformed output
  is retried once, then recorded as an evaluation error, never as a pass.

## Non-goals

- Submitting applications or human review (the run stops before confirmation).
- A CI gate or pytest live suite (approach C; may be added later).
- Frontend or browser testing.
- Changing the agent's prompts or behaviour (findings are reported, not fixed,
  in this work).

## Anti-goals

- A broken simulator or judge counted as an agent failure or success: their
  errors are reported separately from agent checks.
- Real customer data or secrets in reports (synthetic customers only; the API
  key never written).
- Reports or traces committed: they live under ignored `data/local/eval/`.

## Constraints

- Only `FEATHERLESS_API_KEY` is configured: agent, simulator and judge all use
  Featherless (OpenAI-compatible) through the existing `FeatherlessChatModel`
  adapter, each with its own model name and temperature.
- Real RAG loads BGE-M3 in-process. The owner runs RAG runs in their own
  PowerShell (Claude Code's memory guard kills that process). A
  `--retrieval stub` option allows quick runs without the embedder.
- Real document processing requires the uploaded ID's name to match the
  customer profile and a checksum-valid CNP; the dataset's CNPs deliberately
  fail the checksum. Documents are therefore generated at run time with the
  customer's name and a checksum-valid CNP derived from the person's birth
  date and sex in `persons` (body `S YY MM DD 41 001` + checksum), using
  `tests/fixtures/documents.py`.
- The orchestrator also calls some tools itself (`caller="code"`):
  `get_product_requirements`, `get_customer_profile` (once a product with
  identity fields is set), `process_document`, `verify_application_documents`,
  `get_credit_products` (product name for the summary), `create_loan_application`
  and `submit_application`. `run_eligibility_check` and `calculate_loan_offer`
  are only ever called by the model. Checks must distinguish the model's calls
  from code calls; checks about the agent's choices default to `caller: model`.
- Offers require all three documents accepted, extracted fields confirmed, no
  open conflicts and eligibility re-run on verified values
  (`can_calculate_offers`). Generated documents must therefore carry the
  customer's own figures: `tests/fixtures/documents.py::document_bytes` is
  extended to take income, employer, employment start and obligations, filled
  from the customer's `documents` section in `config/orchestrator/customers.yaml`
  (designer's call). The simulated customer's brief uses the same figures, and
  tells it to confirm figures read from its documents. The runner pins the
  orchestrator clock to the dataset date 2026-10-28, as the e2e tests do, so
  document dates, ages and the credit-source `as_of_date` agree.
- Real RAG also needs the knowledge Postgres (`ORCHESTRATOR_DATABASE_URL`)
  running, not just the embedder.

## Approaches considered

- **A. Live pytest suite**: one pass/fail test per scenario. Rejected: a single
  run of a model-driven conversation is noisy, and pytest output is a poor way
  to read conversations.
- **B. Evaluation runner with a report (chosen by the owner)**: scenarios in
  YAML, run N times, per-run report and pass rates.
- **C. B plus a thin pytest wrapper**: deferred.

## Design

### Layout

- `config/eval/scenarios.yaml`: scenarios and rubrics.
- `scripts/eval/`: package with
  - `run_scenarios.py`: CLI entry point;
  - `driver.py`: runs one conversation in-process (`create_app` +
    `TestClient`, like `tests/e2e/test_chat_scenarios.py`) with a per-run
    trace directory and a memory session store;
  - `customer.py`: the simulated customer;
  - `checks.py`: deterministic trace checks;
  - `judge.py`: the wording judge;
  - `report.py`: Markdown and JSON output.
- Unit tests: `tests/unit/eval/`, using recorded trace fixtures and
  `FakeChatModel`; no network.

### CLI

`python -m scripts.eval.run_scenarios [--scenario ID ...] [--runs 3]
[--retrieval rag|stub] [--max-turns 25] [--out data/local/eval/<run_id>]`

Models come from settings/env: the agent uses `ORCHESTRATOR_MODEL` as today;
`EVAL_CUSTOMER_MODEL` (default: the agent's model, temperature 0.7) and
`EVAL_JUDGE_MODEL` (temperature 0). The judge should be a different model
family from the agent so it does not grade its own style; the builder confirms
a suitable model is available on Featherless and sets the default.

### One conversation

1. Start a session for the scenario's demo customer.
2. Loop until a stop condition:
   - give the simulated customer the brief, the transcript so far, and what
     the agent is waiting for (`awaiting.kind`, requested document types,
     offer IDs and summaries);
   - it answers with one JSON action: `say {text, switch?: bool}`,
     `upload {doc_type}`, `choose_offer {offer_id}` or `done {reason}`.
     `switch: true` marks the message where it follows the brief's change of
     mind; the driver records that customer turn's `turn_id` so checks can
     find it (designer's call);
   - the driver performs it through the chat API (uploads generated as
     described in Constraints).
3. Stop when the simulator says `done`, the scenario's `stop_when` is met,
   the agent awaits confirmation (never confirm), or `max_turns` is reached
   (recorded as a stop reason, not a failure by itself).
4. Render the trace with the existing `scripts/trace_report.py` renderer and
   keep the JSONL.

The simulator only knows its brief and what it has been told in the chat; it
never sees state or the trace. Its prompt tells it to answer what the agent
asked, volunteer nothing the brief marks as "only if asked", follow the brief's
timed changes (for example "after you have given your income, say you'd
rather finance a house"), and to stay in English.

### Scenario format

```yaml
- id: knows_loan
  customer_id: cust-elena-popa
  brief: |
    You are Elena Popa. You want a personal loan of 20,000 RON over 48 months
    to buy a used car. You are employed, 67 months at your employer, net
    income about 4,500 RON, no existing loans. Answer what you are asked.
    When offers appear, pick the cheapest monthly payment, then say done.
  stop_when: offers_shown
  checks:
    - {check: intent_seen, intent: credit_application, within_turns: 2}
    - {check: product_final, product: personal_loan}
    - {check: tool_called, tool: run_eligibility_check}
    - {check: tool_order, before: run_eligibility_check, after: calculate_loan_offer}
    - {check: no_model_tool_rejections}
    - {check: no_failed_turns}
  rubric:
    - Asks for one or two missing details at a time, never re-asks something already given.
    - Explains the eligibility outcome in plain words before showing offers.
```

### Initial scenarios

| id | customer | brief summary | key checks |
|---|---|---|---|
| `knows_loan` | Elena Popa (eligible) | personal loan 20,000 / 48 months for a car | intent `credit_application` early; product `personal_loan`; eligibility before offers; offers shown |
| `unsure_type` | Radu Mihai (eligible, has loans) | "I need money but don't know what kind of loan"; real need is to pay off his two existing loans with one new loan, revealed only when asked | at least one clarifying reply before any product is selected; `get_credit_products` or `search_banking_policies` (model) before the product is chosen; no eligibility before a product; product ends `refinancing_unsecured` **or** `personal_loan` (both list consolidation-type purposes in `products.yaml`, so either is a correct choice; designer's call) |
| `changes_mind` | Alex Morgan (eligible) | starts a personal loan for a car; after giving income, switches to buying a flat (message marked `switch: true`) | `product_code` changes `personal_loan` → `mortgage_casa_ta`; no model call of `run_eligibility_check` or `calculate_loan_offer` between the switch turn and the accepted product change; requirements for the new product requested (code call); no re-asking of fields both products share (judge) |
| `rag_questions` | Maria Stoica | asks three general questions (documents needed for a personal loan, what DAE means, whether early repayment has a fee), no application | `search_banking_policies` (model) for each question; replies cite sources (`turn_finished.citations` non-empty); intent `product_info`; no `run_eligibility_check` or `calculate_loan_offer` (any caller); no accepted `product_code` update |

Briefs and rubrics are the builder's to write in this spirit; the table fixes
the customers, behaviour and key checks.

### Trace checks (deterministic)

Each check reads the session's trace events (`docs/superpowers/specs/2026-10-29-agent-trace-design.md`
§4.1) and returns pass/fail with evidence (turn and step). Check types:

- `intent_seen {intent, within_turns?}`: some `action_parsed` with that intent
  (within the first N customer turns if given).
- `tool_called {tool, caller: model|code|any = model, min = 1, max?}`,
  `tool_not_called {tool, caller = any}`.
- `tool_order {before, after}`: the first successful `before` precedes the
  first successful `after`.
- `tool_before_product {tools: [...]}`: one of the tools succeeds before the
  first accepted `product_code` field update.
- `no_tool_before_product {tool}`.
- `clarifying_before_product {min_replies = 1}`: at least N agent replies
  (`turn_finished` with a reply and no accepted `product_code` yet) before the
  first accepted `product_code` update.
- `product_final {product | products: [...]}` and `product_changed {from, to}`.
  The product value comes from the `action_parsed.field_updates` entry for
  `product_code` whose matching `field_updates` result is accepted.
- `no_tool_after_switch {tools}`: no model call of those tools from the
  customer turn the driver recorded as the switch (`switch: true`) until the
  accepted `product_code` update to the new product. Not applicable (reported
  as such, not as a pass) if the simulator never marked a switch.
- Checks that never got a chance to apply (for example the conversation
  stopped first) are reported as `not_applicable`, separately from pass/fail.
- `search_per_question {min}`: at least `min` successful
  `search_banking_policies` calls by the model.
- `cited_answers {min}`: at least `min` turns whose `turn_finished.citations`
  is non-empty.
- `no_model_tool_rejections`: no model-caller `tool_call` with error codes
  `unknown_tool`, `not_model_callable`, `not_allowed_in_flow`,
  `precondition_failed` or `invalid_arguments` (each one listed as evidence).
- `no_failed_turns`: no `turn_finished.outcome` in `fallback`, `step_cap`,
  `model_unavailable`, `error`.

### Judge

- After a conversation, the judge model gets the transcript and, for each agent
  reply, what the agent was waiting for at that point (from the trace
  `model_call.context` needs). It grades:
  - a fixed general rubric for every reply: asks at most two things at once;
    does not re-ask information already given; clear plain English; no
    invented numbers or promises (amounts, rates or decisions must come from
    tool results in the transcript);
  - the scenario's rubric, once for the whole conversation.
- Output JSON: `{"replies": [{"turn": n, "scores": {criterion: {"pass": bool,
  "reason": str}}}], "scenario": {criterion: {"pass": bool, "reason": str}}}`,
  validated with Pydantic. On invalid JSON: one retry, then an evaluation
  error.

### Report

Per run: `data/local/eval/<run_id>/`
- `report.md`: summary table (scenario × check: pass rate over N runs; judge
  criteria pass rate), then per scenario and run: stop reason, transcript,
  check results with evidence, judge grades with reasons, link to the rendered
  trace;
- `results.json`: the same, machine-readable;
- `traces/`: JSONL and rendered Markdown per session.

Simulator or judge errors appear in their own column, never folded into agent
pass rates.

## Testing

- `checks.py`: one unit test per check type on small hand-built event lists,
  plus one recorded trace from the existing scripted e2e run
  (`DemoChatModel`) checked end to end.
- `customer.py` and `judge.py`: parsing, validation and the single retry,
  using `FakeChatModel`.
- `driver.py`: one test driving a short conversation with `DemoChatModel` as
  the agent and a scripted `FakeChatModel` customer, `--retrieval stub`,
  asserting the trace directory and stop reason.
- A real run (`--runs 1`, all scenarios) is done by the owner in their own
  PowerShell with RAG; results reviewed together.

## Decided by the owner

- Success is behaviour along the way (questions, intent clarification, tool
  calls), not reaching submission.
- A second model judges wording.
- The customer is a simulated model following a scenario brief.
- Approach B: runner script with a report, N runs, pass rates.

## Left to the builder (designer's calls)

- Exact module/function names inside `scripts/eval/`.
- Judge model choice on Featherless (different family from the agent).
- Brief and rubric wording.
- Default `--runs` (3) and `--max-turns` (25).
