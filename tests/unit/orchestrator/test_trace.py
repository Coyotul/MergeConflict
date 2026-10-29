"""Tests for session trace recording."""
import json
import shutil
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from src.agent.orchestration.trace import (
    FileTracer,
    InMemoryTracer,
    NullTracer,
    truncate_payload,
)
from src.core.composition import build_tracer
from src.core.settings import OrchestratorSettings, load_orchestrator_settings


@pytest.fixture
def test_tmp_dir():
    """Create a temporary directory in the worktree (separate from test_store's .test_tmp)."""
    tmp_dir = Path(__file__).parent / ".test_tmp_trace" / uuid4().hex
    tmp_dir.mkdir(parents=True, exist_ok=True)
    yield tmp_dir
    # Cleanup with permission restoration
    if tmp_dir.exists():
        try:
            # Restore write permissions in case test modified them
            import os
            for root, dirs, files in os.walk(tmp_dir):
                os.chmod(root, 0o755)
                for fname in files:
                    os.chmod(os.path.join(root, fname), 0o644)
            shutil.rmtree(tmp_dir)
        except Exception:
            # If cleanup fails, at least try basic rmtree
            shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def valid_session_id():
    """A valid session ID (32 lowercase hex characters)."""
    return uuid4().hex


@pytest.fixture
def invalid_session_id():
    """An invalid session ID (contains uppercase or invalid characters)."""
    return "INVALID_SESSION_123"


