from pathlib import Path
import psycopg


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply all pending migrations from migrations/ directory.

    Tracks applied migrations in schema_migrations table.
    Each migration runs in its own transaction.
    Returns list of newly applied filenames.
    """
    # Ensure schema_migrations table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename text PRIMARY KEY,
            applied_at timestamptz DEFAULT now()
        )
    """)
    conn.commit()

    # Find all migration files
    migrations_dir = Path(__file__).parent / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    # Get already applied migrations
    applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}

    # Apply pending migrations
    newly_applied = []
    for migration_file in migration_files:
        filename = migration_file.name
        if filename in applied:
            continue

        # Read and execute migration SQL in a transaction
        migration_sql = migration_file.read_text(encoding="utf-8")

        try:
            conn.execute(migration_sql)
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (filename,)
            )
            conn.commit()
            newly_applied.append(filename)
        except Exception:
            conn.rollback()
            raise

    return newly_applied
