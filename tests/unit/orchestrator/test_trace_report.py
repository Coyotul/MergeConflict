"""Trace report script tests."""
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from src.agent.orchestration.trace import InMemoryTracer
from src.agent.orchestration.orchestrator import CustomerMessage
from tests.unit.orchestrator.factories import respond, call


def generate_realistic_fixture(orchestrator_factory) -> list[dict]:
    """Generate a realistic fixture by running a real orchestrator with InMemoryTracer."""
    tracer = InMemoryTracer()
    orch, store, model = orchestrator_factory([
        respond("Bună! Cu ce te pot ajuta?"),
        call("get_credit_products", intent="product_info"),
        respond("Avem trei produse de credit.", intent="product_info"),
    ], tracer=tracer)
    sid = orch.start_session("cust-001").session_id
    orch.handle(sid, "cust-001", CustomerMessage("Ce credite aveți?"))
    return tracer.events


@pytest.fixture
def tmp_test_dir():
    """Create a temporary test directory using .test_tmp pattern."""
    tmp_dir = Path(__file__).parent / ".test_tmp" / uuid4().hex
    tmp_dir.mkdir(parents=True, exist_ok=True)
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def fixture_trace(tmp_test_dir, orchestrator_factory):
    """Create a fixture trace file with realistic events."""
    events = generate_realistic_fixture(orchestrator_factory)
    trace_path = tmp_test_dir / "test_session.jsonl"
    with open(trace_path, "w", encoding="utf-8") as f:
        for event in events:
            json.dump(event, f, ensure_ascii=False, default=str)
            f.write("\n")
    return trace_path, events


def test_load_events_reads_jsonl(fixture_trace):
    from scripts.trace_report import load_events
    trace_path, expected = fixture_trace
    events = load_events(trace_path)
    assert len(events) == len(expected)
    assert events[0]["type"] == "session_started"
    assert any(e["type"] == "turn_finished" for e in events)


def test_load_events_skips_corrupt_lines(tmp_test_dir):
    from scripts.trace_report import load_events
    trace_path = tmp_test_dir / "corrupt.jsonl"
    with open(trace_path, "w", encoding="utf-8") as f:
        f.write('{"type": "valid", "session_id": "test"}\n')
        f.write('this is not json\n')
        f.write('\n')  # blank line
        f.write('{"type": "also_valid", "session_id": "test"}\n')
    events = load_events(trace_path)
    assert len(events) == 2
    assert [e["type"] for e in events] == ["valid", "also_valid"]


def test_load_events_missing_file(tmp_test_dir):
    from scripts.trace_report import load_events
    missing = tmp_test_dir / "missing.jsonl"
    with pytest.raises(FileNotFoundError):
        load_events(missing)


def test_render_report_basic_structure(fixture_trace):
    from scripts.trace_report import render_report
    _, events = fixture_trace
    report = render_report(events, full=False)

    # Check header
    assert "# Agent Decision Trace" in report
    assert "Session:" in report
    assert "Customer:" in report
    assert "Model:" in report
    assert "Prompt version:" in report

    # Check system prompt in details
    assert "<details>" in report
    assert "System Prompt" in report
    assert "</details>" in report

    # Check turn heading with stage transition
    assert "## Turn" in report
    assert "customer_message" in report
    assert "ms)" in report

    # Check outcome
    assert "replied" in report.lower() or "outcome" in report.lower()


def test_render_report_shows_tool_calls(fixture_trace):
    from scripts.trace_report import render_report
    _, events = fixture_trace
    report = render_report(events, full=False)

    # Should show the get_credit_products tool call
    assert "get_credit_products" in report
    assert "model" in report  # caller


def test_render_report_full_mode_includes_context(fixture_trace):
    from scripts.trace_report import render_report
    _, events = fixture_trace
    report = render_report(events, full=True)

    # Full mode should include context JSON in fenced blocks
    assert "```json" in report
    # Context should contain needs
    assert "needs" in report.lower() or "context" in report.lower()


