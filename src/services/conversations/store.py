"""Session storage implementations."""
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Protocol

from src.agent.orchestration.state import SessionState, StoredMessage
from src.core.errors import SessionNotFound, SessionVersionConflict


class SessionStore(Protocol):
    """Protocol for session storage."""

    def create(self, state: SessionState) -> None:
        """
        Create a new session.

        Raises:
            SessionVersionConflict: If session_id already exists.
        """
        ...

    def get(self, session_id: str) -> SessionState:
        """
        Retrieve a session by ID.

        Raises:
            SessionNotFound: If session does not exist.
        """
        ...

    def save(self, state: SessionState, expected_version: int) -> SessionState:
        """
        Save session state with optimistic locking.

        Returns a copy of the state with version incremented by 1.
        The updated_at field is not modified (orchestrator sets it).

        Args:
            state: The session state to save.
            expected_version: The version we expect the stored state to have.

        Returns:
            A copy of the state with version + 1.

        Raises:
            SessionVersionConflict: If stored version != expected_version.
        """
        ...

    def append_messages(self, session_id: str, messages: list[StoredMessage]) -> None:
        """
        Append messages to the session log.

        Raises:
            SessionNotFound: If session does not exist.
        """
        ...

    def messages(self, session_id: str) -> list[StoredMessage]:
        """
        Retrieve all messages for a session.

        Raises:
            SessionNotFound: If session does not exist.
        """
        ...


class InMemorySessionStore:
    """In-memory session store for development and testing."""

    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
        self._messages: dict[str, list[StoredMessage]] = {}

    def create(self, state: SessionState) -> None:
        """Create a new session."""
        if state.session_id in self._sessions:
            raise SessionVersionConflict(
                f"Session {state.session_id} already exists"
            )
        # Store a deep copy to prevent external mutation
        self._sessions[state.session_id] = deepcopy(state)
        self._messages[state.session_id] = []

    def get(self, session_id: str) -> SessionState:
        """Retrieve a session by ID."""
        if session_id not in self._sessions:
            raise SessionNotFound(f"Session {session_id} not found")
        # Return a deep copy to prevent external mutation
        return deepcopy(self._sessions[session_id])

    def save(self, state: SessionState, expected_version: int) -> SessionState:
        """Save session state with optimistic locking."""
        if state.session_id not in self._sessions:
            raise SessionNotFound(f"Session {state.session_id} not found")

        current = self._sessions[state.session_id]
        if current.version != expected_version:
            raise SessionVersionConflict(
                f"Session {state.session_id} version mismatch: "
                f"expected {expected_version}, got {current.version}"
            )

        # Create updated state with incremented version
        updated = state.model_copy(update={"version": state.version + 1})

        # Store a deep copy
        self._sessions[state.session_id] = deepcopy(updated)

        # Return a copy
        return updated

    def append_messages(self, session_id: str, messages: list[StoredMessage]) -> None:
        """Append messages to the session log."""
        if session_id not in self._sessions:
            raise SessionNotFound(f"Session {session_id} not found")

        # Store deep copies of messages
        self._messages[session_id].extend(deepcopy(msg) for msg in messages)

    def messages(self, session_id: str) -> list[StoredMessage]:
        """Retrieve all messages for a session."""
        if session_id not in self._sessions:
            raise SessionNotFound(f"Session {session_id} not found")
        # Return deep copies
        return [deepcopy(msg) for msg in self._messages[session_id]]


class FileSessionStore:
    """File-based session store that persists sessions to disk."""

    # Pattern for valid session IDs: 32 lowercase hex characters (uuid4().hex)
    _SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

    def __init__(self, root: Path):
        """
        Initialize file store.

        Args:
            root: Root directory for session storage.
        """
        self.root = root

    def _validate_session_id(self, session_id: str) -> None:
        """
        Validate session ID to prevent path traversal.

        Raises:
            SessionNotFound: If session_id is invalid.
        """
        if not self._SESSION_ID_PATTERN.match(session_id):
            raise SessionNotFound(f"Invalid session ID: {session_id}")

    def _session_dir(self, session_id: str) -> Path:
        """Get the directory path for a session."""
        self._validate_session_id(session_id)
        return self.root / session_id

    def _state_path(self, session_id: str) -> Path:
        """Get the state file path for a session."""
        return self._session_dir(session_id) / "state.json"

    def _messages_path(self, session_id: str) -> Path:
        """Get the messages file path for a session."""
        return self._session_dir(session_id) / "messages.jsonl"

    def create(self, state: SessionState) -> None:
        """Create a new session."""
        session_dir = self._session_dir(state.session_id)

        if session_dir.exists():
            raise SessionVersionConflict(
                f"Session {state.session_id} already exists"
            )

        session_dir.mkdir(parents=True, exist_ok=False)

        # Write initial state
        state_path = self._state_path(state.session_id)
        self._write_state_atomic(state_path, state)

        # Create empty messages file
        messages_path = self._messages_path(state.session_id)
        messages_path.touch()

    def get(self, session_id: str) -> SessionState:
        """Retrieve a session by ID."""
        state_path = self._state_path(session_id)

        if not state_path.exists():
            raise SessionNotFound(f"Session {session_id} not found")

        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return SessionState.model_validate(data)

    def save(self, state: SessionState, expected_version: int) -> SessionState:
        """Save session state with optimistic locking."""
        state_path = self._state_path(state.session_id)

        if not state_path.exists():
            raise SessionNotFound(f"Session {state.session_id} not found")

        # Read current version
        current = self.get(state.session_id)

        if current.version != expected_version:
            raise SessionVersionConflict(
                f"Session {state.session_id} version mismatch: "
                f"expected {expected_version}, got {current.version}"
            )

        # Create updated state with incremented version
        updated = state.model_copy(update={"version": state.version + 1})

        # Write atomically
        self._write_state_atomic(state_path, updated)

        return updated

    def append_messages(self, session_id: str, messages: list[StoredMessage]) -> None:
        """Append messages to the session log."""
        messages_path = self._messages_path(session_id)

        if not messages_path.exists():
            raise SessionNotFound(f"Session {session_id} not found")

        # Append to JSONL file
        with open(messages_path, "a", encoding="utf-8") as f:
            for msg in messages:
                line = msg.model_dump_json() + "\n"
                f.write(line)

    def messages(self, session_id: str) -> list[StoredMessage]:
        """Retrieve all messages for a session."""
        messages_path = self._messages_path(session_id)

        if not messages_path.exists():
            raise SessionNotFound(f"Session {session_id} not found")

        messages = []
        with open(messages_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:  # Skip empty lines
                    data = json.loads(line)
                    messages.append(StoredMessage.model_validate(data))

        return messages

    def _write_state_atomic(self, target_path: Path, state: SessionState) -> None:
        """
        Write state to file atomically using temp file + os.replace.

        Args:
            target_path: Final destination path.
            state: Session state to write.
        """
        # Write to temporary file in same directory
        temp_path = target_path.with_suffix(".tmp")

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(state.model_dump(mode="json"), f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replace
            os.replace(temp_path, target_path)
        finally:
            # Clean up temp file if it still exists
            if temp_path.exists():
                temp_path.unlink()
