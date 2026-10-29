# Agent decision trace (per-session trace file) — design

Date: 2026-10-29 · Status: draft for approval · Branch: `feat/agent-trace` (stacked on `feat/luma-orchestrator-chat`; backend-only)
References: `docs/superpowers/specs/2026-10-28-orchestrator-design.md` (§7 turn loop), `src/agent/orchestration/orchestrator.py`, `events.py`, `prompting.py`, `src/integrations/llm/chat.py`

## 1. Intent

The owner wants to evaluate the agent's decisions and see exactly how it behaves in the background. Today only part of that is recorded: the session message log keeps tool calls and results, but not the model's plain replies as raw JSON, the context it was given, rejected field updates, retries, fallbacks, latency or tokens, and the step logs are never printed (logging is not configured). This work writes one append-only trace file per session that records every decision, plus a script that renders it as a readable timeline.

## 2. Goals, non-goals, anti-goals

**Goals**
- One file per session: `data/local/traces/<session_id>.jsonl`, one JSON object per line, written as events happen (survives a crash mid-turn).
- Every model step, parse result, field-update decision, tool call (model and code), code-handled event, fallback and turn outcome is recorded with timing.
- The system prompt is stored once per session (owner's decision), re-stored only if its version changes; each model call stores the context JSON it was given (owner's decision), not the full message list.
- A script renders a session's trace to a readable Markdown timeline.
- Tracing can be switched off; it never breaks or slows a turn noticeably.

**Non-goals**
- OpenTelemetry/Jaeger/Langfuse, dashboards, a browser view, an API endpoint.
- Evaluation scoring or automatic judgement of decisions.
- Changing prompts, tools or orchestrator behaviour.
- Tracing the frontend.

**Anti-goals**
- A trace write failure (disk full, permission) failing or altering a customer's turn.
- The Featherless API key or any secret appearing in a trace.
- Trace files committed to Git (they live under ignored `data/local/`).

## 3. Approaches considered

| Option | Summary | Trade-off |
|---|---|---|
| **1. Explicit `Tracer` interface called by the turn loop (chosen)** | A small typed recorder injected like the session store; file and in-memory implementations; `ORCHESTRATOR_TRACE=file|off`. | Exact, typed events and easy tests, no dependencies; about a dozen call sites. |
| 2. Python `logging` + per-session JSON file handler | Grow the existing log lines into events. | Awkward per-session routing, structured data squeezed into log records, mixed with app logs. |
| 3. OpenTelemetry spans to a file exporter | Standard tracing. | New dependencies; large context/prompt doesn't fit span attributes; hard to read as a file. |

The owner chose **1**.

## 4. Design

### 4.1 Event model (`src/agent/orchestration/trace.py`)
Every line: `{"ts": ISO-8601 UTC, "session_id", "turn_id" (null for session-level), "step" (int|null), "type", ...payload}`. Types and payloads:

| type | when | payload |
|---|---|---|
| `session_started` | session created | `customer_id`, `model`, `temperature`, `json_mode`, `max_steps`, `history_window`, `prompt_version`, `system_prompt` (full text) |
| `system_prompt_changed` | first model call of a turn when `PROMPT_VERSION` differs from the last one written for this session (e.g. resumed after a deploy) | `prompt_version`, `system_prompt` |
| `turn_started` | start of `handle`/`start_session` | `event` (kind + safe fields: message text; upload doc_type/filename/size; offer_id; summary_version/decision), `stage`, `needs` (kind/target list), `state_version` |
| `code_event` | code-handled event result (upload processed, offer selected/rejected, confirmation outcome) | `kind`, `outcome`, `detail` (e.g. rejection reason, application_id) |
| `model_call` | each model call | `context` (the exact CONTEXT_JSON object sent), `history_messages` (count), `notices` (list), `latency_ms`, `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens` or null), `raw_output` (text), `error` (null or `{code, message}` for ModelUnavailable) |
| `action_parsed` | parse ok | `intent`, `field_updates` (as proposed), `action` (`{type, tool, arguments}` or `{type, message, citation_ids}`) |
| `action_invalid` | parse error | `error`, `will_retry` (bool) |
| `field_updates` | after applying | `results` (`[{field, accepted, reason}]`) |
| `tool_call` | every registry execute (model or code) | `tool`, `caller`, `arguments`, `ok`, `error_code`, `error_message`, `output` (JSON, truncated per §4.4), `duration_ms` |
| `citations_filtered` | when citation ids dropped | `kept`, `dropped` |
| `turn_finished` | end of a turn (success, fallback or error) | `outcome` (`replied` \| `fallback` \| `step_cap` \| `model_unavailable` \| `error`), `reply` (text or null), `citations` (ids), `steps_used`, `stage_before`, `stage_after`, `awaiting_kind`, `duration_ms`, `saved` (bool) |