def test_render_report_unknown_event_types():
    from scripts.trace_report import render_report
    events = [
        {"type": "session_started", "session_id": "test", "customer_id": "cust-001",
         "model": "test-model", "prompt_version": "v1", "system_prompt": "Test prompt",
         "temperature": 0.7, "json_mode": True, "max_steps": 4, "history_window": 10,
         "ts": "2026-10-29T10:00:00Z", "turn_id": None, "step": None},
        {"type": "unknown_future_event", "session_id": "test", "turn_id": "turn-1",
         "step": 1, "data": {"some": "payload"}, "ts": "2026-10-29T10:00:01Z"},
    ]
    report = render_report(events, full=False)

    # Unknown events should be rendered as raw JSON
    assert "unknown_future_event" in report
    assert "```json" in report


def test_render_report_field_updates_with_checkmarks(orchestrator_factory):
    from scripts.trace_report import render_report
    tracer = InMemoryTracer()
    orch, store, model = orchestrator_factory([
        respond("Bună! Cu ce te pot ajuta?"),
        respond("Am notat.", intent="credit_application", updates=[
            {"field": "amount", "value": "5000"},
            {"field": "purpose", "value": "invalid_purpose"}
        ]),
        respond("Perfect.", intent="credit_application"),
    ], tracer=tracer)
    sid = orch.start_session("cust-001").session_id
    orch.handle(sid, "cust-001", CustomerMessage("vreau 5000 lei"))

    report = render_report(tracer.events, full=False)

    # Should show field updates with ✓ and ✗
    assert "✓" in report or "✗" in report


def test_cli_writes_markdown_file(tmp_test_dir, fixture_trace):
    """Test CLI writes output and returns exit code 0."""
    import subprocess
    import sys

    trace_path, _ = fixture_trace
    out_path = tmp_test_dir / "output.md"

    result = subprocess.run([
        sys.executable, "-m", "scripts.trace_report",
        str(trace_path.stem),
        "--traces-dir", str(trace_path.parent),
        "--out", str(out_path),
    ], capture_output=True, text=True,
    cwd="C:/Users/vladb/Documents/Hackathon/MergeConflict/.claude/worktrees/feat+orchestrator")

    assert result.returncode == 0
    assert out_path.exists()
    assert "Agent Decision Trace" in out_path.read_text(encoding="utf-8")
    assert str(out_path) in result.stdout


def test_cli_missing_file_exits_1(tmp_test_dir):
    """Test CLI returns exit code 1 for missing trace file."""
    import subprocess
    import sys

    result = subprocess.run([
        sys.executable, "-m", "scripts.trace_report",
        "nonexistent_session_id",
        "--traces-dir", str(tmp_test_dir),
    ], capture_output=True, text=True,
    cwd="C:/Users/vladb/Documents/Hackathon/MergeConflict/.claude/worktrees/feat+orchestrator")

    assert result.returncode == 1
    assert "not found" in result.stderr.lower() or "missing" in result.stderr.lower()


def test_render_raw_output_on_invalid_action(tmp_test_dir):
    """Test that raw_output is always shown in full (fenced) for action_invalid steps."""
    from scripts.trace_report import render_report, load_events

    events = [
        {"type": "session_started", "session_id": "test", "customer_id": "cust-001",
         "model": "test-model", "prompt_version": "v1", "system_prompt": "Test prompt",
         "temperature": 0.7, "json_mode": True, "max_steps": 4, "history_window": 10,
         "ts": "2026-10-29T10:00:00Z", "turn_id": None, "step": None},
        {"type": "turn_started", "session_id": "test", "turn_id": "turn-1", "step": None,
         "event": {"kind": "customer_message", "text": "test"}, "stage": "identify",
         "ts": "2026-10-29T10:00:01Z"},
        {"type": "model_call", "session_id": "test", "turn_id": "turn-1", "step": 1,
         "latency_ms": 100, "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
         "raw_output": "```json\n{broken json", "context": {}, "notices": [], "ts": "2026-10-29T10:00:02Z"},
        {"type": "action_invalid", "session_id": "test", "turn_id": "turn-1", "step": 1,
         "error": "JSON parse error", "will_retry": True, "ts": "2026-10-29T10:00:03Z"},
        {"type": "turn_finished", "session_id": "test", "turn_id": "turn-1", "step": None,
         "outcome": "fallback", "steps_used": 1, "stage_after": "identify", "ts": "2026-10-29T10:00:04Z"},
    ]

    report = render_report(events, full=False)

    # Should show raw_output in full even without --full
    assert "```json" in report
    assert "{broken json" in report
    assert "Invalid action" in report


