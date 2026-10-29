# Conversation Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A runner that plays scenario briefs through the real agent with a simulated customer, checks each session trace deterministically, has a judge model grade the replies, and writes a report with pass rates over N runs.

**Architecture:** `scripts/eval/` package: `checks.py` (pure functions over trace events), `customer.py` + `judge.py` (Featherless-backed models with validated JSON), `driver.py` (one in-process conversation via `create_app` + `TestClient`), `report.py` + `run_scenarios.py` (CLI, N runs, Markdown/JSON). Scenarios in `config/eval/scenarios.yaml`.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI TestClient, existing `FeatherlessChatModel`/`FakeChatModel`, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-conversation-eval-design.md`

## Global Constraints

- Branch `integrate/eligibility-local-rag`; venv `../../../.venv/Scripts/python`; tests use `--basetemp=.pytest_tmp -p no:cacheprovider` (system temp is not writable).
- Agent, customer and judge all use Featherless through `FeatherlessChatModel` (only `FEATHERLESS_API_KEY` exists). Customer model `EVAL_CUSTOMER_MODEL` (default: agent model, temperature 0.7); judge model `EVAL_JUDGE_MODEL` (temperature 0, a different family from the agent).
- Unit tests make no network calls (use `FakeChatModel`, `DemoChatModel`, `--retrieval stub`).
- Outputs only under ignored `data/local/eval/<run_id>/`; never write the API key.
- Orchestrator clock pinned to `2026-10-28T12:00:00Z` for every eval session (as in `tests/e2e/test_chat_scenarios.py::make_app`).
- Model-only tools: `run_eligibility_check`, `calculate_loan_offer`. Check `caller` defaults: `tool_called` → `model`, `tool_not_called` → `any`.
- Never send a confirmation; stop when `awaiting.kind == "confirmation"`.
- Simulator/judge errors are reported separately and never count as agent pass/fail.

## Review Focus

- Simulator returns non-JSON or an unknown action twice → conversation stops with stop reason `customer_error`, recorded, not a crash. Test in Task 2.
- Agent turn returns HTTP error (e.g. 503 model unavailable) → driver records it and stops with `agent_error`; checks still run on the partial trace. Test in Task 3.
- Simulator asks to upload a document type the agent didn't request, or chooses an unknown offer ID → driver rejects the action, tells the simulator once, then stops with `customer_error`. Test in Task 3.
- A check whose precondition never occurred (no switch marked, no product ever chosen) → `not_applicable`, not pass. Test in Task 1.
- Trace file missing or empty for a session → every check `not_applicable` with evidence "no trace". Test in Task 1.

---

### Task 1: Deterministic trace checks

**Files:**
- Create: `scripts/eval/__init__.py`, `scripts/eval/checks.py`
- Test: `tests/unit/eval/__init__.py`, `tests/unit/eval/test_checks.py`

**Interfaces:**
- Produces:
  - `CheckResult(BaseModel)`: `check: str`, `status: Literal["pass","fail","not_applicable"]`, `evidence: list[str]` (e.g. `"turn 3 step 1: run_eligibility_check (model) ok"`), `params: dict`.
  - `run_check(spec: dict, events: list[dict], *, switch_turn_ids: list[str] = []) -> CheckResult` where `spec["check"]` selects the check and the rest are params.
  - `run_checks(specs: list[dict], events: list[dict], *, switch_turn_ids: list[str] = []) -> list[CheckResult]`.
- Check names and params exactly as in the spec "Trace checks" section: `intent_seen{intent, within_turns?}`, `tool_called{tool, caller="model", min=1, max?}`, `tool_not_called{tool, caller="any"}`, `tool_order{before, after}`, `tool_before_product{tools}`, `no_tool_before_product{tool}`, `clarifying_before_product{min_replies=1}`, `product_final{product|products}`, `product_changed{from, to}`, `no_tool_after_switch{tools}`, `search_per_question{min}`, `cited_answers{min}`, `no_model_tool_rejections`, `no_failed_turns`. Unknown check name → `ValueError`.
- Event facts used (trace spec §4.1): `turn_started` (one per customer turn; turns counted in order, greeting turn excluded), `action_parsed{intent, field_updates, action}`, `field_updates{results:[{field, accepted, reason}]}`, `tool_call{tool, caller, ok, error_code}`, `turn_finished{outcome, reply, citations}`. Accepted product value = `action_parsed.field_updates` entry `field == "product_code"` in the same turn+step whose `field_updates` result is accepted.

- [ ] **Step 1: Failing tests** in `test_checks.py` using a small event-builder helper (`ev(type, turn, step, **payload)`): one pass and one fail test per check type, plus `test_no_switch_marked_is_not_applicable`, `test_product_final_without_product_is_not_applicable`, `test_empty_events_all_not_applicable`, `test_code_call_does_not_satisfy_model_tool_called`, `test_rejections_listed_as_evidence`, `test_unknown_check_raises`.
- [ ] **Step 2:** Run `../../../.venv/Scripts/python -m pytest tests/unit/eval/test_checks.py -q --basetemp=.pytest_tmp -p no:cacheprovider`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `checks.py`.
- [ ] **Step 4:** Rerun. Expected: PASS.
- [ ] **Step 5:** Also run all checks over a trace recorded from the scripted e2e happy path: generate one with `DemoChatModel` in a test (`create_app` with `trace="file"`, `traces_dir` in a local tmp) via the same flow as `tests/e2e/test_chat_scenarios.py::test_happy_path_alex_morgan`; assert `tool_order{before: run_eligibility_check, after: calculate_loan_offer}` passes and `no_failed_turns` passes (`test_checks_on_recorded_demo_trace`).

---

### Task 2: Simulated customer and judge

**Files:**
- Create: `scripts/eval/models.py` (model factory), `scripts/eval/customer.py`, `scripts/eval/judge.py`
- Test: `tests/unit/eval/test_customer.py`, `tests/unit/eval/test_judge.py`

**Interfaces:**
- `models.py`: `build_eval_model(role: Literal["customer","judge"], base: OrchestratorSettings) -> ChatModel` — `FeatherlessChatModel(base.model_copy(update={"model": ..., "temperature": ...}))` with model from `EVAL_CUSTOMER_MODEL` / `EVAL_JUDGE_MODEL` env (customer default `base.model`, judge default required: raise `ConfigurationError("EVAL_JUDGE_MODEL is required")` if unset) and temperatures 0.7 / 0.0.
- `customer.py`:
  - `CustomerAction(BaseModel)`: `type: Literal["say","upload","choose_offer","done"]`, `text: str | None`, `switch: bool = False`, `doc_type: str | None`, `offer_id: str | None`, `reason: str | None` (validator: required field per type).
  - `CustomerView(BaseModel)`: `transcript: list[tuple[Literal["customer","agent"], str]]`, `awaiting_kind: str`, `document_types: list[str]`, `offers: list[dict]` (`offer_id`, `term_months`, `monthly_installment`), `feedback: str | None` (driver's note on a rejected action).
  - `class SimulatedCustomer: __init__(self, model: ChatModel, brief: str)`; `next_action(self, view: CustomerView) -> CustomerAction`. One retry on invalid JSON/validation (re-asking with the error), then raises `EvalModelError`.
  - System prompt (exact intent, builder's wording): play the customer in the brief; answer only what the agent asked; reveal "only if asked" facts only when asked; follow timed changes and mark that message `switch: true`; English; respond with exactly one JSON action; upload only requested document types; choose only listed offer IDs; `done` when the brief's goal is reached.
- `judge.py`:
  - `Grade(BaseModel)`: `pass_: bool = Field(alias="pass")`, `reason: str`.
  - `JudgeResult(BaseModel)`: `replies: list[ReplyGrades]` (`turn: int`, `scores: dict[str, Grade]`), `scenario: dict[str, Grade]`.
  - `GENERAL_RUBRIC: list[str]` = the four general criteria from the spec (at most two asks at once; no re-asking given information; clear plain English; no invented numbers/promises — numbers/decisions only from tool results).
  - `judge_conversation(model: ChatModel, transcript: list[dict], scenario_rubric: list[str]) -> JudgeResult`; each transcript item: `{turn, customer, agent, awaiting_before: list[str], tool_results: list[str]}`. One retry on invalid JSON, then `EvalModelError`.
- `EvalModelError(Exception)` lives in `models.py`.

- [ ] **Step 1: Failing tests:** `test_customer_parses_say_with_switch`, `test_customer_retries_once_then_raises` (FakeChatModel returns `"nope"` twice → `EvalModelError`), `test_customer_rejects_upload_without_doc_type`, `test_customer_prompt_contains_brief_and_awaiting` (inspect messages passed to a FakeChatModel callable), `test_judge_parses_grades`, `test_judge_retry_then_error`, `test_judge_prompt_lists_general_and_scenario_rubric`, `test_build_eval_model_requires_judge_model` (monkeypatch env).
- [ ] **Step 2:** Run the two test files. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun. Expected: PASS.

---

### Task 3: Documents, driver and scenarios

**Files:**
- Modify: `tests/fixtures/documents.py` — `income_text`/`statement_text`/`document_bytes` gain `employer: str = "TechCorp SRL"`, `employment_start: date = date(2021, 4, 1)`, `obligations: str = "400,00"`, `net: str` already exists; `document_bytes(doc_type, *, first_name, last_name, cnp, net="6.200,00", employer=..., employment_start=..., obligations=...)`. Defaults unchanged so existing tests keep passing.
- Create: `scripts/eval/driver.py`, `config/eval/scenarios.yaml`
- Test: `tests/unit/eval/test_driver.py`

**Interfaces:**
- Consumes: `CustomerAction`, `CustomerView`, `SimulatedCustomer.next_action`, `EvalModelError` (Task 2) — tests use a scripted stand-in object with `next_action`.
- Produces:
  - `Scenario(BaseModel)`: `id, customer_id, brief, stop_when: Literal["offers_shown","eligibility_result","never"] = "never", checks: list[dict], rubric: list[str]`; `load_scenarios(path: Path) -> list[Scenario]`.
  - `ConversationResult(BaseModel)`: `scenario_id, session_id, stop_reason: Literal["customer_done","stop_when","awaiting_confirmation","max_turns","customer_error","agent_error"]`, `transcript: list[dict]` (judge format of Task 2), `switch_turn_ids: list[str]`, `trace_path: Path`, `error: str | None`.
  - `customer_documents(customer_id: str, config_dir: Path, db_path: Path, bindings_path: Path) -> dict[str, bytes]`: builds the three PDFs with name from `customers.yaml` profile, figures from its `documents` section (net income formatted `"4.500,00"`, employer, obligations; employment start = 2026-10-28 minus `employment_months`), CNP = `cnp_for(sex_digit + yymmdd + "41001")` from the person's birth date and the bound CNP's first digit in `persons`.
  - `run_conversation(app: FastAPI, scenario: Scenario, customer, *, max_turns: int, documents: dict[str, bytes], traces_dir: Path) -> ConversationResult`. Uses `TestClient(app)`; header `X-Customer-Id`; endpoints `/chat/sessions`, `/messages`, `/documents`, `/offer-selection`. `transcript[i].awaiting_before` = needs from the latest `model_call.context` of that turn in the trace; `tool_results` = short `tool` + ok/error per `tool_call` of that turn.
  - `build_eval_app(settings: OrchestratorSettings) -> FastAPI`: `create_app(settings)` then pin `app.state.orchestrator._clock` to 2026-10-28T12:00Z.
- Scenarios: the four from the spec table (`knows_loan` Elena Popa, `unsure_type` Radu Mihai with `product_final{products:[refinancing_unsecured, personal_loan]}`, `changes_mind` Alex Morgan with `product_changed{from: personal_loan, to: mortgage_casa_ta}` and `no_tool_after_switch{tools:[run_eligibility_check, calculate_loan_offer]}`, `rag_questions` Maria Stoica). Brief figures must equal `customers.yaml` `stated`/`documents` values for that customer. Every scenario includes `no_model_tool_rejections` and `no_failed_turns`.

- [ ] **Step 1: Failing tests** with `DemoChatModel` agent (`model="fake"`, `retrieval="stub"`, `trace="file"`, memory store, credit DB built via `scripts.credit_sources.setup.create_database` under a local tmp) and a scripted customer: `test_driver_runs_until_customer_done` (stop reason `customer_done`, trace file exists, transcript non-empty), `test_driver_stops_at_max_turns`, `test_driver_records_switch_turn`, `test_driver_rejects_unrequested_upload_then_customer_error`, `test_driver_records_agent_error` (agent model raising → API 503 → `agent_error`), `test_customer_documents_match_profile` (extracting via `DocumentProcessingService` is not required: assert the PDF text contains `ALEX MORGAN` and a checksum-valid CNP), `test_load_scenarios_valid` (all four load; every check name is known to `checks.run_check` — skip this assertion if Task 1 isn't merged yet).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement fixture changes, `driver.py`, `scenarios.yaml`.
- [ ] **Step 4:** Rerun, plus `tests/integration/orchestrator tests/e2e/test_chat_scenarios.py` (fixture defaults unchanged). Expected: PASS.

---

### Task 4: Report and CLI (after Tasks 1–3)

**Files:**
- Create: `scripts/eval/report.py`, `scripts/eval/run_scenarios.py`
- Modify: `.env.example` (add `EVAL_CUSTOMER_MODEL=`, `EVAL_JUDGE_MODEL=` with a comment), `docs/runbooks/` new `conversation-eval.md` (how to run in own PowerShell with RAG + Postgres, `--retrieval stub` for quick runs)
- Test: `tests/unit/eval/test_report.py`, `tests/unit/eval/test_cli.py`

**Interfaces:**
- `RunRecord(BaseModel)`: `scenario_id, run_index, conversation: ConversationResult, checks: list[CheckResult], judge: JudgeResult | None, judge_error: str | None`.
- `write_report(records: list[RunRecord], out_dir: Path) -> Path` → writes `report.md`, `results.json`, and `traces/<session_id>.md` via `scripts.trace_report.render_report(load_events(path))`. Summary table: rows = scenario × check, columns `pass / fail / n/a / runs`; judge criteria pass rate; column for simulator/judge errors.
- `main(argv: list[str] | None = None) -> int` in `run_scenarios.py`: args `--scenario` (repeatable), `--runs 3`, `--retrieval rag|stub` (default from settings), `--max-turns 25`, `--out` (default `data/local/eval/<UTC yyyymmdd-HHMMSS>`), `--agent-model` (override). Flow: load settings (`load_orchestrator_settings()`), set `trace="file"`, `traces_dir=<out>/traces`, `session_store="memory"`; build app once per run; for each scenario × run: `run_conversation` → `run_checks(scenario.checks, events, switch_turn_ids)` → `judge_conversation` (catch `EvalModelError` → `judge_error`); then `write_report`; print the report path; exit 0 (agent failures are results, not errors), exit 2 on configuration errors.

- [ ] **Step 1: Failing tests:** `test_report_summarises_pass_rates` (two RunRecords with one pass and one fail for the same check → "1 / 1 / 0 / 2"), `test_report_separates_judge_errors`, `test_cli_end_to_end_offline` (`main(["--retrieval","stub","--runs","1","--scenario","knows_loan","--out",tmp])` with `ORCHESTRATOR_MODEL=fake` and monkeypatched `build_eval_model` returning `FakeChatModel`s: a customer that says `done` after one message and a judge returning valid JSON; asserts `report.md` and `results.json` exist and exit code 0).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `../../../.venv/Scripts/python -m pytest tests/unit/eval -q --basetemp=.pytest_tmp -p no:cacheprovider`. Expected: PASS.
- [ ] **Step 5:** Pick the judge default: list Featherless models (`openai.OpenAI(base_url=settings.featherless_base_url, api_key=...).models.list()`), choose an instruction-tuned model of a different family than the agent's (`openai/gpt-oss-*`), set it as `DEFAULT_JUDGE_MODEL` in `models.py` (env still overrides; update the Task 2 test to expect the default instead of the error) and in `.env.example`.
- [ ] **Step 6:** Smoke check without RAG (`FEATHERLESS_API_KEY` is in the main checkout `.env`; load it with `dotenv` from `../../../.env` or the runbook's instructions): `../../../.venv/Scripts/python -m scripts.eval.run_scenarios --retrieval stub --runs 1 --scenario knows_loan`; report the path, stop reason and check results. Do not run `--retrieval rag` from Claude Code.
