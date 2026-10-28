"""Tests for session stores."""
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from src.agent.orchestration.state import SessionState, StoredMessage
from src.core.errors import SessionNotFound, SessionVersionConflict
from src.services.conversations.store import (
    FileSessionStore,
    InMemorySessionStore,
    SessionStore,
)


@pytest.fixture
def test_tmp_dir():
    """Create a temporary directory in the worktree."""
    tmp_dir = Path(__file__).parent / ".test_tmp"
    tmp_dir.mkdir(exist_ok=True)
    yield tmp_dir
    # Cleanup
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)


@pytest.fixture
def store_factories(test_tmp_dir):
    """Factory functions for creating store instances."""
    return {
        "memory": lambda: InMemorySessionStore(),
        "file": lambda: FileSessionStore(test_tmp_dir),
    }


@pytest.fixture(params=["memory", "file"])
def store(request, store_factories) -> SessionStore:
    """Parametrized fixture providing both store implementations."""
    factory = store_factories[request.param]
    return factory()


@pytest.fixture
def sample_state() -> SessionState:
    """Create a sample session state."""
    now = datetime.now(timezone.utc)
    return SessionState(
        session_id=uuid4().hex,
        customer_id="cust_123",
        created_at=now,
        updated_at=now,
        version=0,
        language="ro",
    )


@pytest.fixture
def sample_messages() -> list[StoredMessage]:
    """Create sample stored messages."""
    now = datetime.now(timezone.utc)
    return [
        StoredMessage(
            message_id="msg_1",
            turn_id="turn_1",
            role="customer",
            content="Hello",
            created_at=now,
        ),
        StoredMessage(
            message_id="msg_2",
            turn_id="turn_1",
            role="assistant",
            content="Hi there",
            created_at=now,
        ),
    ]


def test_create_get_round_trip(store: SessionStore, sample_state: SessionState):
    """Test creating and retrieving a session."""
    store.create(sample_state)
    retrieved = store.get(sample_state.session_id)

    assert retrieved.session_id == sample_state.session_id
    assert retrieved.customer_id == sample_state.customer_id
    assert retrieved.version == sample_state.version


def test_create_duplicate_raises_conflict(store: SessionStore, sample_state: SessionState):
    """Test that creating a duplicate session raises SessionVersionConflict."""
    store.create(sample_state)

    with pytest.raises(SessionVersionConflict):
        store.create(sample_state)


def test_save_increments_version(store: SessionStore, sample_state: SessionState):
    """Test that save increments version and returns updated state."""
    store.create(sample_state)

    # Save should increment version
    updated = store.save(sample_state, expected_version=0)
    assert updated.version == 1

    # Original state should be unchanged (returns a copy)
    assert sample_state.version == 0

    # Stored state should have incremented version
    retrieved = store.get(sample_state.session_id)
    assert retrieved.version == 1


def test_stale_save_conflicts(store: SessionStore, sample_state: SessionState):
    """Test that stale save raises SessionVersionConflict."""
    store.create(sample_state)

    # First save succeeds
    store.save(sample_state, expected_version=0)

    # Second save with stale version should fail
    with pytest.raises(SessionVersionConflict):
        store.save(sample_state, expected_version=0)


def test_messages_append_in_order(
    store: SessionStore, sample_state: SessionState, sample_messages: list[StoredMessage]
):
    """Test appending and retrieving messages in order."""
    store.create(sample_state)

    # Append first message
    store.append_messages(sample_state.session_id, [sample_messages[0]])
    messages = store.messages(sample_state.session_id)
    assert len(messages) == 1
    assert messages[0].message_id == "msg_1"

    # Append second message
    store.append_messages(sample_state.session_id, [sample_messages[1]])
    messages = store.messages(sample_state.session_id)
    assert len(messages) == 2
    assert messages[0].message_id == "msg_1"
    assert messages[1].message_id == "msg_2"


def test_missing_session(store: SessionStore, sample_state: SessionState):
    """Test that operations on missing session raise SessionNotFound."""
    session_id = uuid4().hex

    with pytest.raises(SessionNotFound):
        store.get(session_id)

    with pytest.raises(SessionNotFound):
        store.save(sample_state, expected_version=0)

    with pytest.raises(SessionNotFound):
        store.messages(session_id)

    with pytest.raises(SessionNotFound):
        store.append_messages(session_id, [])


def test_file_store_survives_new_instance(test_tmp_dir: Path, sample_state: SessionState):
    """Test that file store persists across instances."""
    # Create and populate first instance
    store1 = FileSessionStore(test_tmp_dir)
    store1.create(sample_state)
    store1.save(sample_state, expected_version=0)

    now = datetime.now(timezone.utc)
    message = StoredMessage(
        message_id="msg_1",
        turn_id="turn_1",
        role="customer",
        content="Test",
        created_at=now,
    )
    store1.append_messages(sample_state.session_id, [message])

    # Create new instance and verify data persists
    store2 = FileSessionStore(test_tmp_dir)
    retrieved = store2.get(sample_state.session_id)
    assert retrieved.version == 1

    messages = store2.messages(sample_state.session_id)
    assert len(messages) == 1
    assert messages[0].message_id == "msg_1"


def test_file_store_rejects_path_traversal(test_tmp_dir: Path):
    """Test that file store rejects path traversal attempts."""
    store = FileSessionStore(test_tmp_dir)

    # Test various path traversal patterns
    invalid_ids = [
        "../etc/passwd",
        "..\\windows\\system32",
        "../../",
        "abc/../def",
        "g",  # Too short
        "12345678901234567890123456789012X",  # Invalid character
        "ABCDEF12345678901234567890123456",  # Uppercase
    ]

    for invalid_id in invalid_ids:
        with pytest.raises(SessionNotFound):
            store.get(invalid_id)

        with pytest.raises(SessionNotFound):
            store.messages(invalid_id)

        with pytest.raises(SessionNotFound):
            store.append_messages(invalid_id, [])


def test_save_does_not_mutate_updated_at(store: SessionStore, sample_state: SessionState):
    """Test that save returns updated state without mutating updated_at."""
    store.create(sample_state)

    original_updated_at = sample_state.updated_at
    updated = store.save(sample_state, expected_version=0)

    # Returned state should have same updated_at (orchestrator sets it)
    assert updated.updated_at == original_updated_at


def test_memory_store_returns_deep_copies(sample_state: SessionState):
    """Test that memory store returns deep copies to prevent mutation."""
    store = InMemorySessionStore()
    store.create(sample_state)

    # Get the state and modify it
    retrieved = store.get(sample_state.session_id)
    retrieved.customer_id = "modified_customer"

    # Original stored state should be unchanged
    retrieved_again = store.get(sample_state.session_id)
    assert retrieved_again.customer_id == "cust_123"