def test_render_tool_arguments_inline(tmp_test_dir):
    """Test that tool arguments are shown as compact inline JSON."""
    from scripts.trace_report import render_report

    events = [
        {"type": "session_started", "session_id": "test", "customer_id": "cust-001",
         "model": "test-model", "prompt_version": "v1", "system_prompt": "Test",
         "ts": "2026-10-29T10:00:00Z", "turn_id": None, "step": None},
        {"type": "turn_started", "session_id": "test", "turn_id": "turn-1", "step": None,
         "event": {"kind": "customer_message", "text": "test"}, "stage": "identify",
         "ts": "2026-10-29T10:00:01Z"},
        {"type": "model_call", "session_id": "test", "turn_id": "turn-1", "step": 1,
         "latency_ms": 100, "raw_output": "{}", "context": {}, "notices": [],
         "ts": "2026-10-29T10:00:02Z"},
        {"type": "action_parsed", "session_id": "test", "turn_id": "turn-1", "step": 1,
         "intent": "test", "action": {"type": "call_tool", "tool": "test_tool",
         "arguments": {"param1": "value1", "param2": 123}},
         "ts": "2026-10-29T10:00:03Z"},
        {"type": "tool_call", "session_id": "test", "turn_id": "turn-1", "step": 1,
         "tool": "test_tool", "caller": "model", "arguments": {"param1": "value1", "param2": 123},
         "ok": True, "output": {"result": "success"}, "duration_ms": 50,
         "ts": "2026-10-29T10:00:04Z"},
    ]

    report = render_report(events, full=False)

    # Arguments should appear on action_parsed line
    assert 'test_tool({"param1": "value1", "param2": 123})' in report
    # And on tool_call line
    assert "caller=model" in report


def test_render_tool_call_output_summary(tmp_test_dir):
    """Test that tool_call shows one-line output summary."""
    from scripts.trace_report import render_report

    events = [
        {"type": "session_started", "session_id": "test", "customer_id": "cust-001",
         "model": "test-model", "prompt_version": "v1", "system_prompt": "Test",
         "ts": "2026-10-29T10:00:00Z", "turn_id": None, "step": None},
        {"type": "turn_started", "session_id": "test", "turn_id": "turn-1", "step": None,
         "event": {"kind": "customer_message"}, "stage": "identify",
         "ts": "2026-10-29T10:00:01Z"},
        {"type": "tool_call", "session_id": "test", "turn_id": "turn-1", "step": 1,
         "tool": "test_tool", "caller": "code", "arguments": {},
         "ok": True, "output": {"key1": "value1", "key2": "value2", "key3": "value3"},
         "duration_ms": 50, "truncated": False, "ts": "2026-10-29T10:00:02Z"},
        {"type": "tool_call", "session_id": "test", "turn_id": "turn-1", "step": 1,
         "tool": "test_tool2", "caller": "model", "arguments": {},
         "ok": True, "output": [1, 2, 3, 4, 5], "duration_ms": 30, "truncated": False,
         "ts": "2026-10-29T10:00:03Z"},
        {"type": "tool_call", "session_id": "test", "turn_id": "turn-1", "step": 1,
         "tool": "test_tool3", "caller": "model", "arguments": {},
         "ok": False, "error_code": "NOT_FOUND", "error_message": "Resource not found",
         "output": None, "duration_ms": 10, "ts": "2026-10-29T10:00:04Z"},
    ]

    report = render_report(events, full=False)

    # Dict output should show keys
    assert "dict with keys: key1, key2, key3" in report
    # List output should show length
    assert "list[5]" in report
    # Error should show code and message
    assert "NOT_FOUND: Resource not found" in report


