"""Session trace recording.

Writes one append-only JSONL file per session that records every decision,
model call, tool call, and turn outcome for debugging and evaluation.
"""
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger("src.agent.trace")


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)


def _json_serializer(obj: Any) -> str:
    """Custom JSON serializer for datetime and other types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def truncate_payload(value: Any, limit: int = 20000) -> tuple[Any, bool]:
    """Truncate large payloads to a size limit.

    Args:
        value: The value to potentially truncate
        limit: Maximum character count for serialized value

    Returns:
        Tuple of (potentially truncated value, was_truncated boolean)
    """
    # Serialize to check size
    if isinstance(value, (str, bytes)):
        if len(value) > limit:
            return value[:limit], True
        return value, False

    # For other types, serialize and check
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=_json_serializer)
        if len(serialized) > limit:
            # Truncate the serialized form
            truncated = serialized[:limit]
            # Try to parse it back, if it fails just return the truncated string
            try:
                return json.loads(truncated), True
            except json.JSONDecodeError:
                return truncated, True
        return value, False
    except (TypeError, ValueError):
        # Can't serialize, return as-is
        return value, False


class Tracer(Protocol):
    """Protocol for session trace recording."""

    def record(
        self,
        session_id: str,
        turn_id: str | None,
        step: int | None,
        type: str,
        **payload: Any
    ) -> None:
        """Record a trace event.

        Args:
            session_id: Session identifier
            turn_id: Turn identifier (None for session-level events)
            step: Step number within turn (None for non-step events)
            type: Event type
            **payload: Additional event-specific fields
        """
        ...

    def needs_system_prompt(self, session_id: str, prompt_version: str) -> bool:
        """Check if system prompt needs to be written for this session.

        Returns True when this session's file has no prompt yet or a different
        version. After it returns True, the caller writes session_started or
        system_prompt_changed, and the tracer remembers the version.

        Args:
            session_id: Session identifier
            prompt_version: Current system prompt version

        Returns:
            True if prompt should be written
        """
        ...


class NullTracer:
    """No-op tracer that does nothing."""

    def record(
        self,
        session_id: str,
        turn_id: str | None,
        step: int | None,
        type: str,
        **payload: Any
    ) -> None:
        """Record nothing."""
        pass

    def needs_system_prompt(self, session_id: str, prompt_version: str) -> bool:
        """Always return False (no prompt needed)."""
        return False


class InMemoryTracer:
    """In-memory tracer for testing."""

    def __init__(self):
        self.events: list[dict] = []
        self._prompt_versions: dict[str, str] = {}

    def record(
        self,
        session_id: str,
        turn_id: str | None,
        step: int | None,
        type: str,
        **payload: Any
    ) -> None:
        """Record event to memory."""
        event = {
            "ts": utc_now().isoformat(),
            "session_id": session_id,
            "turn_id": turn_id,
            "step": step,
            "type": type,
            **payload
        }
        self.events.append(event)

        # Track prompt versions
        if type in ("session_started", "system_prompt_changed"):
            if "prompt_version" in payload:
                self._prompt_versions[session_id] = payload["prompt_version"]

    def needs_system_prompt(self, session_id: str, prompt_version: str) -> bool:
        """Check if prompt version has changed."""
        current = self._prompt_versions.get(session_id)
        if current is None:
            return True
        return current != prompt_version


class FileTracer:
    """File-based tracer that writes JSONL files."""

    # Pattern for valid session IDs: 32 lowercase hex characters
    _SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

    def __init__(self, root: Path, clock: Callable[[], datetime] = utc_now):
        """Initialize file tracer.

        Args:
            root: Root directory for trace files
            clock: Clock function for timestamps (for testing)
        """
        self.root = root
        self.clock = clock
        # Track which sessions we've failed to write to (log once per session)
        self._failed_sessions: set[str] = set()
        # Track prompt versions per session
        self._prompt_versions: dict[str, str] = {}

    def _validate_session_id(self, session_id: str) -> bool:
        """Validate session ID format.

        Returns:
            True if valid, False otherwise
        """
        return bool(self._SESSION_ID_PATTERN.match(session_id))

    def _trace_path(self, session_id: str) -> Path:
        """Get the trace file path for a session."""
        return self.root / f"{session_id}.jsonl"

    def _load_prompt_version(self, session_id: str) -> str | None:
        """Load the current prompt version from the trace file.

        Returns:
            The prompt version if found, None otherwise
        """
        trace_path = self._trace_path(session_id)
        if not trace_path.exists():
            return None

        try:
            with open(trace_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line)
                        if event.get("type") in ("session_started", "system_prompt_changed"):
                            if "prompt_version" in event:
                                return event["prompt_version"]
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        continue
        except (OSError, IOError):
            # Can't read file, assume no version
            return None

        return None

    def record(
        self,
        session_id: str,
        turn_id: str | None,
        step: int | None,
        type: str,
        **payload: Any
    ) -> None:
        """Record event to file.

        Validates session_id and swallows write errors (logging once per session).
        """
        # Validate session ID
        if not self._validate_session_id(session_id):
            return

        # Skip if we've already failed to write to this session
        if session_id in self._failed_sessions:
            return

        # Build event
        event = {
            "ts": self.clock().isoformat(),
            "session_id": session_id,
            "turn_id": turn_id,
            "step": step,
            "type": type,
            **payload
        }

        # Track prompt versions in memory
        if type in ("session_started", "system_prompt_changed"):
            if "prompt_version" in payload:
                self._prompt_versions[session_id] = payload["prompt_version"]

        # Write to file
        try:
            trace_path = self._trace_path(session_id)

            # Ensure parent directory exists
            trace_path.parent.mkdir(parents=True, exist_ok=True)

            # Append to file
            with open(trace_path, "a", encoding="utf-8") as f:
                json.dump(event, f, ensure_ascii=False, default=_json_serializer)
                f.write("\n")
                f.flush()

        except (OSError, IOError, TypeError, ValueError) as e:
            # Log warning once per session
            if session_id not in self._failed_sessions:
                logger.warning(
                    "Failed to write trace event for session %s: %s",
                    session_id, str(e)
                )
                self._failed_sessions.add(session_id)

    def needs_system_prompt(self, session_id: str, prompt_version: str) -> bool:
        """Check if system prompt needs to be written.

        Reads from file on first use for this session to handle tracer restarts.
        """
        # Check memory cache first
        if session_id in self._prompt_versions:
            return self._prompt_versions[session_id] != prompt_version

        # Load from file
        current = self._load_prompt_version(session_id)
        if current is not None:
            self._prompt_versions[session_id] = current
            return current != prompt_version

        # No version found, prompt is needed
        return True
