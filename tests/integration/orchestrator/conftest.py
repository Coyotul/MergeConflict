import os
import pytest
import psycopg
from src.storage.application_db.migrate import apply_migrations


@pytest.fixture(scope="session")
def _session_db_setup():
    """Once per test session: connect, apply migrations."""
    test_db_url = os.getenv("RAG_TEST_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5433/rag_test")

    try:
        conn = psycopg.connect(test_db_url, autocommit=True, connect_timeout=5)
    except (psycopg.OperationalError, psycopg.Error):
        pytest.skip("Test database unreachable")

    try:
        # Apply migrations (idempotent - does not drop schema)
        apply_migrations(conn)

        yield
    finally:
        conn.close()


@pytest.fixture
def db_conn(_session_db_setup):
    """Function-scoped connection that truncates conversation tables before each test."""
    test_db_url = os.getenv("RAG_TEST_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5433/rag_test")

    conn = psycopg.connect(test_db_url)

    # Truncate conversation tables before the test
    conn.execute("""
        TRUNCATE
            conversation_messages,
            conversation_sessions
        RESTART IDENTITY CASCADE
    """)
    conn.commit()

    yield conn

    conn.close()