def test_render_discarded_reply(tmp_test_dir):
    """Test that discarded replies are labeled correctly."""
    from scripts.trace_report import render_report

    events = [
        {"type": "session_started", "session_id": "test", "customer_id": "cust-001",
         "model": "test-model", "prompt_version": "v1", "system_prompt": "Test",
         "ts": "2026-10-29T10:00:00Z", "turn_id": None, "step": None},
        {"type": "turn_started", "session_id": "test", "turn_id": "turn-1", "step": None,
         "event": {"kind": "customer_message"}, "stage": "identify",
         "ts": "2026-10-29T10:00:01Z"},
        {"type": "model_call", "session_id": "test", "turn_id": "turn-1", "step": 1,
         "latency_ms": 100, "raw_output": "{}", "context": {}, "notices": [],
         "ts": "2026-10-29T10:00:02Z"},
        {"type": "action_parsed", "session_id": "test", "turn_id": "turn-1", "step": 1,
         "intent": "test", "action": {"type": "respond", "message": "First reply"},
         "ts": "2026-10-29T10:00:03Z"},
        # Another model call at step 2 means step 1 reply was discarded
        {"type": "model_call", "session_id": "test", "turn_id": "turn-1", "step": 2,
         "latency_ms": 100, "raw_output": "{}", "context": {}, "notices": [],
         "ts": "2026-10-29T10:00:04Z"},
        {"type": "action_parsed", "session_id": "test", "turn_id": "turn-1", "step": 2,
         "intent": "test", "action": {"type": "respond", "message": "Second reply"},
         "ts": "2026-10-29T10:00:05Z"},
    ]

    report = render_report(events, full=False)

    # First reply should be labeled as discarded
    assert "Reply discarded — model asked again (rejected field updates or notices)" in report
    # Second reply should be normal
    assert "Action parsed" in report


def test_render_code_event_detail(tmp_test_dir):
    """Test that code_event.detail is shown."""
    from scripts.trace_report import render_report

    events = [
        {"type": "session_started", "session_id": "test", "customer_id": "cust-001",
         "model": "test-model", "prompt_version": "v1", "system_prompt": "Test",
         "ts": "2026-10-29T10:00:00Z", "turn_id": None, "step": None},
        {"type": "turn_started", "session_id": "test", "turn_id": "turn-1", "step": None,
         "event": {"kind": "offer_selected"}, "stage": "collect",
         "ts": "2026-10-29T10:00:01Z"},
        {"type": "code_event", "session_id": "test", "turn_id": "turn-1", "step": None,
         "kind": "offer_selected", "outcome": "rejected",
         "detail": {"reason": "offer_expired", "offer_id": "off-123"},
         "ts": "2026-10-29T10:00:02Z"},
    ]

    report = render_report(events, full=False)

    # Detail should be shown
    assert "offer_expired" in report
    assert "off-123" in report


def test_render_turn_finished_error_and_awaiting(tmp_test_dir):
    """Test that turn_finished shows error, awaiting_kind, and saved."""
    from scripts.trace_report import render_report

    events = [
        {"type": "session_started", "session_id": "test", "customer_id": "cust-001",
         "model": "test-model", "prompt_version": "v1", "system_prompt": "Test",
         "ts": "2026-10-29T10:00:00Z", "turn_id": None, "step": None},
        {"type": "turn_started", "session_id": "test", "turn_id": "turn-1", "step": None,
         "event": {"kind": "customer_message"}, "stage": "identify",
         "ts": "2026-10-29T10:00:01Z"},
        {"type": "turn_finished", "session_id": "test", "turn_id": "turn-1", "step": None,
         "outcome": "error", "steps_used": 0, "stage_after": "identify",
         "error": {"type": "ValidationError", "message": "Invalid input"},
         "awaiting_kind": "document", "saved": True, "duration_ms": 100,
         "ts": "2026-10-29T10:00:02Z"},
    ]

    report = render_report(events, full=False)

    # Error, awaiting, and saved should be shown
    assert "ValidationError: Invalid input" in report
    assert "Awaiting: document" in report
    assert "Saved: True" in report


