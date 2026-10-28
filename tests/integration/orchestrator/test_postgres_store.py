"""Integration tests for PostgreSQL session store."""
import os
from datetime import datetime, timezone
from threading import Thread
from uuid import uuid4

import psycopg
import pytest

from src.agent.orchestration.state import SessionState, StoredMessage
from src.core.errors import SessionVersionConflict
from src.services.conversations.postgres_store import PostgresSessionStore

# Import contract tests from unit tests
from tests.unit.orchestrator.test_store import (
    test_create_get_round_trip,
    test_create_duplicate_raises_conflict,
    test_save_increments_version,
    test_stale_save_conflicts,
    test_messages_append_in_order,
    test_missing_session,
    test_save_does_not_mutate_updated_at,
)


def get_db_url():
    """Get test database URL from environment."""
    return os.getenv("RAG_TEST_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5433/rag_test")


@pytest.fixture
def store(db_conn) -> PostgresSessionStore:
    """PostgreSQL store fixture."""
    def connect():
        return psycopg.connect(get_db_url())

    return PostgresSessionStore(connect)


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


# Mark all tests as integration
pytestmark = pytest.mark.integration


@pytest.mark.integration
def test_concurrent_save_one_wins(store: PostgresSessionStore, sample_state: SessionState):
    """Test that concurrent saves with the same expected version result in one success, one conflict."""
    store.create(sample_state)

    # Simulate two concurrent saves with the same expected version
    results = []
    errors = []

    def save_state(state):
        try:
            updated = store.save(state, expected_version=0)
            results.append(updated)
        except SessionVersionConflict as e:
            errors.append(e)

    # Create two threads that will try to save simultaneously
    t1 = Thread(target=save_state, args=(sample_state,))
    t2 = Thread(target=save_state, args=(sample_state,))

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    # One should succeed, one should fail
    assert len(results) == 1
    assert len(errors) == 1

    # The successful save should have incremented version
    assert results[0].version == 1

    # Verify stored state has version 1
    retrieved = store.get(sample_state.session_id)
    assert retrieved.version == 1


@pytest.mark.integration
def test_messages_returned_in_insertion_order(store: PostgresSessionStore, sample_state: SessionState):
    """Test that messages are returned in insertion order (ORDER BY id)."""
    store.create(sample_state)

    now = datetime.now(timezone.utc)

    # Append messages in batches
    msg1 = StoredMessage(
        message_id="msg_1",
        turn_id="turn_1",
        role="customer",
        content="First",
        created_at=now,
    )
    msg2 = StoredMessage(
        message_id="msg_2",
        turn_id="turn_1",
        role="assistant",
        content="Second",
        created_at=now,
    )
    msg3 = StoredMessage(
        message_id="msg_3",
        turn_id="turn_2",
        role="customer",
        content="Third",
        created_at=now,
    )

    store.append_messages(sample_state.session_id, [msg1])
    store.append_messages(sample_state.session_id, [msg2])
    store.append_messages(sample_state.session_id, [msg3])

    messages = store.messages(sample_state.session_id)

    assert len(messages) == 3
    assert messages[0].message_id == "msg_1"
    assert messages[1].message_id == "msg_2"
    assert messages[2].message_id == "msg_3"
