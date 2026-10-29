"""PostgreSQL session store implementation."""
import json
from typing import Callable

import psycopg
from psycopg.errors import UniqueViolation, OperationalError

from src.agent.orchestration.state import SessionState, StoredMessage
from src.core.errors import SessionNotFound, SessionVersionConflict, ToolUnavailable


class PostgresSessionStore:
    """PostgreSQL-backed session store with optimistic locking."""

    def __init__(self, connect: Callable[[], psycopg.Connection]):
        """
        Initialize Postgres session store.

        Args:
            connect: Callable that returns a new psycopg.Connection.
        """
        self.connect = connect

    def create(self, state: SessionState) -> None:
        """
        Create a new session.

        Raises:
            SessionVersionConflict: If session_id already exists.
            ToolUnavailable: If database connection fails.
        """
        try:
            conn = self.connect()
        except (OperationalError, Exception) as e:
            raise ToolUnavailable(f"Database connection failed: {e}")

        try:
            state_json = state.model_dump_json()

            conn.execute(
                """
                INSERT INTO conversation_sessions
                    (session_id, customer_id, state, version, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    state.session_id,
                    state.customer_id,
                    state_json,
                    state.version,
                    state.created_at,
                    state.updated_at,
                ),
            )
            conn.commit()
        except UniqueViolation:
            conn.rollback()
            raise SessionVersionConflict(f"Session {state.session_id} already exists")
        except Exception as e:
            conn.rollback()
            raise ToolUnavailable(f"Database error: {e}")
        finally:
            conn.close()

    def get(self, session_id: str) -> SessionState:
        """
        Retrieve a session by ID.

        Raises:
            SessionNotFound: If session does not exist.
            ToolUnavailable: If database connection fails.
        """
        try:
            conn = self.connect()
        except (OperationalError, Exception) as e:
            raise ToolUnavailable(f"Database connection failed: {e}")

        try:
            result = conn.execute(
                "SELECT state FROM conversation_sessions WHERE session_id = %s",
                (session_id,),
            ).fetchone()

            if result is None:
                raise SessionNotFound(f"Session {session_id} not found")

            state_data = result[0]
            # PostgreSQL JSONB returns dict directly, not JSON string
            if isinstance(state_data, str):
                state_data = json.loads(state_data)
            return SessionState.model_validate(state_data)
        except SessionNotFound:
            raise
        except Exception as e:
            raise ToolUnavailable(f"Database error: {e}")
        finally:
            conn.close()

    def save(self, state: SessionState, expected_version: int) -> SessionState:
        """
        Save session state with optimistic locking.

        Returns a copy of the state with version incremented by 1.

        Args:
            state: The session state to save.
            expected_version: The version we expect the stored state to have.

        Returns:
            A copy of the state with version + 1.

        Raises:
            SessionVersionConflict: If stored version != expected_version.
            ToolUnavailable: If database connection fails.
        """
        try:
            conn = self.connect()
        except (OperationalError, Exception) as e:
            raise ToolUnavailable(f"Database connection failed: {e}")

        try:
            # Create updated state with incremented version
            updated = state.model_copy(update={"version": state.version + 1})
            state_json = updated.model_dump_json()

            # Update with version check
            result = conn.execute(
                """
                UPDATE conversation_sessions
                SET state = %s, version = version + 1, updated_at = now()
                WHERE session_id = %s AND version = %s
                RETURNING version
                """,
                (state_json, state.session_id, expected_version),
            )

            if result.rowcount == 0:
                # Check if session exists
                exists = conn.execute(
                    "SELECT version FROM conversation_sessions WHERE session_id = %s",
                    (state.session_id,),
                ).fetchone()

                if exists is None:
                    conn.rollback()
                    raise SessionNotFound(f"Session {state.session_id} not found")
                else:
                    conn.rollback()
                    raise SessionVersionConflict(
                        f"Session {state.session_id} version mismatch: "
                        f"expected {expected_version}, got {exists[0]}"
                    )

            conn.commit()
            return updated
        except (SessionNotFound, SessionVersionConflict):
            raise
        except Exception as e:
            conn.rollback()
            raise ToolUnavailable(f"Database error: {e}")
        finally:
            conn.close()

    def append_messages(self, session_id: str, messages: list[StoredMessage]) -> None:
        """
        Append messages to the session log.

        Raises:
            SessionNotFound: If session does not exist.
            ToolUnavailable: If database connection fails.
        """
        try:
            conn = self.connect()
        except (OperationalError, Exception) as e:
            raise ToolUnavailable(f"Database connection failed: {e}")

        try:
            # Check if session exists
            exists = conn.execute(
                "SELECT 1 FROM conversation_sessions WHERE session_id = %s",
                (session_id,),
            ).fetchone()

            if exists is None:
                raise SessionNotFound(f"Session {session_id} not found")

            # Insert messages
            for msg in messages:
                citations_json = json.dumps([c.model_dump() for c in msg.citations])
                conn.execute(
                    """
                    INSERT INTO conversation_messages
                        (session_id, message_id, turn_id, role, content, citations, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session_id,
                        msg.message_id,
                        msg.turn_id,
                        msg.role,
                        msg.content,
                        citations_json,
                        msg.created_at,
                    ),
                )

            conn.commit()
        except SessionNotFound:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            raise ToolUnavailable(f"Database error: {e}")
        finally:
            conn.close()

    def messages(self, session_id: str) -> list[StoredMessage]:
        """
        Retrieve all messages for a session in insertion order.

        Raises:
            SessionNotFound: If session does not exist.
            ToolUnavailable: If database connection fails.
        """
        try:
            conn = self.connect()
        except (OperationalError, Exception) as e:
            raise ToolUnavailable(f"Database connection failed: {e}")

        try:
            # Check if session exists
            exists = conn.execute(
                "SELECT 1 FROM conversation_sessions WHERE session_id = %s",
                (session_id,),
            ).fetchone()

            if exists is None:
                raise SessionNotFound(f"Session {session_id} not found")

            # Fetch messages in insertion order (ORDER BY id)
            rows = conn.execute(
                """
                SELECT message_id, turn_id, role, content, citations, created_at
                FROM conversation_messages
                WHERE session_id = %s
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()

            messages = []
            for row in rows:
                message_id, turn_id, role, content, citations_data, created_at = row
                # PostgreSQL JSONB returns list directly, not JSON string
                if isinstance(citations_data, str):
                    citations_data = json.loads(citations_data)
                messages.append(
                    StoredMessage(
                        message_id=message_id,
                        turn_id=turn_id,
                        role=role,
                        content=content,
                        citations=citations_data,
                        created_at=created_at,
                    )
                )

            return messages
        except SessionNotFound:
            raise
        except Exception as e:
            raise ToolUnavailable(f"Database error: {e}")
        finally:
            conn.close()