def test_render_citations_with_ids(tmp_test_dir):
    """Test that citation ids are shown, not just counts."""
    from scripts.trace_report import render_report

    events = [
        {"type": "session_started", "session_id": "test", "customer_id": "cust-001",
         "model": "test-model", "prompt_version": "v1", "system_prompt": "Test",
         "ts": "2026-10-29T10:00:00Z", "turn_id": None, "step": None},
        {"type": "turn_started", "session_id": "test", "turn_id": "turn-1", "step": None,
         "event": {"kind": "customer_message"}, "stage": "identify",
         "ts": "2026-10-29T10:00:01Z"},
        {"type": "citations_filtered", "session_id": "test", "turn_id": "turn-1", "step": 1,
         "kept": ["cite-1", "cite-2"], "dropped": ["cite-3", "cite-4", "cite-5"],
         "ts": "2026-10-29T10:00:02Z"},
    ]

    report = render_report(events, full=False)

    # Should show the actual citation IDs
    assert "cite-1, cite-2" in report
    assert "cite-3, cite-4, cite-5" in report
    assert "Kept (2)" in report
    assert "Dropped (3)" in report


def test_load_events_skips_non_objects_and_counts(tmp_test_dir):
    """Test that load_events skips non-object lines and lines without 'type' and counts them."""
    from scripts.trace_report import load_events, get_skipped_lines_count

    trace_path = tmp_test_dir / "skip_test.jsonl"
    with open(trace_path, "w", encoding="utf-8") as f:
        f.write('{"type": "valid", "session_id": "test"}\n')
        f.write('"just a string"\n')  # Not an object
        f.write('[1, 2, 3]\n')  # Not an object
        f.write('{"session_id": "test"}\n')  # Missing 'type'
        f.write('{"type": "also_valid", "session_id": "test"}\n')

    events = load_events(trace_path)

    assert len(events) == 2
    assert [e["type"] for e in events] == ["valid", "also_valid"]
    assert get_skipped_lines_count() == 3


def test_render_report_shows_skipped_count(tmp_test_dir):
    """Test that render_report shows skipped lines count in header."""
    from scripts.trace_report import load_events, render_report, get_skipped_lines_count

    trace_path = tmp_test_dir / "skip_test.jsonl"
    with open(trace_path, "w", encoding="utf-8") as f:
        f.write('{"type": "session_started", "session_id": "test", "customer_id": "c1", "model": "m1", "prompt_version": "v1", "system_prompt": "test", "ts": "2026-10-29T10:00:00Z", "turn_id": null, "step": null}\n')
        f.write('"bad line"\n')
        f.write('{"no_type": true}\n')

    events = load_events(trace_path)
    report = render_report(events, full=False)

    assert "2 unreadable lines skipped" in report


def test_render_header_with_system_prompt_changed_only(tmp_test_dir):
    """Test that header is rendered even when trace starts with system_prompt_changed."""
    from scripts.trace_report import render_report

    events = [
        {"type": "system_prompt_changed", "session_id": "test", "turn_id": None, "step": None,
         "prompt_version": "v2", "system_prompt": "New prompt",
         "ts": "2026-10-29T10:00:00Z"},
        {"type": "turn_started", "session_id": "test", "turn_id": "turn-1", "step": None,
         "event": {"kind": "customer_message"}, "stage": "identify",
         "ts": "2026-10-29T10:00:01Z"},
    ]

    report = render_report(events, full=False)

    # Header should still be rendered
    assert "# Agent Decision Trace" in report
    assert "**Session:** `test`" in report
    # System prompt should be in details
    assert "System Prompt" in report
    assert "New prompt" in report


def test_render_unknown_session_level_event(tmp_test_dir):
    """Test that unknown session-level events (turn_id null) are rendered raw."""
    from scripts.trace_report import render_report

    events = [
        {"type": "session_started", "session_id": "test", "customer_id": "cust-001",
         "model": "test-model", "prompt_version": "v1", "system_prompt": "Test",
         "ts": "2026-10-29T10:00:00Z", "turn_id": None, "step": None},
        {"type": "unknown_session_event", "session_id": "test", "turn_id": None, "step": None,
         "data": {"some": "payload"}, "ts": "2026-10-29T10:00:01Z"},
    ]

    report = render_report(events, full=False)

    # Unknown session event should be rendered as raw JSON
    assert "**Session event:** `unknown_session_event`" in report
    assert '"some": "payload"' in report or '"some":"payload"' in report