def test_file_tracer_writes_jsonl_lines(test_tmp_dir, valid_session_id):
    """FileTracer writes valid JSON lines with all required fields."""
    tracer = FileTracer(test_tmp_dir)

    # Record two events
    tracer.record(
        session_id=valid_session_id,
        turn_id="turn_1",
        step=1,
        type="model_call",
        latency_ms=123,
        usage={"prompt_tokens": 100, "completion_tokens": 50},
    )

    tracer.record(
        session_id=valid_session_id,
        turn_id="turn_1",
        step=2,
        type="tool_call",
        tool="test_tool",
        output={"result": Decimal("123.45")},
        timestamp=datetime(2024, 1, 15, 12, 30, 0, tzinfo=timezone.utc),
    )

    # Read and verify
    trace_file = test_tmp_dir / f"{valid_session_id}.jsonl"
    assert trace_file.exists()

    with open(trace_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 2

    # Parse first line
    event1 = json.loads(lines[0])
    assert "ts" in event1
    assert event1["session_id"] == valid_session_id
    assert event1["turn_id"] == "turn_1"
    assert event1["step"] == 1
    assert event1["type"] == "model_call"
    assert event1["latency_ms"] == 123
    assert event1["usage"]["prompt_tokens"] == 100

    # Parse second line
    event2 = json.loads(lines[1])
    assert event2["session_id"] == valid_session_id
    assert event2["type"] == "tool_call"
    assert event2["tool"] == "test_tool"
    # Decimal should serialize as string
    assert event2["output"]["result"] == "123.45"
    # Datetime should serialize
    assert event2["timestamp"] == "2024-01-15T12:30:00+00:00"


def test_file_tracer_appends_across_instances(test_tmp_dir, valid_session_id):
    """Multiple FileTracer instances append to the same file."""
    # First instance writes one event
    tracer1 = FileTracer(test_tmp_dir)
    tracer1.record(valid_session_id, "turn_1", 1, "turn_started", stage="identify")

    # Second instance writes another event
    tracer2 = FileTracer(test_tmp_dir)
    tracer2.record(valid_session_id, "turn_1", 2, "turn_finished", outcome="replied")

    # Verify both events are in the file
    trace_file = test_tmp_dir / f"{valid_session_id}.jsonl"
    with open(trace_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 2
    event1 = json.loads(lines[0])
    event2 = json.loads(lines[1])
    assert event1["type"] == "turn_started"
    assert event2["type"] == "turn_finished"


def test_invalid_session_id_skipped(test_tmp_dir, invalid_session_id):
    """FileTracer skips events with invalid session IDs."""
    tracer = FileTracer(test_tmp_dir)

    # Record with invalid session ID (should be skipped silently)
    tracer.record(invalid_session_id, "turn_1", 1, "test_event", data="test")

    # No file should be created
    trace_file = test_tmp_dir / f"{invalid_session_id}.jsonl"
    assert not trace_file.exists()


def test_file_tracer_swallows_write_errors(test_tmp_dir, valid_session_id, caplog):
    """FileTracer swallows write errors and logs a warning once per session."""
    # Create a file where the root should be (to cause write error)
    bad_root = test_tmp_dir / "bad_root.txt"
    bad_root.write_text("blocking file")

    tracer = FileTracer(bad_root)

    with caplog.at_level(logging.WARNING, logger="src.agent.trace"):
        # First write attempt should log a warning
        tracer.record(valid_session_id, "turn_1", 1, "test_event", data="test")
        assert len(caplog.records) == 1
        assert "failed to write" in caplog.text.lower()

        # Second write attempt for the same session should not log again
        caplog.clear()
        tracer.record(valid_session_id, "turn_1", 2, "test_event", data="test2")
        assert len(caplog.records) == 0


def test_system_prompt_once_across_instances(test_tmp_dir, valid_session_id):
    """needs_system_prompt returns true only once per version, across instances."""
    tracer1 = FileTracer(test_tmp_dir)

    # First check should return True (no prompt written yet)
    assert tracer1.needs_system_prompt(valid_session_id, "v1.0") is True

    # Simulate writing session_started with prompt
    tracer1.record(
        valid_session_id, None, None, "session_started",
        prompt_version="v1.0", system_prompt="Test prompt"
    )

    # Second check with same version should return False
    assert tracer1.needs_system_prompt(valid_session_id, "v1.0") is False

    # New FileTracer instance should also return False for same version
    tracer2 = FileTracer(test_tmp_dir)
    assert tracer2.needs_system_prompt(valid_session_id, "v1.0") is False

    # Different version should return True
    assert tracer2.needs_system_prompt(valid_session_id, "v2.0") is True

    # Write system_prompt_changed for new version
    tracer2.record(
        valid_session_id, None, None, "system_prompt_changed",
        prompt_version="v2.0", system_prompt="New prompt"
    )

    # Check should now return False
    assert tracer2.needs_system_prompt(valid_session_id, "v2.0") is False


def test_last_prompt_version_wins_across_instances(test_tmp_dir, valid_session_id):
    """A restarted tracer uses the LAST prompt version in the file, not the first."""
    writer = FileTracer(test_tmp_dir)
    writer.record(valid_session_id, None, None, "session_started", prompt_version="v1", system_prompt="one")
    writer.record(valid_session_id, "t1", 1, "system_prompt_changed", prompt_version="v2", system_prompt="two")

    restarted = FileTracer(test_tmp_dir)
    assert restarted.needs_system_prompt(valid_session_id, "v2") is False
    assert restarted.needs_system_prompt(valid_session_id, "v1") is True


def test_truncation_marker():
    """truncate_payload truncates long values and adds a marker."""
    # Short value - no truncation
    value, truncated = truncate_payload("short text", limit=100)
    assert value == "short text"
    assert truncated is False

    # Long string - truncated
    long_str = "x" * 30000
    value, truncated = truncate_payload(long_str, limit=20000)
    assert len(value) == 20000
    assert value == "x" * 20000
    assert truncated is True

    # Dict with long value - should return truncated JSON string
    large_dict = {"data": "y" * 30000}
    value, truncated = truncate_payload(large_dict, limit=20000)
    assert truncated is True
    assert isinstance(value, str)
    assert len(value) == 20000

    # List with long content - should return truncated JSON string
    large_list = ["z" * 10000, "a" * 10000, "b" * 10000]
    value, truncated = truncate_payload(large_list, limit=20000)
    assert truncated is True
    assert isinstance(value, str)
    assert len(value) == 20000


def test_settings_trace_defaults_and_env():
    """OrchestratorSettings has trace fields with defaults and env loading."""
    # Test defaults
    settings = OrchestratorSettings()
    assert settings.trace == "file"
    assert settings.traces_dir == Path("data/local/traces")

    # Test env loading
    env = {
        "ORCHESTRATOR_TRACE": "off",
        "ORCHESTRATOR_TRACES_DIR": "custom/traces",
    }
    settings = load_orchestrator_settings(env)
    assert settings.trace == "off"
    assert settings.traces_dir == Path("custom/traces")


def test_build_tracer_off_returns_null():
    """build_tracer returns NullTracer when trace is 'off'."""
    settings = OrchestratorSettings(trace="off")
    tracer = build_tracer(settings)
    assert isinstance(tracer, NullTracer)


def test_null_tracer_does_nothing():
    """NullTracer record and needs_system_prompt do nothing."""
    tracer = NullTracer()
    # Should not raise
    tracer.record("session_id", "turn_id", 1, "test", data="test")
    assert tracer.needs_system_prompt("session_id", "v1.0") is False


def test_in_memory_tracer_stores_events():
    """InMemoryTracer stores events in a list."""
    tracer = InMemoryTracer()

    tracer.record("sess_1", "turn_1", 1, "model_call", latency_ms=100)
    tracer.record("sess_1", "turn_1", 2, "tool_call", tool="test")

    assert len(tracer.events) == 2
    assert tracer.events[0]["type"] == "model_call"
    assert tracer.events[0]["session_id"] == "sess_1"
    assert tracer.events[1]["type"] == "tool_call"


class BadObject:
    """Object whose __str__ raises an exception."""
    def __str__(self):
        raise RuntimeError("Cannot serialize")


def test_file_tracer_handles_bad_serialization(test_tmp_dir, valid_session_id, caplog):
    """FileTracer handles objects that raise on serialization without propagating exception."""
    tracer = FileTracer(test_tmp_dir)

    with caplog.at_level(logging.WARNING, logger="src.agent.trace"):
        # Record with an object that raises on __str__
        tracer.record(valid_session_id, "turn_1", 1, "test_event", bad_obj=BadObject())

        # Should log a warning
        assert len(caplog.records) == 1
        assert "failed to write" in caplog.text.lower()

        # Second attempt should not log again (already failed for this session)
        caplog.clear()
        tracer.record(valid_session_id, "turn_1", 2, "test_event", data="test")
        assert len(caplog.records) == 0


def test_file_tracer_handles_bad_clock(test_tmp_dir, valid_session_id, caplog):
    """FileTracer handles clock that raises without propagating exception."""
    def bad_clock():
        raise RuntimeError("Clock failure")

    tracer = FileTracer(test_tmp_dir, clock=bad_clock)

    with caplog.at_level(logging.WARNING, logger="src.agent.trace"):
        # Record should not raise even though clock raises
        tracer.record(valid_session_id, "turn_1", 1, "test_event", data="test")

        # Should log a warning
        assert len(caplog.records) == 1
        assert "failed to write" in caplog.text.lower()


def test_in_memory_tracer_handles_bad_serialization():
    """InMemoryTracer does not raise even with bad objects."""
    tracer = InMemoryTracer()

    # Should not raise
    tracer.record("sess_1", "turn_1", 1, "test_event", bad_obj=BadObject())

    # Event should still be recorded (we store as-is, don't serialize)
    assert len(tracer.events) == 1


def test_truncate_payload_returns_string_for_complex():
    """truncate_payload returns JSON string for non-str/bytes values."""
    # Dict - should return string
    value, truncated = truncate_payload({"key": "value"}, limit=100)
    assert isinstance(value, str)
    assert value == '{"key": "value"}'
    assert truncated is False

    # List - should return string
    value, truncated = truncate_payload([1, 2, 3], limit=100)
    assert isinstance(value, str)
    assert value == '[1, 2, 3]'
    assert truncated is False

    # Large dict - should return truncated string
    large_dict = {"data": "x" * 30000}
    value, truncated = truncate_payload(large_dict, limit=100)
    assert isinstance(value, str)
    assert len(value) == 100
    assert truncated is True


def test_file_tracer_keeps_trying_after_failure(test_tmp_dir, valid_session_id, caplog):
    """FileTracer keeps trying to write after a transient failure."""
    from unittest.mock import patch, mock_open

    tracer = FileTracer(test_tmp_dir)
    trace_file = test_tmp_dir / f"{valid_session_id}.jsonl"

    # Mock open to fail twice, then succeed
    call_count = {"count": 0}
    original_open = open

    def mock_open_fn(path, *args, **kwargs):
        if str(path).endswith(".jsonl") and call_count["count"] < 2:
            call_count["count"] += 1
            raise OSError("Simulated write failure")
        return original_open(path, *args, **kwargs)

    with caplog.at_level(logging.WARNING, logger="src.agent.trace"):
        with patch("builtins.open", side_effect=mock_open_fn):
            # First write should fail and log
            tracer.record(valid_session_id, "turn_1", 1, "test_event", data="first")
            assert len(caplog.records) == 1

            # Second write should also fail but NOT log again (already warned)
            caplog.clear()
            tracer.record(valid_session_id, "turn_1", 2, "test_event", data="second")
            assert len(caplog.records) == 0

        # Third write should succeed (no more mock)
        tracer.record(valid_session_id, "turn_1", 3, "test_event", data="third")

    # Verify the third event was written
    assert trace_file.exists()
    with open(trace_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Should have only the third event (first two failed)
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["data"] == "third"


def test_file_tracer_validates_session_id_in_needs_system_prompt(test_tmp_dir, invalid_session_id):
    """needs_system_prompt returns False for invalid session IDs without touching filesystem."""
    tracer = FileTracer(test_tmp_dir)

    # Should return False for invalid session ID
    assert tracer.needs_system_prompt(invalid_session_id, "v1.0") is False

    # Should not create any files
    assert not (test_tmp_dir / f"{invalid_session_id}.jsonl").exists()


def test_file_tracer_validates_session_id_in_load_prompt_version(test_tmp_dir, invalid_session_id):
    """_load_prompt_version returns None for invalid session IDs without touching filesystem."""
    tracer = FileTracer(test_tmp_dir)

    # Should return None for invalid session ID
    result = tracer._load_prompt_version(invalid_session_id)
    assert result is None

    # Should not attempt to read any files
    assert not (test_tmp_dir / f"{invalid_session_id}.jsonl").exists()
