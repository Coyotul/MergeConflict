import os
import pytest
import psycopg
from src.core.settings import load_rag_settings
from src.storage.application_db.migrate import apply_migrations


@pytest.fixture(scope="session")
def _session_db_setup():
    """Once per test session: connect, drop/recreate schema, apply migrations."""
    settings = load_rag_settings()
    test_db_url = os.getenv("RAG_TEST_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5433/rag_test")

    try:
        conn = psycopg.connect(test_db_url, autocommit=True)
    except (psycopg.OperationalError, psycopg.Error):
        pytest.skip("Test database unreachable")

    try:
        # Drop and recreate public schema
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")

        # Apply migrations
        apply_migrations(conn)

        yield
    finally:
        conn.close()


@pytest.fixture
def db_conn(_session_db_setup):
    """Function-scoped connection that truncates tables before each test."""
    test_db_url = os.getenv("RAG_TEST_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5433/rag_test")

    conn = psycopg.connect(test_db_url)

    # Truncate all tables before the test
    conn.execute("""
        TRUNCATE
            knowledge_chunk_links,
            knowledge_chunks,
            knowledge_document_versions,
            knowledge_documents,
            index_runs
        RESTART IDENTITY CASCADE
    """)
    conn.commit()

    yield conn

    conn.close()
