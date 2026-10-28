import pytest
from src.storage.application_db.migrate import apply_migrations


@pytest.mark.integration
def test_schema_created(db_conn):
    exts = {r[0] for r in db_conn.execute("select extname from pg_extension")}
    assert {"vector", "unaccent"} <= exts
    tables = {r[0] for r in db_conn.execute(
        "select tablename from pg_tables where schemaname='public'")}
    assert {"knowledge_documents", "knowledge_document_versions",
            "knowledge_chunks", "knowledge_chunk_links", "index_runs", "schema_migrations"} <= tables


@pytest.mark.integration
def test_unaccent_search_config_matches_without_diacritics(db_conn):
    row = db_conn.execute(
        "select to_tsvector('ro_unaccent', 'Dobânda fixă') @@ to_tsquery('ro_unaccent', 'dobanda')").fetchone()
    assert row[0] is True


@pytest.mark.integration
def test_apply_migrations_is_idempotent(db_conn):
    assert apply_migrations(db_conn) == []
