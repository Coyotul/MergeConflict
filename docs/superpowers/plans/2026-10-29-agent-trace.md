# Agent Decision Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every orchestrator session writes an append-only JSONL trace of all decisions (model calls with context, parsed actions, field-update results, tool calls, code events, outcomes), and a script renders it as a Markdown timeline.

**Architecture:** A small `Tracer` (Null / InMemory / File) injected into `Orchestrator` like the session store; the turn loop and events mixin call it at fixed points; `FeatherlessChatModel` exposes `last_usage`; composition builds the tracer from settings; `scripts/trace_report.py` renders a session's file.

**Tech Stack:** Python 3.12, Pydantic settings, stdlib `json`/`logging`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-agent-trace-design.md` — §4.1 event table is the binding wire format.

## Global Constraints

- Branch `feat/agent-trace` (worktree `C:/Users/vladb/Documents/Hackathon/MergeConflict/.claude/worktrees/feat+orchestrator`). Backend + scripts only; do not touch `apps/`, `packages/`, `tests/e2e/` frontend files.
- Python `C:/Users/vladb/Documents/Hackathon/MergeConflict/.venv/Scripts/python.exe`; run `"$PY" -m pytest tests/unit tests/integration tests/contract -q` (do not run Playwright; dev servers are running on 3000/3001/4010/8000 for the owner — don't stop or start them). Known pre-existing failure: `tests/contract/test_eligibility_contract.py`.
- Commits per `GIT_AGENT_PROTOCOL.md` (`agent(orchestrator): ...`, Details/Status/Next), ending with exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; stage by explicit path; never commit `.superpowers/`, `*.log`, `data/local/`.
- Trace file: `data/local/traces/<session_id>.jsonl`; session ids must match `^[0-9a-f]{32}$` (else the event is skipped). JSON via `json.dumps(obj, ensure_ascii=False, default=str)`.
- Every line has `ts` (ISO-8601 UTC), `session_id`, `turn_id` (or null), `step` (or null), `type`, plus the payload fields named in spec §4.1 — use those exact type names and field names.
- `system_prompt` written once per session (in `session_started`; again only as `system_prompt_changed` when `PROMPT_VERSION` differs from the last one in that file).
- Truncate `raw_output` and tool `output` (serialized) to 20000 characters, adding `"truncated": true` on that event.
- Tracing must never raise into the turn: wrap every write; log failures at warning once per session on logger `src.agent.trace`.
- Never trace secrets (settings allow-list only: model, temperature, json_mode, max_steps, history_window) or document bytes.
- Settings: `trace: Literal["file","off"] = "file"` (env `ORCHESTRATOR_TRACE`), `traces_dir: Path = Path("data/local/traces")` (env `ORCHESTRATOR_TRACES_DIR`); add to `.env.example`.

## Review Focus

1. **Disk/permission failure while tracing** (traces dir is a file, or unwritable): the customer's turn completes normally and returns the same response as with tracing off. Test: `test_tracer_failure_does_not_break_turn` (Task 2) and `test_file_tracer_swallows_write_errors` (Task 1).
2. **Backend restart mid-session** (resume an existing session): the system prompt is not re-written each turn after restart; only re-written when the prompt version changed. Test: `test_system_prompt_once_across_instances` (Task 1).
3. **Large tool outputs / long model replies**: lines stay bounded (truncated with marker), file remains valid JSONL. Test: `test_truncation_marker` (Task 1).
4. **Model unavailable mid-turn and code-handled events**: trace still shows what happened (model_call with error, turn_finished outcome `model_unavailable`; confirmation's code tool call + code_event even when the model then fails). Tests in Task 2.
5. **Unknown/new event types in an old report script**: rendered raw, not crashing. Test in Task 3.

---

### Task 1: Tracer module, settings, composition, logging

**Files:** Create `src/agent/orchestration/trace.py`; Modify `src/core/settings.py`, `src/core/composition.py`, `src/api/app.py` (logging config), `.env.example`; Test `tests/unit/orchestrator/test_trace.py`

**Interfaces — Produces:**
- `class Tracer(Protocol)`: `record(self, session_id: str, turn_id: str | None, step: int | None, type: str, **payload: Any) -> None`; `needs_system_prompt(self, session_id: str, prompt_version: str) -> bool` (true when this session's file has no prompt yet or a different version; after it returns true the caller writes `session_started`/`system_prompt_changed`, and the tracer remembers the version).
- `NullTracer`, `InMemoryTracer` (`events: list[dict]`, same line shape as the file), `FileTracer(root: Path, clock: Callable[[], datetime] = utc_now)`.
- `truncate_payload(value: Any, limit: int = 20000) -> tuple[Any, bool]` helper used for `raw_output`/`output`.
- `build_tracer(settings) -> Tracer` in composition; `build_orchestrator` passes it to `Orchestrator(..., tracer=...)` (Task 2 adds the constructor parameter; in this task add it to `Orchestrator.__init__` with default `NullTracer()` and store it, without call sites).
- `create_app`: if the `src` logger has no handlers, attach a `StreamHandler` to stderr at INFO with format `%(asctime)s %(levelname)s %(name)s %(message)s`; set `logging.getLogger("src").setLevel(logging.INFO)`; don't touch uvicorn's loggers.

- [ ] **Step 1: Failing tests** — `test_file_tracer_writes_jsonl_lines` (two records → two parseable lines with ts/session_id/turn_id/step/type + payload, Decimal and datetime serialize), `test_file_tracer_appends_across_instances`, `test_invalid_session_id_skipped`, `test_file_tracer_swallows_write_errors` (root path is an existing file → no exception, one warning logged), `test_system_prompt_once_across_instances` (needs_system_prompt true once; new FileTracer on same root → false for same version, true for a new version), `test_truncation_marker`, `test_settings_trace_defaults_and_env`, `test_build_tracer_off_returns_null`.
- [ ] **Step 2:** run them → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** run the test file, then the suite command from Global Constraints → pass.
- [ ] **Step 5:** commit `agent(orchestrator): add session trace recorder and settings`.

---

### Task 2: Instrument the orchestrator

**Files:** Modify `src/agent/orchestration/orchestrator.py`, `src/agent/orchestration/events.py`, `src/integrations/llm/chat.py`; Test `tests/unit/orchestrator/test_trace_orchestrator.py`, extend `tests/unit/orchestrator/test_llm_adapter.py`

**Interfaces — Consumes:** Task 1 tracer. **Produces:** the events of spec §4.1 at these points:
- `start_session`: `session_started` (if `needs_system_prompt`) then the greeting turn's events.
- Every `handle` / `start_session` turn: `turn_started` (event kind + safe fields, stage, needs kinds/targets, state version) … `turn_finished` (outcome `replied|fallback|step_cap|model_unavailable|error`, reply, citation ids, steps_used, stage_before/after, awaiting_kind, duration_ms, saved). `turn_finished` is written in a `finally` so it appears even when an exception propagates (outcome `model_unavailable` for ModelUnavailable, else `error`), then the exception re-raises unchanged.
- Before each model call in a turn: `system_prompt_changed` if `needs_system_prompt` says the version changed.
- Each model call: `model_call` (context = the dict passed into CONTEXT_JSON — expose it from prompting without changing the messages, e.g. build context once and pass it to `build_messages`, or have `build_messages` return/accept it; keep prompting's public behaviour and tests green), history count, notices, latency_ms, usage from `getattr(model, "last_usage", None)`, raw_output (truncated), error on ModelUnavailable).
- After parsing: `action_parsed` or `action_invalid(error, will_retry)`.
- After applying updates: `field_updates(results=[{field, accepted, reason}])` (only when there were updates).
- Every `registry.execute` call from orchestrator/events (model and code): `tool_call` with tool, caller, arguments, ok, error_code, error_message, output (truncated), duration_ms — via one helper wrapping execute.
- Citation filtering with drops: `citations_filtered(kept, dropped)`.
- events mixin: `code_event(kind, outcome, detail)` for upload processed (accepted/rejected + reason), offer selected/rejected, confirmation (submitted + application_id | already_submitted | summary_changed | declined | not_submitted).
- `FeatherlessChatModel.complete` sets `self.last_usage = {"prompt_tokens", "completion_tokens", "total_tokens"}` from `response.usage` (None when absent; reset to None before each call).

- [ ] **Step 1: Failing tests** (InMemoryTracer + FakeChatModel + stub registry via the existing `orchestrator_factory` in `tests/unit/orchestrator/conftest.py`; extend the factory with an optional `tracer` arg):
  - `test_tool_then_reply_event_sequence` — exact type sequence `turn_started, model_call, action_parsed, tool_call, model_call, action_parsed, turn_finished`; model_call.context has `needs` and `tools`; turn_finished.outcome == "replied".
  - `test_session_started_has_prompt_once` — start_session then two messages → one `session_started` with `system_prompt` and `prompt_version`; no `system_prompt_changed`.
  - `test_invalid_json_traced_then_fallback` — `action_invalid(will_retry=True)`, `action_invalid(will_retry=False)`, outcome `fallback`.
  - `test_rejected_field_update_traced` — field_updates results include `{field:"amount", accepted:False, reason startswith "invalid_value"}`.
  - `test_confirmation_traces_code_tool_and_event` — seeded awaiting-confirmation state → tool_call(tool="submit_application", caller="code", ok=True) and code_event(kind="confirmation", outcome="submitted").
  - `test_model_unavailable_traced` — FakeChatModel "!unavailable" on a message turn → model_call with error, turn_finished outcome "model_unavailable", exception still raised.
  - `test_tracer_failure_does_not_break_turn` — tracer whose record raises → TurnResponse identical (text, stage, blocks) to a run with NullTracer.
  - `test_featherless_sets_last_usage` (in test_llm_adapter.py) — stub client response with usage → `last_usage` dict; without usage → None.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** run the new tests, then the Global Constraints suite (all existing orchestrator/contract/e2e-python tests green).
- [ ] **Step 5:** commit `agent(orchestrator): trace every agent decision per session`.

---

### Task 3: Readable trace report and docs

**Files:** Create `scripts/trace_report.py`; Test `tests/unit/orchestrator/test_trace_report.py`; Modify `README.md` (short "Agent decision trace" section under the orchestrator docs), `contracts/http/README.md` not needed.

**Interfaces — Produces:** `render_report(events: list[dict], *, full: bool = False) -> str`; `load_events(path: Path) -> list[dict]` (skips blank/invalid lines, counts them); CLI `python scripts/trace_report.py <session_id> [--traces-dir DIR] [--out FILE] [--full]` → writes Markdown (default `<traces-dir>/<session_id>.md`) and prints its path; exit code 1 with a clear message if the trace file is missing.

Report layout per spec §4.5: header (session, customer, model, prompt version, started; system prompt in `<details>`); per turn "## Turn N — <trigger> (<stage_before> → <stage_after>, <duration_ms> ms)"; steps in order with model call (latency, tokens, notices, needs summary), parsed action (intent; tool name or reply excerpt ≤ 200 chars), field updates as `✓ amount` / `✗ amount — invalid_value: …`, tool calls (`model`/`code`, ok or error code, one-line output summary), invalid outputs, citations kept/dropped, code events; ends with outcome and reply. `--full` adds context JSON and tool outputs as fenced ```json blocks. Unknown event types listed raw as fenced JSON.

- [ ] **Step 1: Failing tests** — build a fixture event list (or generate one with InMemoryTracer through a real orchestrator run with FakeChatModel) → report contains the turn heading with stages, `✓`/`✗` lines with reasons, tool lines with caller, outcome line, `<details>` with the system prompt; `--full`/`full=True` includes the context JSON; unknown type rendered raw; `load_events` skips a corrupt line; CLI missing file → exit 1.
- [ ] **Step 2:** run → FAIL. **Step 3:** implement. **Step 4:** run tests + suite.
- [ ] **Step 5:** README section: where traces live, `ORCHESTRATOR_TRACE` / `ORCHESTRATOR_TRACES_DIR`, how to run the report, what each event type means (one line each), that traces contain conversation content (synthetic data only) and live under ignored `data/local/`.
- [ ] **Step 6:** commit `agent(orchestrator): add trace report script and docs`, Status COMPLETED.
