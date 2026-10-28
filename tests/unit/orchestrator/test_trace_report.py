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