### 4.2 Tracer interface
- `class Tracer(Protocol)`: `def record(self, session_id: str, turn_id: str | None, step: int | None, type: str, **payload) -> None`. Event-specific helper methods are the builder's call; the wire format above is binding.
- `NullTracer` (no-op), `InMemoryTracer` (list of dicts, for tests), `FileTracer(root: Path)`.
- `FileTracer`: appends one line per event to `<root>/<session_id>.jsonl` (validate `session_id` like `FileSessionStore`: 32 lowercase hex, else skip), `json.dumps(..., ensure_ascii=False, default=str)` so Decimals/datetimes serialize, opens in append mode per write and flushes (simple and crash-safe at this volume). It remembers per session the last `prompt_version` written (reading it from the file's existing lines on first use, so a restart doesn't re-write the prompt every turn).
- **Never raises:** every `record` is wrapped; failures are logged once per session at warning level (`src.agent.trace`) and swallowed.

### 4.3 Where events come from
- `Orchestrator.__init__` gains `tracer: Tracer = NullTracer()`; `start_session`, `handle`, `_run_model_steps`, the code-tool path, field-update application and the events mixin call it at the points in §4.1. Tool calls are traced by wrapping the orchestrator's calls to `registry.execute` (one helper), not by changing the registry.
- Token usage: `FeatherlessChatModel` keeps the last response's usage on `self.last_usage` (dict or None) after each `complete`; the orchestrator reads `getattr(model, "last_usage", None)` right after the call. `ChatModel` protocol and the fake/demo models are unchanged (designer's call: non-breaking).
- Composition: `OrchestratorSettings` gains `trace: Literal["file", "off"] = "file"` (env `ORCHESTRATOR_TRACE`) and `traces_dir: Path = Path("data/local/traces")` (env `ORCHESTRATOR_TRACES_DIR`); `build_orchestrator` builds the tracer. Add both to `.env.example`.

### 4.4 Size and safety
- `system_prompt` once per session; context per model call; tool `output` and `raw_output` truncated to 20,000 characters with a `"truncated": true` marker (designer's call).
- No secrets: settings fields traced are an explicit allow-list (model, temperature, json_mode, max_steps, history_window); never the settings object or headers. Document bytes are never traced (upload events carry doc_type, filename, size only).
- `data/local/` is already git-ignored; verify `data/local/traces/` is covered.

### 4.5 Readable report (`scripts/trace_report.py`)
- `python scripts/trace_report.py <session_id> [--traces-dir DIR] [--out FILE] [--full]` writes Markdown (default `data/local/traces/<session_id>.md`) and prints the path.
- Layout: header (session, customer, model, prompt version, start time; system prompt in a collapsed `<details>` block); then per turn a section "Turn N — <trigger> (<stage before> → <stage after>, <duration>)" listing each step in order: model call (latency, tokens, notices, needs summary), parsed action (intent, tool or reply excerpt), field-update results (✓/✗ with reasons), tool calls (caller, ok/error, short output summary), invalid output/retry, citations kept/dropped; ends with the final reply and outcome.
- By default context JSON and tool outputs are shown as one-line summaries; `--full` includes them as fenced JSON. Unknown event types are listed raw (forward compatible).

### 4.6 Logging (bonus, tiny)
`create_app` configures the `src` logger hierarchy at INFO to stderr if no handlers are configured, so existing `orchestrator_step` lines appear in the console (designer's call; option A from the conversation, nearly free).

### 4.7 Testing
- Unit (`tests/unit/orchestrator/test_trace.py`): FileTracer writes valid JSON lines, appends, skips invalid session ids, swallows write errors (e.g. root is a file), stores the system prompt once per session across tracer instances, truncation marker.
- Orchestrator with `InMemoryTracer` + `FakeChatModel`: a turn with a tool call and a reply produces the event sequence `turn_started, model_call, action_parsed, tool_call, model_call, action_parsed, turn_finished` with expected fields; invalid JSON produces `action_invalid(will_retry=true)` then fallback outcome; rejected field update recorded with reason; code-handled confirmation records `code_event` and a code `tool_call(caller="code")`; ModelUnavailable records `model_call.error` and `turn_finished.outcome="model_unavailable"`; tracer raising does not break the turn.
- Report script: renders a fixture trace to Markdown containing the turn headings, ✓/✗ updates and outcome; `--full` includes context JSON.
- Existing suites stay green (contract OpenAPI unchanged; the known eligibility drift test excepted).

## 5. Decided with the owner
- Output is a file.
- Approach 1 (explicit Tracer).
- System prompt stored once per session; each model call stores the state/context it was given.

## 6. Designer's calls (owner may override)
- Branch stacked on `feat/luma-orchestrator-chat` so the running Luma test servers keep working.
- JSON lines + generated Markdown report via a script (no API/UI).
- Token usage via `last_usage` attribute instead of changing the `ChatModel` protocol.
- 20,000-char truncation for tool outputs and raw model text.
- Tracing on by default (`file`), switchable with `ORCHESTRATOR_TRACE=off`.
- Configure `src.*` logging at INFO (existing step logs become visible).

## 7. Left to the builder
Helper method names on the tracer, exact Markdown formatting, how the report summarises each event, internal file split.
